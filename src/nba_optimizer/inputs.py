"""Pick a run's projections and DKEntries for its slate type (O-15).

The slate type chooses the projections folder; the newest export there (by
the timestamp in its name) is used. The DKEntries is the chosen file or, by
default, the newest recent download whose players match those projections.
Every check here runs before anything is written.
"""

import glob
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set

import pandas as pd

from . import records
from .config import Config, ROSTER_SLOTS, SLATE_TYPES
from .utils import parse_dk_entries

# Share of a file's DK player IDs that must be found in the reference set
# (projections, a slate folder's Pre-L0-DKEntries). DK IDs are per slate, so
# a match is ~100% and a mismatch ~0%. capture uses the same rule.
MATCH_MIN = 0.5
ENTRIES_MAX_AGE_HOURS = 24
PROJS_NAME_RE = re.compile(r"^NBA-Projs-(?:(?P<type>[A-Za-z]+)-)?(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")
PROJS_TS_FORMAT = "%Y-%m-%d_%H-%M-%S"


def _type_env_var(slate_type: str) -> str:
    return "NBA_PROJS_DIR" if slate_type == "main" else f"NBA_PROJS_DIR_{slate_type.upper()}"


def projs_dir_for(cfg: Config, slate_type: str, must_exist: bool = True) -> str:
    """main -> cfg.projs_dir; else cfg.projs_dir_overrides[type] or f"{cfg.projs_dir}-{type}".

    With *must_exist*, a missing folder raises FileNotFoundError naming the
    expected path and the env var that would point elsewhere.
    """
    slate_type = slate_type.lower()
    if slate_type == "main":
        directory = cfg.projs_dir
    else:
        directory = cfg.projs_dir_overrides.get(slate_type) or f"{os.path.normpath(cfg.projs_dir)}-{slate_type}"
    if must_exist and not os.path.isdir(directory):
        raise FileNotFoundError(
            f"no projections folder for {slate_type}: expected {directory} (or set {_type_env_var(slate_type)})"
        )
    return directory


def projs_name_time(name: str) -> Optional[datetime]:
    """The export time in an ``NBA-Projs-[<Type>-]YYYY-MM-DD_HH-MM-SS`` name (any ``L0-`` prefix ignored)."""
    start = name.find("NBA-Projs-")
    match = PROJS_NAME_RE.match(name[start:]) if start >= 0 else None
    return datetime.strptime(match.group("ts"), PROJS_TS_FORMAT) if match else None


def _name_type(name: str) -> Optional[str]:
    """The slate type a projections name is for, or None for an untyped name."""
    match = PROJS_NAME_RE.match(name)
    word = match.group("type") if match else None
    if word and word == word.capitalize() and word.lower() in SLATE_TYPES:
        return word.lower()
    return None


def latest_projections(directory: str, slate_type: str) -> str:
    """Newest ``NBA-Projs-*.csv`` in *directory* by its name's timestamp (decisions 2-3).

    A name without a timestamp ranks by its modified time; ties go to the
    later name. Files named for another slate type are skipped with a warning.
    Raises FileNotFoundError naming the folder when nothing qualifies.
    """
    candidates = []
    for path in glob.glob(os.path.join(directory, "NBA-Projs-*.csv")):
        name = os.path.basename(path)
        named_for = _name_type(name)
        if named_for and named_for != slate_type:
            print(f"Warning: skipping {name} in the {slate_type} projections folder (named for {named_for})")
            continue
        when = projs_name_time(name) or datetime.fromtimestamp(os.path.getmtime(path))
        candidates.append((when, name, path))
    if not candidates:
        raise FileNotFoundError(f"no NBA-Projs-*.csv for {slate_type} in {directory}")
    return max(candidates)[2]


def _normalize_ids(values) -> Set[str]:
    return set(pd.Series(values).dropna().astype(str).str.split(".").str[0])


def player_ids(path: str) -> Set[str]:
    """DK player IDs a file mentions: a DKEntries pool block, a projections ID column, or lineup slots."""
    try:
        return _normalize_ids(parse_dk_entries(path)["ID"])
    except ValueError:
        pass
    if "ID" in pd.read_csv(path, nrows=0).columns:
        return _normalize_ids(pd.read_csv(path, usecols=["ID"])["ID"])
    df = records.read_lineup_file(path)
    return {str(int(v)) for slot in ROSTER_SLOTS for v in df[slot].dropna()}


