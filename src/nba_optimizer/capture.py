"""Nightly capture (O-0): ``nba-dfs-capture finalize`` and ``nba-dfs-capture record``.

``finalize`` searches the night's downloads and projections folder, identifies
each CSV by its contents, assigns it to a lock by its modified time, checks
every lock's entry set against the final DKEntries download, and writes the
results into the slate folder. Originals are only ever copied, never moved
or deleted. Running it again rebuilds the same records.
"""

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from . import records
from .config import Config, ROSTER_SLOTS, STANDARD_EXPORT_PREFIX
from .slate import (
    PRE_L0_ENTRIES,
    SLATE_FILE,
    build_slate,
    find_slate_dir,
    lock_for_time,
    lock_starts,
    team_game_lock,
)
from .utils import parse_dk_entries

LINEUP_ROLES = ("pretemplate", "upload_candidate", "midnight", "final", "stok_export")
PROJ_ROLES = ("projs_expanded", "projs_basic")
CANDIDATE_ROLES = ("upload_candidate", "stok_export")
PINS_FILE = "pins.json"
FINALIZE_FILE = "finalize.json"
SLATE_ENTRIES_FILE = "slate-entries.csv"
FINAL_ENTRIES = "Final-DKEntries.csv"

# Projections whose IDs are mostly outside tonight's pool belong to another slate.
PROJS_MEMBERSHIP_MIN = 0.5

BROWSER_SUFFIX_RE = re.compile(r" \(\d+\)(?=\.[^.]+$)")
CAPTURE_PREFIX_RE = re.compile(r"^(?:(?:Pre|Post)-)?L\d+-|^Final-", re.IGNORECASE)
RUN_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{6})")

# §3.18: the settings Jonny confirmed for runs that predate run records.
RECONSTRUCTED_ENGINE_PARAMS = {"num_lineups": 2500, "randomness": 0.25, "min_unique": 1, "base_seed": None}
RECONSTRUCTED_WEIGHTS = {"proj": 0.8, "own": 0.0, "geo": 0.2}

SLATE_ENTRIES_COLUMNS = [
    "slate_id", "lock", "entry_set_id", "source", "entry_id", "contest_id", "slot", "dk_id",
    "name", "salary", "game", "game_lock", "lineup_key", "lineup_changed", "pre_lock_rank",
]


@dataclass
class FoundFile:
    path: str
    role: str
    mtime: datetime
    sha256: str
    lock: Optional[int] = None
    used: bool = False
    reason: str = ""
    copied_as: Optional[str] = None
    df: Optional[pd.DataFrame] = None

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def to_json(self) -> dict:
        return {
            "file": self.path,
            "role": self.role,
            "modified": records.iso_seconds(self.mtime),
            "sha256": self.sha256,
            "lock": self.lock,
            "used": self.used,
            "reason": self.reason,
            "copied_as": self.copied_as,
        }


class SlateContext:
    """Slate facts plus the player pool from the night's first DKEntries."""

    def __init__(self, slate: dict, slate_dir: str, pool_file: str):
        self.slate = slate
        self.slate_dir = slate_dir
        self.locks = lock_starts(slate)
        self.entry_ids = list(slate["entry_ids"])
        self.contest_ids = {c["contest_id"] for c in slate["contests"]}
        team_lock = team_game_lock(slate)
        df_pool = parse_dk_entries(pool_file)
        self.player_lock: Dict[int, int] = {}
        self.player_info: Dict[int, tuple] = {}
        for _, row in df_pool.iterrows():
            pid = int(row["ID"])
            team = str(row["TeamAbbrev"]).strip()
            self.player_lock[pid] = team_lock[team]
            self.player_info[pid] = (row["Name"], int(row["Salary"]), slate["teams"][team])

    @property
    def window_start(self) -> datetime:
        return self.locks[0] - timedelta(hours=24)

    def lock_of(self, t: datetime) -> Optional[int]:
        try:
            return lock_for_time(self.slate, t)
        except ValueError:
            return None

    def locks_passed(self, t: datetime) -> int:
        return sum(start <= t for start in self.locks)


# --- LOADING ---


def _slate_type_from_dir(slate_dir: str, default: str) -> str:
    match = re.search(r"_classic_([a-z]+)$", os.path.basename(os.path.normpath(slate_dir)))
    return match.group(1) if match else default


