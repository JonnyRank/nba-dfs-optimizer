"""Run records, entry sets and file helpers for nightly capture (O-0).

Everything here writes or reads small JSON/CSV artifacts inside a slate
folder. Nothing in this module solves or ranks lineups.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import pandas as pd

from .config import ROSTER_SLOTS
from .utils import extract_player_id, is_player_locked

SCHEMA_VERSION = 1

# Header line DK puts at the top of the player-pool block in DKEntries files.
POOL_HEADER_MARKER = "Position,Name + ID,Name,ID"
ENTRY_HEADER = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"] + list(ROSTER_SLOTS)
BASIC_PROJS_HEADER = ["ID", "Projection", "Own_Proj"]
STANDINGS_NAME_RE = re.compile(r"^contest-standings-(\d+)(?: \(\d+\))?\.csv$", re.IGNORECASE)
PROJS_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")

# Blend check tolerances: the workbook rounds nothing, so these only absorb float noise.
BLEND_FPPM_TOL = 1e-6
BLEND_PROJ_TOL = 1e-4

_SHA_CACHE: Dict[tuple, str] = {}


# --- FILE HELPERS ---


def sha256_file(path: str) -> str:
    st = os.stat(path)
    key = (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size)
    if key not in _SHA_CACHE:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _SHA_CACHE[key] = h.hexdigest()
    return _SHA_CACHE[key]


def file_mtime(path: str) -> datetime:
    """Modified time as an aware local datetime (whole seconds dropped only on output)."""
    return datetime.fromtimestamp(os.path.getmtime(path)).astimezone()


def find_identical(path: str, directory: str) -> Optional[str]:
    """Basename of a file in *directory* with the same sha256 as *path*, if any."""
    if not os.path.isdir(directory):
        return None
    size = os.path.getsize(path)
    target = None
    for name in sorted(os.listdir(directory)):
        candidate = os.path.join(directory, name)
        if not os.path.isfile(candidate) or os.path.getsize(candidate) != size:
            continue
        if target is None:
            target = sha256_file(path)
        if sha256_file(candidate) == target:
            return name
    return None


def snapshot_name(path: str, directory: str, canonical_name: str) -> str:
    """The basename snapshot_input would use, without copying anything."""
    existing = find_identical(path, directory)
    if existing:
        return existing
    if not os.path.exists(os.path.join(directory, canonical_name)):
        return canonical_name
    stem, ext = os.path.splitext(canonical_name)
    suffix = file_mtime(path).strftime("%H%M%S")
    name = f"{stem}-{suffix}{ext}"
    n = 2
    while os.path.exists(os.path.join(directory, name)):
        name = f"{stem}-{suffix}-{n}{ext}"
        n += 1
    return name


def snapshot_input(path: str, slate_dir: str, canonical_name: str) -> str:
    """Copy *path* into *slate_dir* as *canonical_name* and return the basename used.

    A file with identical contents already in the folder is reused. An
    existing file with the same name but different contents is never
    overwritten; ``-<HHMMSS>`` (from the source's modified time) is appended.
    The copy keeps the source's modified time.
    """
    os.makedirs(slate_dir, exist_ok=True)
    name = snapshot_name(path, slate_dir, canonical_name)
    dest = os.path.join(slate_dir, name)
    if not os.path.exists(dest):
        shutil.copy2(path, dest)
    return name


def write_json_atomic(path: str, payload: dict) -> None:
    """Write JSON through a temp file and os.replace; retry once (Google Drive sync locks)."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    try:
        os.replace(tmp, path)
    except PermissionError:
        import time

        time.sleep(1.0)
        os.replace(tmp, path)


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def git_code_version(repo_root: str) -> Optional[str]:
    """Short commit hash of *repo_root*, with ``-dirty`` for uncommitted changes."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo_root, capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        print("Warning: git unavailable; code_version not recorded.")
        return None
    return f"{sha}-dirty" if dirty else sha


def iso_seconds(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def compact_ts(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def projections_copy_name(path: str, lock: int) -> str:
    """``L<k>-NBA-Projs-<YYYY-MM-DD_HH-MM-SS>.csv``, keeping the source's own timestamp if it has one."""
    match = PROJS_TS_RE.search(os.path.basename(path))
    ts = match.group(1) if match else file_mtime(path).strftime("%Y-%m-%d_%H-%M-%S")
    return f"L{lock}-NBA-Projs-{ts}.csv"


# --- LINEUPS ---


def lineup_key(dk_ids: Iterable) -> str:
    return "-".join(str(i) for i in sorted(int(i) for i in dk_ids))


def _cell_to_id(cell: str) -> Optional[int]:
    cell = (cell or "").strip()
    if not cell:
        return None
    if cell.isdigit():
        return int(cell)
    pid = extract_player_id(cell)
    return int(pid) if pid else None


def _read_csv_rows(path: str) -> List[List[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def read_lineup_file(path: str) -> pd.DataFrame:
    """Parse the entry rows of a DKEntries-format or Stok-export file.

    Returns one row per entry: ``entry_id`` (str), ``contest_id`` (int),
    ``contest_name``, ``entry_fee``, the 8 slot DK IDs (nullable Int64) and
    8 ``<slot>_locked`` flags.
    """
    rows = _read_csv_rows(path)
    if not rows or [c.strip() for c in rows[0][: len(ENTRY_HEADER)]] != ENTRY_HEADER:
        raise ValueError(f"{os.path.basename(path)}: not a DK entry file (unexpected header)")
    records = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        row = row + [""] * (len(ENTRY_HEADER) - len(row))
        rec = {
            "entry_id": row[0].strip(),
            "contest_name": row[1].strip(),
            "contest_id": int(row[2].strip()),
            "entry_fee": row[3].strip(),
        }
        for k, slot in enumerate(ROSTER_SLOTS):
            cell = row[4 + k]
            rec[slot] = _cell_to_id(cell)
            rec[f"{slot}_locked"] = is_player_locked(cell)
        records.append(rec)
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=["entry_id", "contest_name", "contest_id", "entry_fee"]
                          + list(ROSTER_SLOTS) + [f"{s}_locked" for s in ROSTER_SLOTS])
    for slot in ROSTER_SLOTS:
        df[slot] = df[slot].astype("Int64")
    return df


def lineups_from_df(df: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    """{entry_id: {slot: dk_id}} for entries whose 8 slots are all filled."""
    out = {}
    for _, row in df.iterrows():
        if all(pd.notna(row[s]) for s in ROSTER_SLOTS):
            out[row["entry_id"]] = {s: int(row[s]) for s in ROSTER_SLOTS}
    return out


def classify_file(path: str) -> Optional[str]:
    """Identify a CSV by its contents.

    Returns one of ``pretemplate``, ``upload_candidate``, ``midnight``,
    ``final``, ``stok_export``, ``projs_expanded``, ``projs_basic``,
    ``standings`` or ``None``.
    """
    name = os.path.basename(path)
    if STANDINGS_NAME_RE.match(name):
        return "standings"
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    first = next(csv.reader([text.split("\n", 1)[0].rstrip("\r")]), [])
    header = [c.strip() for c in first]

    if header == BASIC_PROJS_HEADER:
        return "projs_basic"
    if "Stok Mins" in header and "ID" in header:
        return "projs_expanded"
    if header[: len(ENTRY_HEADER)] != ENTRY_HEADER:
        return None

    try:
        df = read_lineup_file(path)
    except (ValueError, IndexError):
        return None
    # DKEntries downloads carry the Instructions/player-pool block; the
    # exporter's upload-ready file keeps only its "Instructions" column.
    if "Instructions" not in header and POOL_HEADER_MARKER not in text:
        return "stok_export" if len(df) and len([c for c in header if c]) == len(ENTRY_HEADER) else None

    slot_cols = df[list(ROSTER_SLOTS)]
    if df.empty or slot_cols.isna().all().all():
        return "pretemplate"
    locked = df[[f"{s}_locked" for s in ROSTER_SLOTS]].to_numpy()
    if not locked.any():
        return "upload_candidate"
    if locked.all():
        return "final"
    return "midnight"


# --- PROJECTIONS ---


def derive_projection_fields(df_projs: pd.DataFrame) -> pd.DataFrame:
    """Add ``min_source`` (my|stok) and ``mins_used`` to an expanded projections frame."""
    df = df_projs.copy()
    my_raw = df["My Mins"] if "My Mins" in df.columns else pd.Series(0.0, index=df.index)
    my_mins = pd.to_numeric(my_raw, errors="coerce").fillna(0.0)
    stok_mins = pd.to_numeric(df["Stok Mins"], errors="coerce").fillna(0.0)
    use_my = my_mins != 0
    df["min_source"] = use_my.map({True: "my", False: "stok"})
    df["mins_used"] = my_mins.where(use_my, stok_mins)
    return df


def check_blend(df_projs: pd.DataFrame, warn: bool = True) -> Optional[dict]:
    """Verify the workbook's Blend FPPM and Projection columns.

    ``Blend FPPM`` must be the mean of the non-zero values among Stok/LS/My
    FPPM, and ``Projection`` must equal ``mins_used * Blend FPPM``. Returns
    ``None`` for the basic (3-column) layout. A mismatch only warns.
    """
    if "Stok Mins" not in df_projs.columns:
        return None
    df = derive_projection_fields(df_projs)
    fppm_cols = [c for c in ("Stok FPPM", "LS FPPM", "My FPPM") if c in df.columns]
    fppm = df[fppm_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    nonzero = fppm.where(fppm != 0)
    expected_blend = nonzero.mean(axis=1).fillna(0.0)
    blend = pd.to_numeric(df["Blend FPPM"], errors="coerce").fillna(0.0)
    proj = pd.to_numeric(df["Projection"], errors="coerce").fillna(0.0)
    expected_proj = df["mins_used"] * blend

    bad = ((blend - expected_blend).abs() > BLEND_FPPM_TOL) | ((proj - expected_proj).abs() > BLEND_PROJ_TOL)
    name_col = next((c for c in ("Player", "Name", "Name + ID", "ID") if c in df.columns), "ID")
    examples = df.loc[bad, name_col].astype(str).head(5).tolist()
    result = {"rows": int(len(df)), "mismatches": int(bad.sum()), "examples": examples}
    if warn and result["mismatches"]:
        print(
            f"Warning: blend check found {result['mismatches']} of {result['rows']} projection rows "
            f"that don't match Blend FPPM / mins x FPPM (first: {examples})"
        )
    return result


def projections_layout(df_projs: pd.DataFrame) -> str:
    return "expanded" if "Stok Mins" in df_projs.columns else "basic"


# --- ENTRY SETS ---


def make_entry_set(
    slate_id: Optional[str],
    lock: int,
    source: str,
    created_at: datetime,
    lineups_file: str,
    lineups_sha256: str,
    df_lineups: pd.DataFrame,
    projections_file: Optional[str] = None,
    run_id: Optional[str] = None,
    status: str = "recorded",
    rank_map: Optional[Dict[str, int]] = None,
    entry_order: Optional[List[str]] = None,
) -> dict:
    """Build an entry-set payload from a parsed lineup file."""
    rank_map = rank_map or {}
    ts = compact_ts(created_at)
    df = df_lineups
    if entry_order:
        order = {eid: i for i, eid in enumerate(entry_order)}
        df = df.assign(_order=df["entry_id"].map(order).fillna(len(order))).sort_values(
            ["_order", "entry_id"], kind="stable"
        )
    entries = []
    for _, row in df.iterrows():
        if not all(pd.notna(row[s]) for s in ROSTER_SLOTS):
            continue
        lineup = {s: int(row[s]) for s in ROSTER_SLOTS}
        key = lineup_key(lineup.values())
        entries.append({
            "entry_id": str(row["entry_id"]),
            "contest_id": int(row["contest_id"]),
            "lineup_key": key,
            "lineup": lineup,
            "pre_lock_rank": rank_map.get(key),
        })
    return {
        "schema": SCHEMA_VERSION,
        "entry_set_id": f"{slate_id}_L{lock}_{ts}",
        "slate_id": slate_id,
        "lock": lock,
        "source": source,
        "created_at": iso_seconds(created_at),
        "lineups_file": lineups_file,
        "lineups_sha256": lineups_sha256,
        "projections_file": projections_file,
        "run_id": run_id,
        "status": status,
        "entries": entries,
    }


def entry_set_filename(payload: dict) -> str:
    ts = payload["entry_set_id"].rsplit("_", 1)[-1]
    return f"L{payload['lock']}-entry-set-{ts}.json"


def write_entry_set(directory: str, payload: dict) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, entry_set_filename(payload))
    write_json_atomic(path, payload)
    return path


def rank_map_from_ranked(ranked_file: str) -> Dict[str, int]:
    """{lineup_key: Final_Rank} from a ranked-lineups CSV (best rank kept on repeats)."""
    df = pd.read_csv(ranked_file)
    out: Dict[str, int] = {}
    for _, row in df.iterrows():
        ids = [_cell_to_id(str(row[s])) for s in ROSTER_SLOTS]
        if any(i is None for i in ids):
            continue
        key = lineup_key(ids)
        rank = int(row["Final_Rank"])
        if key not in out or rank < out[key]:
            out[key] = rank
    return out


def run_record_path(ranked_file: str) -> str:
    return os.path.splitext(ranked_file)[0] + ".json"