def id_match(ids: Set[str], reference: Set[str]) -> float:
    """Share of *ids* found in *reference* (0.0 when ids is empty)."""
    return len(ids & reference) / len(ids) if ids else 0.0


def _entries_ids(path: str) -> Set[str]:
    """The player-pool IDs of a DKEntries download; ValueError if it has no pool."""
    try:
        return _normalize_ids(parse_dk_entries(path)["ID"])
    except ValueError:
        raise ValueError(f"{os.path.basename(path)} isn't a DKEntries download (no player pool)") from None


def _entries_candidates(cfg: Config):
    paths = glob.glob(os.path.join(cfg.downloads_dir, "DKEntries*.csv"))
    if cfg.entries_path and os.path.isfile(cfg.entries_path):
        paths.append(cfg.entries_path)
    unique = {}
    for path in paths:
        unique.setdefault(os.path.normcase(os.path.abspath(path)), path)
    return list(unique.values())


def pick_entries(cfg: Config, projs_file: str, run_time: datetime) -> str:
    """Decision 5 auto mode: the newest recent DKEntries download matching *projs_file*.

    Candidates are ``DKEntries*.csv`` in cfg.downloads_dir plus cfg.entries_path
    (NBA_ENTRIES_PATH) when it exists. Only modified time counts: Windows keeps
    a file's creation time when it's overwritten in place. A newer download
    for another slate fails the match and is skipped.
    """
    projs_ids = player_ids(projs_file)
    oldest = run_time.timestamp() - ENTRIES_MAX_AGE_HOURS * 3600
    recent = [p for p in _entries_candidates(cfg) if os.path.getmtime(p) >= oldest]
    for path in sorted(recent, key=lambda p: (os.path.getmtime(p), os.path.basename(p)), reverse=True):
        try:
            ids = _entries_ids(path)
        except (ValueError, OSError, UnicodeDecodeError):
            continue
        if id_match(ids, projs_ids) >= MATCH_MIN:
            return path
    raise FileNotFoundError(
        f"no DKEntries downloaded in the last {ENTRIES_MAX_AGE_HOURS} h matches {os.path.basename(projs_file)}; "
        f"download the {cfg.slate_type} DKEntries or choose one"
    )


@dataclass
class RunInputs:
    slate_type: str
    projs_dir: str
    projs_file: str
    entries_file: str
    entries_how: str               # "chosen" | "auto"
    match: float                   # decision-4 share, for the console line
    n_players: int                 # DKEntries player-pool size

    def print_lines(self) -> None:
        """The three §6.1 lines at the start of a run."""
        folder = os.path.basename(os.path.normpath(self.projs_dir))
        how = "chosen" if self.entries_how == "chosen" else "auto: newest matching download"
        matched = round(self.match * self.n_players)
        print(f"Slate type: {self.slate_type}")
        print(f"Projections: {os.path.basename(self.projs_file)} (newest in {folder})")
        print(f"DKEntries: {os.path.basename(self.entries_file)} ({how}; {matched} of {self.n_players} players)")


def resolve_inputs(cfg: Config, slate_type: str, entries: Optional[str], run_time: datetime) -> RunInputs:
    """Decisions 1-5 in order; raises ValueError / FileNotFoundError before anything is written."""
    projs_dir = projs_dir_for(cfg, slate_type)
    projs_file = latest_projections(projs_dir, slate_type)
    if entries:
        if not os.path.isfile(entries):
            raise FileNotFoundError(f"DKEntries file not found: {entries}")
        entries_file, how = entries, "chosen"
    else:
        entries_file, how = pick_entries(cfg, projs_file, run_time), "auto"

    ids = _entries_ids(entries_file)
    match = id_match(ids, player_ids(projs_file))
    if match < MATCH_MIN:
        raise ValueError(
            f"{os.path.basename(projs_file)} matches {round(match * len(ids))} of {len(ids)} players in "
            f"{os.path.basename(entries_file)}; export tonight's {slate_type} projections, "
            "or check the slate type and DKEntries"
        )
    return RunInputs(slate_type, projs_dir, projs_file, entries_file, how, match, len(ids))