def load_context(
    slate_dir: str, entries: Optional[str] = None, dry_run: bool = False, slate_type: str = "main"
) -> SlateContext:
    """Load slate.json, or (backfill) build it from *entries* and write it once."""
    path = os.path.join(slate_dir, SLATE_FILE)
    if os.path.isfile(path):
        slate = records.read_json(path)
        return SlateContext(slate, slate_dir, os.path.join(slate_dir, slate["source_file"]))
    if not entries:
        raise FileNotFoundError(f"No {SLATE_FILE} in {slate_dir}; pass --entries with the pre-lock DKEntries")
    slate = build_slate(entries, _slate_type_from_dir(slate_dir, slate_type))
    if dry_run:
        return SlateContext(slate, slate_dir, entries)
    os.makedirs(slate_dir, exist_ok=True)
    slate["source_file"] = records.snapshot_input(entries, slate_dir, PRE_L0_ENTRIES)
    records.write_json_atomic(path, slate)
    print(f"Wrote {SLATE_FILE} for {slate['slate_id']}")
    return SlateContext(slate, slate_dir, os.path.join(slate_dir, slate["source_file"]))


def load_entry_sets(slate_dir: str) -> List[dict]:
    if not os.path.isdir(slate_dir):
        return []
    out = []
    for name in sorted(os.listdir(slate_dir)):
        if re.match(r"^L\d+-entry-set-.*\.json$", name):
            out.append(records.read_json(os.path.join(slate_dir, name)))
    return out


def load_pins(slate_dir: str) -> dict:
    path = os.path.join(slate_dir, PINS_FILE)
    pins = records.read_json(path) if os.path.isfile(path) else {}
    pins.setdefault("entry_sets", {})
    pins.setdefault("projections", {})
    return pins


def _load_run_records(slate_dir: str) -> List[dict]:
    if not os.path.isdir(slate_dir):
        return []
    out = []
    for name in sorted(os.listdir(slate_dir)):
        if name.startswith("ranked-lineups-") and name.endswith(".json"):
            out.append(records.read_json(os.path.join(slate_dir, name)))
    return out


# --- SEARCH ---


def _ids_in_lineup_cells(path: str) -> set:
    df = pd.read_csv(path, nrows=5)
    ids = set()
    for s in ROSTER_SLOTS:
        if s in df.columns:
            ids.update(int(i) for i in df[s].astype(str).str.extract(r"\((\d+)\)")[0].dropna())
    return ids


def _belongs(ctx: SlateContext, f: FoundFile) -> bool:
    if f.role in LINEUP_ROLES:
        return bool(set(f.df["entry_id"]) & set(ctx.entry_ids))
    if f.role in PROJ_ROLES:
        ids = pd.read_csv(f.path, usecols=["ID"])["ID"].dropna().astype(str).str.split(".").str[0]
        if ids.empty:
            return False
        return ids.map(lambda i: i.isdigit() and int(i) in ctx.player_lock).mean() >= PROJS_MEMBERSHIP_MIN
    if f.role == "standings":
        return int(records.STANDINGS_NAME_RE.match(f.name).group(1)) in ctx.contest_ids
    if f.role in ("pool", "ranked"):
        ids = _ids_in_lineup_cells(f.path)
        return bool(ids) and ids <= set(ctx.player_lock)
    return False


def _classify(path: str, backfill: bool) -> Optional[str]:
    role = records.classify_file(path)
    if role is None and backfill:
        name = os.path.basename(path)
        if name.startswith("lineup-pool-"):
            return "pool"
        if name.startswith("ranked-lineups-"):
            return "ranked"
    return role


def scan(ctx: SlateContext, search_dirs: List[str], now: datetime, backfill: bool = False) -> List[FoundFile]:
    """Classify every top-level CSV modified in [lock 0 - 24 h, now] that belongs to this slate.

    Files with identical contents in the same lock window collapse to one
    (the same export re-saved after a lock still counts in the later
    window); copies already in the slate folder are preferred only when no
    original remains elsewhere.
    """
    slate_norm = os.path.normcase(os.path.abspath(ctx.slate_dir))
    seen_dirs, seen_paths = set(), set()
    found: List[FoundFile] = []
    for d in list(search_dirs) + [ctx.slate_dir]:
        if not d or not os.path.isdir(d):
            continue
        d_norm = os.path.normcase(os.path.abspath(d))
        if d_norm in seen_dirs:
            continue
        seen_dirs.add(d_norm)
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            p_norm = os.path.normcase(os.path.abspath(path))
            if not name.lower().endswith(".csv") or not os.path.isfile(path) or p_norm in seen_paths:
                continue
            seen_paths.add(p_norm)
            mtime = records.file_mtime(path)
            if mtime < ctx.window_start or mtime > now:
                continue
            role = _classify(path, backfill)
            if role is None:
                continue
            f = FoundFile(path=path, role=role, mtime=mtime, sha256=records.sha256_file(path))
            if role in LINEUP_ROLES:
                f.df = records.read_lineup_file(path)
            f.lock = ctx.lock_of(mtime)
            found.append(f)

    in_slate = lambda f: os.path.normcase(os.path.dirname(os.path.abspath(f.path))) == slate_norm
    by_content: Dict[tuple, List[FoundFile]] = {}
    for f in found:
        by_content.setdefault((f.sha256, f.lock), []).append(f)
    out = []
    for group in by_content.values():
        group.sort(key=lambda f: (in_slate(f), -f.mtime.timestamp(), f.path))
        rep = group[0]
        out.append(rep)
        for dup in group[1:]:
            if not in_slate(dup):
                dup.reason = f"duplicate of {rep.name}"
                out.append(dup)
    out.sort(key=lambda f: (f.mtime, f.path))

    for f in out:
        if f.reason:
            continue
        if not _belongs(ctx, f):
            f.reason = "other slate (IDs don't match slate.json)"
        elif f.lock is None and f.role not in ("final", "standings"):
            f.reason = "modified after the last lock"
    return out


