"""Slate facts (locks, games, contests, entries) and the per-slate folder (O-0)."""

import os
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from .config import SLATE_TYPES, Config  # noqa: F401  (SLATE_TYPES re-exported)
from .records import (
    SCHEMA_VERSION,
    read_json,
    read_lineup_file,
    sha256_file,
    snapshot_input,
    write_json_atomic,
)
from .inputs import MATCH_MIN, id_match, player_ids
from .utils import parse_dk_entries

ET = ZoneInfo("America/New_York")
SLATE_FILE = "slate.json"
PRE_L0_ENTRIES = "Pre-L0-DKEntries.csv"
GAME_INFO_RE = re.compile(r"^([A-Za-z]{2,4})@([A-Za-z]{2,4}) (\d{2}/\d{2}/\d{4} \d{2}:\d{2}[AP]M) ET$")


def _parse_game_info(game_info) -> Optional[Tuple[str, datetime]]:
    """("PHI@NYK", aware ET start) for a pre-lock Game Info string, else None."""
    match = GAME_INFO_RE.match(str(game_info).strip())
    if not match:
        return None
    start = datetime.strptime(match.group(3), "%m/%d/%Y %I:%M%p").replace(tzinfo=ET)
    return f"{match.group(1).upper()}@{match.group(2).upper()}", start


def _games_in_pool(df_players: pd.DataFrame) -> Dict[str, datetime]:
    games = {}
    for gi in df_players["Game Info"]:
        parsed = _parse_game_info(gi)
        if parsed:
            games[parsed[0]] = parsed[1]
    return games


def build_slate(entries_file: str, slate_type: str) -> dict:
    """Build slate facts from a pre-lock DKEntries file.

    Raises ValueError if any player's Game Info shows ``In Progress``/``Final``
    or can't be parsed: slate facts must come from the night's first download.
    """
    df_players = parse_dk_entries(entries_file)
    name = os.path.basename(entries_file)
    bad = [gi for gi in df_players["Game Info"] if _parse_game_info(gi) is None]
    if bad:
        started = sum(str(gi).strip() in ("In Progress", "Final") for gi in bad)
        if started:
            raise ValueError(
                f"{name}: {started} player(s) show In Progress/Final; "
                "first run of the night needs a pre-lock DKEntries"
            )
        raise ValueError(f"{name}: unparseable Game Info {bad[:3]}")

    teams: Dict[str, str] = {}
    games: Dict[str, datetime] = {}
    for _, row in df_players.iterrows():
        game, start = _parse_game_info(row["Game Info"])
        games[game] = start
        teams[str(row["TeamAbbrev"]).strip()] = game

    starts = sorted(set(games.values()))
    locks = [
        {"lock": k, "start": t.isoformat(), "games": sorted(g for g, s in games.items() if s == t)}
        for k, t in enumerate(starts)
    ]
    slate_date = starts[0].date().isoformat()

    df_entries = read_lineup_file(entries_file)
    contests = []
    for cid, group in df_entries.groupby("contest_id", sort=False):
        fee = str(group["entry_fee"].iloc[0]).strip().lstrip("$").replace(",", "")
        contests.append({
            "contest_id": int(cid),
            "name": group["contest_name"].iloc[0],
            "entry_fee": float(fee) if fee else None,
            "n_entries": int(len(group)),
        })

    return {
        "schema": SCHEMA_VERSION,
        "slate_id": f"{slate_date}_classic_{slate_type}",
        "slate_date": slate_date,
        "slate_type": slate_type,
        "source_file": name,
        "source_sha256": sha256_file(entries_file),
        "n_players": int(len(df_players)),
        "locks": locks,
        "teams": dict(sorted(teams.items())),
        "contests": contests,
        "entry_ids": df_entries["entry_id"].tolist(),
    }


def lock_starts(slate: dict):
    return [datetime.fromisoformat(lk["start"]) for lk in slate["locks"]]


def lock_for_time(slate: dict, t: datetime) -> int:
    """Index of the first lock that starts after *t*. Raises if every lock has passed."""
    if t.tzinfo is None:
        t = t.astimezone()
    for k, start in enumerate(lock_starts(slate)):
        if start > t:
            return k
    raise ValueError(f"{t.isoformat()} is after the last lock of {slate['slate_id']}")


