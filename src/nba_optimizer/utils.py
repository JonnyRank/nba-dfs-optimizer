import os
import glob
import re
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