def _active(found: List[FoundFile], roles) -> List[FoundFile]:
    return [f for f in found if f.role in roles and not f.reason]


# --- CHECKS ---


def _lineups(es: dict) -> Dict[str, Dict[str, int]]:
    return {e["entry_id"]: {s: int(e["lineup"][s]) for s in ROSTER_SLOTS} for e in es["entries"]}


def _players_in_lock(lineup: Dict[str, int], k: int, player_lock: Dict[int, int]) -> frozenset:
    return frozenset((s, pid) for s, pid in lineup.items() if player_lock.get(pid) == k)


def check_filled(label: str, df: pd.DataFrame) -> None:
    for _, row in df.iterrows():
        for s in ROSTER_SLOTS:
            if pd.isna(row[s]):
                raise ValueError(f"{label}: entry {row['entry_id']} slot {s} is empty or has no DK ID")


def check_record(
    label: str,
    lineups: Dict[str, Dict[str, int]],
    ctx: SlateContext,
    prev: Optional[Dict[str, Dict[str, int]]],
    k: int,
) -> None:
    """Fail loudly unless *lineups* could be what DK accepted for lock k."""
    expected, actual = set(ctx.entry_ids), set(lineups)
    if expected != actual:
        raise ValueError(
            f"{label}: entry IDs don't match slate.json "
            f"(missing {sorted(expected - actual)[:5]}, extra {sorted(actual - expected)[:5]})"
        )
    for eid, lineup in lineups.items():
        for s, pid in lineup.items():
            if pid not in ctx.player_lock:
                raise ValueError(f"{label}: entry {eid} slot {s}: DK ID {pid} isn't in the slate's player pool")
    if prev is None:
        return
    for eid, lineup in lineups.items():
        before = prev.get(eid)
        if before is None:
            continue
        for s in ROSTER_SLOTS:
            was, now = before[s], lineup[s]
            if was != now and (ctx.player_lock[was] < k or ctx.player_lock[now] < k):
                raise ValueError(
                    f"{label}: entry {eid} slot {s}: locked player changed ({was} -> {now}); "
                    "this can't be what DK accepted"
                )


def _verified(lineups, final, k: int, ctx: SlateContext) -> int:
    return sum(
        1 for eid in ctx.entry_ids
        if eid in lineups and eid in final
        and _players_in_lock(lineups[eid], k, ctx.player_lock) == _players_in_lock(final[eid], k, ctx.player_lock)
    )


def _differences(lineups, final, ctx: SlateContext, k: Optional[int] = None) -> List[dict]:
    out = []
    for eid in ctx.entry_ids:
        a, b = lineups.get(eid), final.get(eid)
        if a is None or b is None:
            out.append({"entry_id": eid, "slot": None, "recorded": a is not None, "final": b is not None})
            continue
        for s in ROSTER_SLOTS:
            if k is not None and ctx.player_lock.get(a[s]) != k and ctx.player_lock.get(b[s]) != k:
                continue
            if a[s] != b[s]:
                out.append({"entry_id": eid, "slot": s, "recorded": a[s], "final": b[s]})
    return out


def _set_in_force_before(entry_sets: List[dict], k: int) -> Optional[Dict[str, Dict[str, int]]]:
    """Lineups in force at lock k-1 from recorded entry sets (in_force first, else latest)."""
    current = None
    for j in range(k):
        cands = sorted((es for es in entry_sets if es["lock"] == j), key=lambda es: es["created_at"])
        chosen = [es for es in cands if es.get("status") == "in_force"] or cands[-1:]
        if chosen:
            current = _lineups(chosen[-1])
    return current


# --- NAMING / COPYING ---


def _clean_name(name: str) -> str:
    name = BROWSER_SUFFIX_RE.sub("", name)
    return CAPTURE_PREFIX_RE.sub("", name)