def lock_or_none(slate: dict, t: datetime) -> Optional[int]:
    """lock_for_time, or None once every lock has passed."""
    try:
        return lock_for_time(slate, t)
    except ValueError:
        return None


def team_game_lock(slate: dict) -> Dict[str, int]:
    game_lock = {g: lk["lock"] for lk in slate["locks"] for g in lk["games"]}
    return {team: game_lock[game] for team, game in slate["teams"].items()}


def find_slate_dir(cfg: Config, when: datetime) -> str:
    """Slate folder under cfg.data_root whose lock 0 is the latest one <= when + 12 h.

    If that slate hasn't locked yet (tonight's pre-lock run already made its
    folder), the most recent slate whose last lock has passed wins instead,
    so the next-morning finalize still finds last night's folder.
    """
    if not cfg.data_root or not os.path.isdir(cfg.data_root):
        raise FileNotFoundError("NBA_DATA_ROOT is not set or doesn't exist; pass --slate-dir")
    if when.tzinfo is None:
        when = when.astimezone()
    limit = when + timedelta(hours=12)
    candidates = []
    for name in os.listdir(cfg.data_root):
        path = os.path.join(cfg.data_root, name, SLATE_FILE)
        if not os.path.isfile(path):
            continue
        try:
            starts = lock_starts(read_json(path))
        except (ValueError, KeyError, IndexError, OSError):
            continue
        if starts and starts[0] <= limit:
            candidates.append((starts[0], starts[-1], os.path.dirname(path)))
    if not candidates:
        raise FileNotFoundError(f"No slate folder in {cfg.data_root} with lock 0 before {limit.isoformat()}")
    latest = max(candidates)
    if latest[0] > when:
        finished = [c for c in candidates if c[1] <= when]
        if finished:
            return max(finished)[2]
    return latest[2]


def _warn_on_drift(slate: dict, entries_file: str) -> None:
    try:
        current = _games_in_pool(parse_dk_entries(entries_file))
    except (ValueError, KeyError, OSError) as e:
        print(f"Warning: couldn't compare {os.path.basename(entries_file)} with slate.json: {e}")
        return
    recorded = {g: datetime.fromisoformat(lk["start"]) for lk in slate["locks"] for g in lk["games"]}
    drift = [
        f"{g} {t.isoformat()}" for g, t in current.items() if recorded.get(g) != t
    ]
    if drift:
        print(
            f"Warning: {os.path.basename(entries_file)} differs from slate.json "
            f"(games/start times not recorded: {drift}); slate.json is kept as written."
        )


def load_or_write_slate(cfg: Config, entries_file: str) -> Tuple[Optional[dict], Optional[str]]:
    """Return (slate, slate_dir), writing slate.json on the night's first run.

    Without cfg.data_root the slate is built in memory only (legacy layout)
    and slate_dir is None. A later run with a post-lock DKEntries reuses the
    existing slate.json; slate.json is never overwritten.
    """
    try:
        fresh = build_slate(entries_file, cfg.slate_type)
        error = None
    except ValueError as e:
        fresh, error = None, e

    if not cfg.data_root:
        if fresh is None:
            print(f"Warning: slate facts unavailable ({error}); run records will have no slate_id.")
        return fresh, None

    if fresh is not None:
        slate_dir = os.path.join(cfg.data_root, fresh["slate_id"])
    else:
        slate_dir = _existing_slate_dir(cfg, entries_file)
        if slate_dir is None:
            raise ValueError(f"first run of the night needs a pre-lock DKEntries ({error})")

    path = os.path.join(slate_dir, SLATE_FILE)
    check_slate_folder(cfg, entries_file, slate_dir, creating=not os.path.isfile(path))
    if os.path.isfile(path):
        slate = read_json(path)
        _warn_on_drift(slate, entries_file)
        return slate, slate_dir

    if fresh is None:
        raise ValueError(f"first run of the night needs a pre-lock DKEntries ({error})")
    os.makedirs(slate_dir, exist_ok=True)
    fresh["source_file"] = snapshot_input(entries_file, slate_dir, PRE_L0_ENTRIES)
    write_json_atomic(path, fresh)
    print(f"Slate folder: {slate_dir}")
    return fresh, slate_dir


