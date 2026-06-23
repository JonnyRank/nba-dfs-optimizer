import io
import os
import glob
import re
from typing import Literal

import pandas as pd
from datetime import datetime
from typing import Tuple, List, Optional


def get_latest_file(directory: str, pattern: str, use_mtime: bool = False) -> str:
    """
    Finds the most recent file matching a pattern in a directory.
    Replaces redundant implementations in ranker.py, exporter.py, engine.py, etc.
    """
    files = glob.glob(os.path.join(directory, pattern))
    if not files:
        raise FileNotFoundError(f"No files matching '{pattern}' found in {directory}")

    # exposure_report.py uses getmtime, while others rely on alphabetical timestamp sorting via basename
    if use_mtime:
        return max(files, key=os.path.getmtime)
    return max(files, key=os.path.basename)


def extract_player_id(player_string: str) -> Optional[str]:
    """
    Extracts the DraftKings numeric ID from a "Name (ID)" string.
    Consolidates regex logic from ranker.py, exposure_report.py, and late_swapper_v1.1.py.
    """
    if pd.isna(player_string):
        return None
    match = re.search(r"\((\d+)\)", str(player_string))
    return match.group(1) if match else None


def is_player_locked(player_string: str) -> bool:
    """
    Determines if a player string contains the (LOCKED) indicator.
    """
    if pd.isna(player_string):
        return False
    return "(LOCKED)" in str(player_string).upper()


def parse_game_time(game_info: str) -> datetime:
    """
    Extracts datetime from a DraftKings game info string (e.g., "MIA@PHI 02/25/2026 07:00PM ET").
    Unifies the time parsing logic found in engine.py and late_swapper_v1.1.py.
    """
    match = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}[AP]M)", str(game_info))
    if not match:
        return datetime.max  # Fallback to push invalid times to the end
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y %I:%M%p")
    except ValueError:
        return datetime.max


def derive_game_key(team, opponent, game_info: str = "") -> str:
    """Return a canonical, order-independent game identifier (e.g. "ATL@DET").

    During late swap, DraftKings replaces the "Game Info" matchup string with
    "In Progress" once a game has started, which erases the team pairing. The
    team/opponent pair from the projections feed survives that, so it is the
    preferred source: both LAL(opp IND) and IND(opp LAL) collapse to the same
    "IND@LAL" key regardless of which side a player is on. Fallbacks, in order:
    parse a matchup out of "Game Info" (works for not-yet-started games), then
    the team alone (the only remaining signal for an in-progress player who is
    missing from projections).
    """
    ta = "" if pd.isna(team) else str(team).strip()
    opp = "" if pd.isna(opponent) else str(opponent).strip()
    if ta and opp:
        return "@".join(sorted([ta, opp]))

    gi = "" if pd.isna(game_info) else str(game_info).strip()
    match = re.match(r"\s*([A-Za-z]{2,4})@([A-Za-z]{2,4})", gi)
    if match:
        return "@".join(sorted([match.group(1).upper(), match.group(2).upper()]))

    if ta:
        return ta
    if opp:
        return opp
    return gi.split(" ")[0] if gi else ""


def read_ragged_csv(
    file_path: str, max_columns: int = 25
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Safely reads a CSV with ragged rows (like the DKEntries template) by padding with dummy columns.
    Extracts the robust parsing logic previously localized in exporter.py and late_swapper_v1.1.py.

    Returns:
        Tuple containing the padded DataFrame and a list of the valid (original) column names.
    """
    header_df = pd.read_csv(file_path, nrows=0)
    valid_cols = header_df.columns.tolist()

    extra_count = max(0, max_columns - len(valid_cols))
    all_cols = valid_cols + [f"extra_{i}" for i in range(extra_count)]

    df = pd.read_csv(
        file_path,
        header=None,
        names=all_cols,
        skiprows=1,
        dtype={"Entry ID": object, "Contest ID": object},
        engine="python",
    )
    return df, valid_cols


def parse_dk_entries(entries_file: str) -> pd.DataFrame:
    """Parse the DKEntries CSV player-pool section into a DataFrame.

    Searches for the header row containing "Position,Name + ID,Name,ID"
    (which may appear after contest metadata rows) and reads everything
    from that header onward. Works for both the pre-lock (engine) and
    post-lock (late-swap) variants of the DraftKings export because both
    use the same player-pool section format.

    Returns a DataFrame with ID normalized to a plain integer string and
    rows with a missing ID dropped.
    """
    with open(entries_file, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    pool_start = -1
    for i, line in enumerate(lines):
        if "Position,Name + ID,Name,ID" in line:
            pool_start = i
            break

    if pool_start == -1:
        raise ValueError(f"Could not find player pool section in {entries_file}")

    df_players = pd.read_csv(io.StringIO("".join(lines[pool_start:])))
    df_players = df_players.dropna(subset=["ID"]).copy()
    df_players["ID"] = df_players["ID"].astype(str).str.split(".").str[0]
    return df_players


def merge_player_pool(
    df_players: pd.DataFrame, df_projs: pd.DataFrame, how: Literal["inner", "left"]
) -> pd.DataFrame:
    """Merge a parsed player-pool DataFrame with a projections DataFrame.

    Normalizes ``ID`` on the projections side before merging. After the
    merge, casts ``Salary`` to numeric and, for ``how="left"`` merges,
    fills any missing ``Projection`` values with 0 (retaining current-
    lineup players who have no projection entry).

    Args:
        df_players: Output of ``parse_dk_entries``.
        df_projs: Raw projections CSV loaded via ``pd.read_csv``.
        how: ``"inner"`` for engine (only projected players) or
            ``"left"`` for late-swap (retain all pool players).

    Returns:
        Merged DataFrame ready for column-level additions (StartTime, Game).
    """
    df_projs = df_projs.copy()
    # Normalize projs ID the same way as parse_dk_entries: if any ID is NaN,
    # pandas reads the column as float64 and astype(str) would give "12345.0",
    # which would silently fail to match the "12345" IDs from parse_dk_entries.
    df_projs["ID"] = df_projs["ID"].astype(str).str.split(".").str[0]
    # Drop DK-owned columns from projs to avoid _x/_y suffix collisions.
    # df_players (from DKEntries) is authoritative for these values.
    df_projs = df_projs.drop(
        columns=["Name", "Salary", "Position", "Roster Position", "Game Info"],
        errors="ignore",
    )
    df_merged = pd.merge(df_players, df_projs, on="ID", how=how)
    df_merged["Salary"] = pd.to_numeric(df_merged["Salary"])
    if "Projection" in df_merged.columns:
        df_merged["Projection"] = pd.to_numeric(df_merged["Projection"])
        if how == "left":
            df_merged["Projection"] = df_merged["Projection"].fillna(0)
    return df_merged