def _lineup_copy_name(f: FoundFile, k: int) -> str:
    clean = _clean_name(f.name)
    if clean.startswith(STANDARD_EXPORT_PREFIX):
        return clean
    return f"L{k}-{clean}"


def _place(path: str, slate_dir: str, canonical: str, dry_run: bool) -> str:
    if dry_run:
        return records.snapshot_name(path, slate_dir, canonical)
    return records.snapshot_input(path, slate_dir, canonical)


def _source_for(f: FoundFile) -> str:
    if f.role == "stok_export":
        return "stokastic"
    if _clean_name(f.name).startswith(STANDARD_EXPORT_PREFIX):
        return "optimizer"
    return "manual"


def _run_record_for_export(name: str, run_records: List[dict]) -> Optional[dict]:
    match = RUN_TS_RE.search(name)
    if not match:
        return None
    suffix = f"{match.group(1)}_{match.group(2)}.csv"
    for rec in run_records:
        if rec.get("ranked_file", "").endswith(suffix):
            return rec
    return None


# --- BACKFILL ---


def _backfill_runs(ctx: SlateContext, found: List[FoundFile], dry_run: bool) -> None:
    """Copy pre-lock pool/ranked files found by name and write reconstructed run records."""
    from .ranker import write_run_record

    pools = {RUN_TS_RE.search(f.name).group(0): f for f in _active(found, ("pool",)) if RUN_TS_RE.search(f.name)}
    projs = sorted(_active(found, PROJ_ROLES), key=lambda f: f.mtime)
    for f in _active(found, ("ranked",)):
        if f.lock != 0:
            f.reason = "ranked file after lock 0"
            continue
        f.copied_as = _place(f.path, ctx.slate_dir, f.name, dry_run)
        f.used = True
        f.reason = "backfill: pre-lock ranked file"
        match = RUN_TS_RE.search(f.name)
        pool = pools.get(match.group(0)) if match else None
        if pool:
            pool.copied_as = _place(pool.path, ctx.slate_dir, pool.name, dry_run)
            pool.used, pool.reason = True, "backfill: pre-lock lineup pool"
        record_path = records.run_record_path(os.path.join(ctx.slate_dir, f.copied_as))
        if dry_run or os.path.isfile(record_path):
            continue
        read = [p for p in projs if p.mtime <= f.mtime]
        if not read:
            print(f"Warning: no projections before {f.name}; reconstructed run record skipped.")
            continue
        projs_name = _place(read[-1].path, ctx.slate_dir, records.projections_copy_name(read[-1].path, 0), dry_run)
        run_time = (
            datetime.strptime(f"{match.group(1)}{match.group(2)}", "%Y-%m-%d%H%M%S").astimezone()
            if match else f.mtime
        )
        pool_path = os.path.join(ctx.slate_dir, pool.copied_as) if pool else None
        cfg = Config(entries_path=os.path.join(ctx.slate_dir, ctx.slate["source_file"]))
        write_run_record(
            cfg,
            os.path.join(ctx.slate_dir, f.copied_as),
            pool_path,
            os.path.join(ctx.slate_dir, projs_name),
            ctx.slate,
            run_time,
            lineups_written=len(pd.read_csv(pool_path)) if pool_path else None,
            weights=RECONSTRUCTED_WEIGHTS,
            engine_params=RECONSTRUCTED_ENGINE_PARAMS,
            params_source="reconstructed",
            code_version=None,
        )


# --- FINALIZE ---


def _pick_latest(files: List[FoundFile], before: Optional[datetime] = None) -> Optional[FoundFile]:
    files = [f for f in files if before is None or f.mtime <= before]
    full = [f for f in files if f.role == "projs_expanded"]
    pool = full or [f for f in files if f.role == "projs_basic"]
    return max(pool, key=lambda f: f.mtime) if pool else None