def _folder_match(ids, slate_dir: str):
    """(share, matched, n) of *ids* in slate_dir's Pre-L0-DKEntries.csv, or None without one."""
    pre_l0 = os.path.join(slate_dir, PRE_L0_ENTRIES)
    if not os.path.isfile(pre_l0):
        return None
    share = id_match(ids, player_ids(pre_l0))
    return share, round(share * len(ids)), len(ids)


def check_slate_folder(cfg: Config, entries_file: str, slate_dir: str, creating: bool) -> None:
    """Decision-6 guard: the DKEntries must be *slate_dir*'s slate, not a sibling's.

    An existing folder needs MATCH_MIN of the DKEntries' player IDs in its
    Pre-L0-DKEntries.csv; a folder about to be created needs no other folder
    of the same slate date to match. Raises ValueError before anything is written.
    """
    ids = player_ids(entries_file)
    slate_id = os.path.basename(os.path.normpath(slate_dir))
    own = None if creating else _folder_match(ids, slate_dir)
    if own is not None and own[0] >= MATCH_MIN:
        return
    date_prefix = slate_id[:10] + "_classic_"
    siblings = sorted(
        n for n in os.listdir(cfg.data_root)
        if n.startswith(date_prefix) and n != slate_id and os.path.isdir(os.path.join(cfg.data_root, n))
    ) if os.path.isdir(cfg.data_root) else []
    for name in siblings:
        found = _folder_match(ids, os.path.join(cfg.data_root, name))
        if found and found[0] >= MATCH_MIN:
            other_type = name[len(date_prefix):]
            raise ValueError(
                f"these DKEntries are {name}'s ({found[1]} of {found[2]} players); "
                f"set the slate type to {other_type} or choose the {cfg.slate_type} DKEntries"
            )
    if own is not None:
        raise ValueError(
            f"these DKEntries match only {own[1]} of {own[2]} players in {slate_id}'s {PRE_L0_ENTRIES}; "
            f"check the slate type or choose the {cfg.slate_type} DKEntries"
        )


def finished_slate_dir(cfg: Config, entries_file: str, when: datetime) -> Optional[str]:
    """The finished cfg.slate_type folder whose Pre-L0-DKEntries holds these DKEntries' players, or None.

    Newest first. Lets a re-run on last night's slate through once the
    projections folder holds the next slate's exports (the past-slate rules
    never use those).
    """
    if not cfg.data_root or not os.path.isdir(cfg.data_root):
        return None
    try:
        ids = player_ids(entries_file)
    except (ValueError, OSError):
        return None
    suffix = f"_classic_{cfg.slate_type}"
    for name in sorted(os.listdir(cfg.data_root), reverse=True):
        slate_dir = os.path.join(cfg.data_root, name)
        path = os.path.join(slate_dir, SLATE_FILE)
        if not name.endswith(suffix) or not os.path.isfile(path):
            continue
        try:
            finished = lock_or_none(read_json(path), when) is None
        except (ValueError, KeyError, IndexError, OSError):
            continue
        found = _folder_match(ids, slate_dir) if finished else None
        if found and found[0] >= MATCH_MIN:
            return slate_dir
    return None


def _existing_slate_dir(cfg: Config, entries_file: str) -> Optional[str]:
    """Locate tonight's slate folder from a post-lock DKEntries file."""
    try:
        games = _games_in_pool(parse_dk_entries(entries_file))
    except (ValueError, KeyError, OSError):
        games = {}
    if games:
        date = min(games.values()).date().isoformat()
        candidate = os.path.join(cfg.data_root, f"{date}_classic_{cfg.slate_type}")
        if os.path.isfile(os.path.join(candidate, SLATE_FILE)):
            return candidate
    try:
        found = find_slate_dir(cfg, datetime.now().astimezone())
    except FileNotFoundError:
        return None
    if read_json(os.path.join(found, SLATE_FILE)).get("slate_type") != cfg.slate_type:
        return None
    return found