def finalize(
    slate_dir: str,
    search_dirs: List[str],
    dry_run: bool = False,
    entries: Optional[str] = None,
    assume_default_params: bool = False,
    now: Optional[datetime] = None,
    slate_type: str = "main",
) -> dict:
    """Assign the night's files to locks, verify the chain and write the records.

    Returns the finalize payload (``changed_vs_previous`` and
    ``unique_lineups_by_lock`` keyed by int lock).
    """
    now = now or datetime.now().astimezone()
    print(f"Slate folder: {slate_dir}")
    ctx = load_context(slate_dir, entries, dry_run, slate_type)
    warnings: List[str] = []
    found = scan(ctx, search_dirs, now, backfill=bool(entries) and assume_default_params)
    pins = load_pins(slate_dir)
    n_locks = len(ctx.locks)

    if entries and assume_default_params:
        _backfill_runs(ctx, found, dry_run)
    run_records = _load_run_records(slate_dir)

    for f in _active(found, ("pretemplate",)):
        if f.sha256 == ctx.slate["source_sha256"]:
            f.used, f.reason = True, "slate source (Pre-L0)"
        else:
            f.reason = "pre-lock template; slate.json already recorded"

    # Projections closest to each lock (§3.6).
    projs = _active(found, PROJ_ROLES)
    chain_projs: List[Optional[str]] = []
    for k in range(n_locks):
        pinned = pins["projections"].get(str(k))
        pick = None if pinned else _pick_latest([f for f in projs if f.lock == k])
        if pinned:
            name = pinned
        elif pick:
            pick.copied_as = _place(pick.path, slate_dir, records.projections_copy_name(pick.path, k), dry_run)
            pick.used, pick.reason = True, f"latest projections before lock {k}"
            name = pick.copied_as
        else:
            name = chain_projs[-1] if chain_projs else None
            warnings.append(f"no projections export before lock {k}; reusing {name}")
        chain_projs.append(name)

    # Entry-set candidates: recorded sets in the folder plus new files from the search.
    entry_sets = load_entry_sets(slate_dir)
    known = {es["lineups_sha256"]: es for es in entry_sets}
    for f in _active(found, CANDIDATE_ROLES):
        if f.sha256 in known:
            es = known[f.sha256]
            f.copied_as = es["lineups_file"]
            f.used, f.reason = True, f"L{es['lock']} entry-set candidate {es['entry_set_id']}"
            continue
        k = f.lock
        check_filled(f.name, f.df)
        source = _source_for(f)
        run_rec = _run_record_for_export(f.name, run_records) if source == "optimizer" else None
        if run_rec:
            projections_file = run_rec["inputs"]["projections"]["file"]
        else:
            built = _pick_latest([p for p in projs if p.lock == k], before=f.mtime)
            if built is None:
                # No export in this window before the file: the lock's own
                # projections if pinned/picked, else the previous lock's.
                projections_file = chain_projs[k] or (chain_projs[k - 1] if k > 0 else None)
            else:
                if not built.used:
                    built.copied_as = _place(
                        built.path, slate_dir, records.projections_copy_name(built.path, k), dry_run
                    )
                    built.used, built.reason = True, f"projections the L{k} entry set was built from"
                projections_file = built.copied_as
        f.copied_as = _place(f.path, slate_dir, _lineup_copy_name(f, k), dry_run)
        es = records.make_entry_set(
            slate_id=ctx.slate["slate_id"],
            lock=k,
            source=source,
            created_at=f.mtime,
            lineups_file=f.copied_as,
            lineups_sha256=f.sha256,
            df_lineups=f.df,
            projections_file=projections_file,
            run_id=run_rec["run_id"] if run_rec else None,
            rank_map=_rank_map(slate_dir, run_rec) if run_rec else None,
            entry_order=ctx.entry_ids,
        )
        f.used, f.reason = True, f"L{k} entry-set candidate {es['entry_set_id']}"
        entry_sets.append(es)
        known[f.sha256] = es

    for f in projs:
        if not f.used and not f.reason:
            f.reason = f"superseded by a later export before lock {f.lock}"

    # Final state.
    finals = _active(found, ("final",))
    final_file = max(finals, key=lambda f: f.mtime) if finals else None
    for f in finals:
        if f is not final_file:
            f.reason = f"earlier final download than {final_file.name}"
    final = records.lineups_from_df(final_file.df) if final_file else None
    if final_file:
        check_record(final_file.name, final, ctx, None, n_locks)
        final_file.copied_as = _place(final_file.path, slate_dir, FINAL_ENTRIES, dry_run)
        final_file.used, final_file.reason = True, "final DK state"
    else:
        warnings.append("not verified; download DKEntries after the last lock and re-run")

    # Chain (§6.3.5-7).
    chain, lineups_by_lock, provider_by_lock = [], [], []
    prev, prev_provider = None, None
    mismatches = []
    for k in range(n_locks):
        cands = sorted((es for es in entry_sets if es["lock"] == k), key=lambda es: es["created_at"])
        for es in cands:
            check_record(es["lineups_file"], _lineups(es), ctx, prev, k)
        pin_id = pins["entry_sets"].get(str(k))
        pinned = [es for es in cands if es["entry_set_id"] == pin_id]
        chosen, kind = None, None
        if final is not None:
            fits = lambda es: _verified(_lineups(es), final, k, ctx) == len(ctx.entry_ids)
            if pinned:
                chosen = pinned[0] if fits(pinned[0]) else None
            else:
                matching = [es for es in cands if fits(es)]
                if len(matching) > 1:
                    warnings.append(
                        f"L{k}: {len(matching)} candidates consistent with DK; using the latest "
                        f"({matching[-1]['entry_set_id']}). Use 'record --lock {k}' to pin one."
                    )
                chosen = matching[-1] if matching else None
            if chosen:
                kind = "in_force"
            elif prev is not None and not pinned and _verified(prev, final, k, ctx) == len(ctx.entry_ids):
                kind = "carried"
            else:
                kind = "mismatch"
        else:
            chosen = pinned[0] if pinned else (cands[-1] if cands else None)
            kind = "recorded" if chosen else ("carried" if prev is not None else "missing")

        if chosen is not None:
            current, provider = _lineups(chosen), chosen
        elif kind == "mismatch" and cands:
            current, provider = _lineups(cands[-1]), cands[-1]
        else:
            current, provider = prev, prev_provider

        for es in cands:
            if final is None:
                es["status"] = "recorded"
            elif kind == "mismatch":
                es["status"] = "mismatch"
            else:
                es["status"] = "in_force" if es is chosen else "superseded"

        verified = _verified(current, final, k, ctx) if (final is not None and current) else None
        if kind == "mismatch":
            diffs = _differences(current or {}, final, ctx, k)
            mismatches.append({"lock": k, "differences": diffs})
        chain.append({
            "lock": k,
            "entry_set_id": "carried" if kind == "carried" else (chosen["entry_set_id"] if chosen else None),
            "status": kind,
            "verified_entries": verified,
            "games": ctx.slate["locks"][k]["games"],
            "projections_file": chain_projs[k],
        })
        lineups_by_lock.append(current or {})
        provider_by_lock.append(provider)
        prev, prev_provider = current, provider

    final_matches_last = None
    if final is not None and prev is not None:
        final_matches_last = sum(1 for eid in ctx.entry_ids if prev.get(eid) == final.get(eid))
        if final_matches_last != len(ctx.entry_ids):
            mismatches.append({"lock": "final", "differences": _differences(prev, final, ctx)})
            warnings.append("final DK state differs from the last set in force (manual edits on DK's site?)")

    # Mid-night downloads: extra checks on their locked players only.
    midnight_checks = []
    for f in _active(found, ("midnight",)):
        j = ctx.locks_passed(f.mtime)
        f.reason = "check only"
        if j == 0:
            continue
        in_force = lineups_by_lock[j - 1]
        ok = 0
        for _, row in f.df.iterrows():
            lineup = in_force.get(row["entry_id"])
            if lineup and all(
                lineup[s] == int(row[s]) for s in ROSTER_SLOTS if row[f"{s}_locked"] and pd.notna(row[s])
            ):
                ok += 1
        f.used = True
        midnight_checks.append({"file": f.path, "after_lock": j - 1, "verified": ok, "entries": int(len(f.df))})
        if ok != len(f.df):
            warnings.append(f"{f.name}: {len(f.df) - ok} entries' locked players differ from L{j - 1}")

    unique_by_lock = {k: len({records.lineup_key(lu.values()) for lu in lineups_by_lock[k].values()})
                      for k in range(n_locks)}
    changed = {}
    for k in range(1, n_locks):
        a, b = lineups_by_lock[k - 1], lineups_by_lock[k]
        changed[k] = sum(1 for eid in ctx.entry_ids
                         if eid in a and eid in b and records.lineup_key(a[eid].values()) != records.lineup_key(b[eid].values()))

    # pre_lock_rank for sets the optimizer didn't write: rank in the in-force L0 run's ranked file.
    l0 = provider_by_lock[0] if provider_by_lock else None
    rank_map = _rank_map(slate_dir, _run_record_by_id(run_records, l0.get("run_id") if l0 else None))
    if rank_map:
        for es in entry_sets:
            if es["source"] != "optimizer":
                for e in es["entries"]:
                    e["pre_lock_rank"] = rank_map.get(e["lineup_key"])

    standings = []
    for f in _active(found, ("standings",)):
        f.copied_as = _place(f.path, slate_dir, f.name, dry_run)
        f.used, f.reason = True, "contest standings (copied as downloaded)"
        standings.append(f.copied_as)

    payload = {
        "schema": records.SCHEMA_VERSION,
        "slate_id": ctx.slate["slate_id"],
        "final_file": final_file.copied_as if final_file else None,
        "final_sha256": final_file.sha256 if final_file else None,
        "assignments": [f.to_json() for f in found],
        "chain": chain,
        "final_matches_last": final_matches_last,
        "mismatches": mismatches,
        "unique_lineups_by_lock": unique_by_lock,
        "changed_vs_previous": changed,
        "midnight_checks": midnight_checks,
        "standings": standings,
        "warnings": warnings,
    }

    if not dry_run:
        for es in entry_sets:
            records.write_entry_set(slate_dir, es)
        json_payload = dict(payload)
        json_payload["unique_lineups_by_lock"] = {str(k): v for k, v in unique_by_lock.items()}
        json_payload["changed_vs_previous"] = {str(k): v for k, v in changed.items()}
        records.write_json_atomic(os.path.join(slate_dir, FINALIZE_FILE), json_payload)
        _write_slate_entries(ctx, lineups_by_lock, provider_by_lock)

    _print_summary(payload, found, dry_run)
    payload["entry_sets"] = entry_sets
    return payload


def _run_record_by_id(run_records: List[dict], run_id: Optional[str]) -> Optional[dict]:
    if not run_id:
        return None
    return next((r for r in run_records if r.get("run_id") == run_id), None)


def _rank_map(slate_dir: str, run_record: Optional[dict]) -> Optional[Dict[str, int]]:
    if not run_record:
        return None
    path = os.path.join(slate_dir, run_record["ranked_file"])
    return records.rank_map_from_ranked(path) if os.path.isfile(path) else None


def _write_slate_entries(ctx: SlateContext, lineups_by_lock, provider_by_lock) -> None:
    rows = []
    for k, lineups in enumerate(lineups_by_lock):
        es = provider_by_lock[k]
        ranks = {e["entry_id"]: e.get("pre_lock_rank") for e in es["entries"]} if es else {}
        contests = {e["entry_id"]: e["contest_id"] for e in es["entries"]} if es else {}
        prev = lineups_by_lock[k - 1] if k > 0 else {}
        for eid in ctx.entry_ids:
            lineup = lineups.get(eid)
            if not lineup:
                continue
            key = records.lineup_key(lineup.values())
            changed = bool(prev.get(eid)) and records.lineup_key(prev[eid].values()) != key
            for s in ROSTER_SLOTS:
                pid = lineup[s]
                name, salary, game = ctx.player_info.get(pid, (None, None, None))
                rows.append({
                    "slate_id": ctx.slate["slate_id"], "lock": k,
                    "entry_set_id": es["entry_set_id"] if es else None,
                    "source": es["source"] if es else None,
                    "entry_id": eid, "contest_id": contests.get(eid), "slot": s, "dk_id": pid,
                    "name": name, "salary": salary, "game": game, "game_lock": ctx.player_lock.get(pid),
                    "lineup_key": key, "lineup_changed": changed, "pre_lock_rank": ranks.get(eid),
                })
    path = os.path.join(ctx.slate_dir, SLATE_ENTRIES_FILE)
    tmp = f"{path}.tmp"
    df = pd.DataFrame(rows, columns=SLATE_ENTRIES_COLUMNS)
    df["pre_lock_rank"] = df["pre_lock_rank"].astype("Int64")
    df.to_csv(tmp, index=False)
    records.replace_with_retry(tmp, path)


def _print_summary(payload: dict, found: List[FoundFile], dry_run: bool) -> None:
    print(f"\n=== {'DRY RUN: ' if dry_run else ''}finalize {payload['slate_id']} ===")
    print("Files:")
    for f in found:
        lock = "-" if f.lock is None else f"L{f.lock}"
        mark = "used   " if f.used else "ignored"
        target = f" -> {f.copied_as}" if f.copied_as and f.copied_as != f.name else ""
        print(f"  {mark} {lock:>3} {f.role:<16} {f.mtime:%H:%M:%S} {f.name}{target}  ({f.reason})")
    print("Chain:")
    n = len(payload["chain"])
    for c in payload["chain"]:
        k = c["lock"]
        changed = payload["changed_vs_previous"].get(k)
        changed_txt = f", {changed} changed" if changed is not None else ""
        verified = "-" if c["verified_entries"] is None else c["verified_entries"]
        print(
            f"  L{k} {'/'.join(c['games'])}: {c['status']} {c['entry_set_id'] or ''} "
            f"verified {verified}, unique {payload['unique_lineups_by_lock'][k]}{changed_txt}; "
            f"projections {c['projections_file']}"
        )
    if payload["final_matches_last"] is not None:
        print(f"Final DK state matches last set in force: {payload['final_matches_last']} entries")
    for m in payload["midnight_checks"]:
        print(f"Mid-night check {os.path.basename(m['file'])}: {m['verified']}/{m['entries']} vs L{m['after_lock']}")
    for w in payload["warnings"]:
        print(f"Warning: {w}")
    if n == 0:
        print("Warning: slate has no locks")


# --- RECORD ---


def record(
    file: str,
    slate_dir: str,
    lock: Optional[int] = None,
    source: Optional[str] = None,
) -> str:
    """Pin *file* as lock k's candidate (lineups) or projections; return the stored name."""
    ctx = load_context(slate_dir)
    role = records.classify_file(file)
    mtime = records.file_mtime(file)
    if lock is None:
        lock = lock_for_time(ctx.slate, mtime)
    if not 0 <= lock < len(ctx.locks):
        raise ValueError(f"--lock {lock} is out of range; this slate has locks 0-{len(ctx.locks) - 1}")
    pins = load_pins(slate_dir)

    if role in PROJ_ROLES:
        f = FoundFile(path=file, role=role, mtime=mtime, sha256=records.sha256_file(file), lock=lock)
        if not _belongs(ctx, f):
            raise ValueError(f"{os.path.basename(file)}: projections IDs don't match this slate's player pool")
        name = records.snapshot_input(file, slate_dir, records.projections_copy_name(file, lock))
        pins["projections"][str(lock)] = name
        records.write_json_atomic(os.path.join(slate_dir, PINS_FILE), pins)
        print(f"Pinned projections {name} to lock {lock}")
        return name
    if role not in CANDIDATE_ROLES:
        raise ValueError(f"{os.path.basename(file)}: not a lineup upload or projections file (classified {role})")

    df = records.read_lineup_file(file)
    label = os.path.basename(file)
    check_filled(label, df)
    lineups = records.lineups_from_df(df)
    entry_sets = load_entry_sets(slate_dir)
    check_record(label, lineups, ctx, _set_in_force_before(entry_sets, lock), lock)

    f = FoundFile(path=file, role=role, mtime=mtime, sha256=records.sha256_file(file), lock=lock)
    name = records.snapshot_input(file, slate_dir, _lineup_copy_name(f, lock))
    es = records.make_entry_set(
        slate_id=ctx.slate["slate_id"],
        lock=lock,
        source=source or _source_for(f),
        created_at=mtime,
        lineups_file=name,
        lineups_sha256=f.sha256,
        df_lineups=df,
        entry_order=ctx.entry_ids,
    )
    records.write_entry_set(slate_dir, es)
    pins["entry_sets"][str(lock)] = es["entry_set_id"]
    records.write_json_atomic(os.path.join(slate_dir, PINS_FILE), pins)
    print(f"Recorded {name} as {es['entry_set_id']} (pinned to lock {lock})")
    return name


# --- CLI ---


def _resolve_slate_dir(cfg: Config, slate_dir: Optional[str], entries: Optional[str]) -> str:
    if slate_dir:
        return slate_dir
    if entries:
        if not cfg.data_root:
            raise FileNotFoundError("NBA_DATA_ROOT is not set; pass --slate-dir")
        return os.path.join(cfg.data_root, build_slate(entries, cfg.slate_type)["slate_id"])
    return find_slate_dir(cfg, datetime.now().astimezone())


def main(argv=None):
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(prog="nba-dfs-capture", description="Nightly capture for the NBA DFS optimizer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fin = sub.add_parser("finalize", help="Assign tonight's files to locks, verify against DK and record them")
    p_fin.add_argument("--slate-dir", help="Slate folder (Default: tonight's under NBA_DATA_ROOT)")
    p_fin.add_argument("--sweep", action="append", default=[], help="Extra folder to search (repeatable)")
    p_fin.add_argument("--dry-run", action="store_true", help="Show assignments; copy and write nothing")
    p_fin.add_argument("--entries", help="Backfill only: the pre-lock DKEntries to build slate.json from")
    p_fin.add_argument("--assume-default-params", action="store_true",
                       help="Backfill only: write a reconstructed run record with the default settings")

    p_rec = sub.add_parser("record", help="Pin a specific file to a lock by hand")
    p_rec.add_argument("file")
    p_rec.add_argument("--lock", type=int, help="Lock index (Default: from the file's modified time)")
    p_rec.add_argument("--source", choices=("optimizer", "stokastic", "manual"))
    p_rec.add_argument("--slate-dir", help="Slate folder (Default: tonight's under NBA_DATA_ROOT)")

    args = parser.parse_args(argv)
    cfg = load_config_from_env()
    try:
        if args.command == "finalize":
            if args.assume_default_params and not args.entries:
                parser.error("--assume-default-params needs --entries")
            slate_dir = _resolve_slate_dir(cfg, args.slate_dir, args.entries)
            finalize(
                slate_dir,
                [cfg.downloads_dir, cfg.projs_dir] + args.sweep,
                dry_run=args.dry_run,
                entries=args.entries,
                assume_default_params=args.assume_default_params,
                slate_type=cfg.slate_type,
            )
        else:
            record(args.file, _resolve_slate_dir(cfg, args.slate_dir, None), lock=args.lock, source=args.source)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
