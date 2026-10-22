"""Assemble the night's entries from a ranked pool under exposure caps (O-13).

A small integer program: pick exactly N lineups, minimising the sum of
their Final_Rank, with each player's count bounded by the --max/--min/
--max-all settings. With no settings the optimum is ranks 1..N.
"""

import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import pulp

from . import records
from .config import Config, ROSTER_SLOTS
from .utils import extract_player_id

ASSEMBLED_PREFIX = "assembled-lineups"
# Re-solving once per dropped constraint is cheap (< 2 s each) up to this many.
MAX_DIAGNOSE_CONSTRAINTS = 20


@dataclass
class AssembleSettings:
    n_entries: int
    max: Dict[int, float] = field(default_factory=dict)
    min: Dict[int, float] = field(default_factory=dict)
    max_all: Optional[float] = None
    names: Dict[int, str] = field(default_factory=dict)


@dataclass
class AssembleResult:
    df_selected: pd.DataFrame  # ranked columns + Entry_Order, in entry order
    exposures: List[dict]
    solve: dict
    kept_top_n: int
    skipped_above_worst: int


def max_count(pct: float, n: int) -> int:
    return math.floor(pct * n / 100 + 1e-9)


def min_count(pct: float, n: int) -> int:
    return math.ceil(pct * n / 100 - 1e-9)


def _player_sets(df_ranked: pd.DataFrame) -> List[set]:
    return [
        {int(pid) for pid in (extract_player_id(row[s]) for s in ROSTER_SLOTS) if pid}
        for _, row in df_ranked.iterrows()
    ]


def _names_from_pool(df_ranked: pd.DataFrame) -> Dict[int, str]:
    names = {}
    for s in ROSTER_SLOTS:
        for cell in df_ranked[s].dropna().astype(str):
            pid = extract_player_id(cell)
            if pid and int(pid) not in names:
                names[int(pid)] = cell.split(" (")[0]
    return names


def _name(settings: AssembleSettings, pool_names: Dict[int, str], dk_id: int) -> str:
    return settings.names.get(dk_id) or pool_names.get(dk_id) or str(dk_id)


def _constraints(settings: AssembleSettings, pool_names: Dict[int, str]) -> List[dict]:
    """Exposure constraints, one per --max/--min player; --max-all is a single constraint."""
    n = settings.n_entries
    out = []
    for dk_id, pct in settings.max.items():
        cap = max_count(pct, n)
        out.append({"dk_id": dk_id, "kind": "max", "count": cap,
                    "label": f"{_name(settings, pool_names, dk_id)} max {fmt_pct(pct)}% (<={cap} of {n})"})
    for dk_id, pct in settings.min.items():
        floor = min_count(pct, n)
        out.append({"dk_id": dk_id, "kind": "min", "count": floor,
                    "label": f"{_name(settings, pool_names, dk_id)} min {fmt_pct(pct)}% (>={floor} of {n})"})
    if settings.max_all is not None:
        cap = max_count(settings.max_all, n)
        out.append({"dk_id": None, "kind": "max_all", "count": cap,
                    "label": f"max-all {fmt_pct(settings.max_all)}% (<={cap} of {n})"})
    return out


def fmt_pct(pct: float) -> str:
    return f"{pct:g}"


def _solve(sets: List[set], ranks: List[int], n: int, constraints: List[dict]):
    """(status, chosen row positions) for the rank-sum program; rows are in Final_Rank order."""
    prob = pulp.LpProblem("Assemble", pulp.LpMinimize)
    x = [pulp.LpVariable(f"x{i}", cat=pulp.LpBinary) for i in range(len(sets))]
    prob += pulp.lpSum(r * xi for r, xi in zip(ranks, x))
    prob += pulp.lpSum(x) == n

    rows_by_player: Dict[int, List[int]] = {}
    for i, players in enumerate(sets):
        for pid in players:
            rows_by_player.setdefault(pid, []).append(i)

    # A player's own --max replaces --max-all for that player.
    own_max = {c["dk_id"] for c in constraints if c["kind"] == "max"}
    for c in constraints:
        if c["kind"] == "max_all":
            # Only players who could exceed the cap need a row.
            for pid in sorted(rows_by_player):
                if pid not in own_max and len(rows_by_player[pid]) > c["count"]:
                    prob += pulp.lpSum(x[i] for i in rows_by_player[pid]) <= c["count"]
            continue
        rows = rows_by_player.get(c["dk_id"], [])
        if c["kind"] == "max":
            prob += pulp.lpSum(x[i] for i in rows) <= c["count"]
        else:
            prob += pulp.lpSum(x[i] for i in rows) >= c["count"]

    # Default threads: see the comment above engine.LineupModel.__init__.
    prob.solve(pulp.HiGHS(msg=False))
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        return status, []
    return status, [i for i, xi in enumerate(x) if (xi.value() or 0) > 0.5]


def _sorted_pool(df_ranked: pd.DataFrame) -> pd.DataFrame:
    return df_ranked.sort_values("Final_Rank", kind="stable").reset_index(drop=True)


def _precheck(df_ranked: pd.DataFrame, settings: AssembleSettings, sets: List[set], pool_names) -> List[str]:
    n, size = settings.n_entries, len(df_ranked)
    problems = []
    if n > size:
        problems.append(f"{n} entries but the pool has only {size} lineups")
    for dk_id, pct in settings.min.items():
        need = min_count(pct, n)
        have = sum(dk_id in s for s in sets)
        if have < need:
            problems.append(
                f"{_name(settings, pool_names, dk_id)} min {fmt_pct(pct)}% (>={need} of {n}): "
                f"in {have} of {size} lineups, need {need}"
            )
    return problems


def _culprit_reason(c: dict, sets: List[set], n: int) -> str:
    size = len(sets)
    if c["kind"] == "max":
        have = sum(c["dk_id"] in s for s in sets)
        return (f"{c['label']}: in {have} of {size} lineups of this pool, so only {size - have} "
                f"lineups without this player; need {n - c['count']}")
    if c["kind"] == "min":
        have = sum(c["dk_id"] in s for s in sets)
        return f"{c['label']}: in {have} of {size} lineups of this pool"
    return f"{c['label']}: too few lineups in this pool to keep every player at or under the cap"


def diagnose_infeasible(df_ranked: pd.DataFrame, settings: AssembleSettings) -> List[str]:
    """Constraints whose removal alone makes the program feasible, with a reason each (§3.8)."""
    df = _sorted_pool(df_ranked)
    sets = _player_sets(df)
    pool_names = _names_from_pool(df)
    ranks = df["Final_Rank"].astype(int).tolist()
    constraints = _constraints(settings, pool_names)
    if len(constraints) > MAX_DIAGNOSE_CONSTRAINTS:
        return ["infeasible; remove constraints to find the conflict"]
    found = []
    for c in constraints:
        rest = [o for o in constraints if o is not c]
        status, _ = _solve(sets, ranks, settings.n_entries, rest)
        if status == "Optimal":
            found.append(_culprit_reason(c, sets, settings.n_entries))
    return found or ["infeasible; no single constraint is the cause, remove constraints to find the conflict"]


def validate_settings(settings: AssembleSettings) -> None:
    pcts = list(settings.max.values()) + list(settings.min.values())
    if settings.max_all is not None:
        pcts.append(settings.max_all)
    bad = [p for p in pcts if not 0 <= p <= 100]
    if bad:
        raise ValueError(f"exposure percentages must be within 0-100, got {[fmt_pct(p) for p in bad]}")
    if settings.n_entries <= 0:
        raise ValueError("no entries to assemble (DKEntries has no entry rows)")


def assemble(df_ranked: pd.DataFrame, settings: AssembleSettings) -> AssembleResult:
    """Pick N lineups minimising the rank sum under the exposure settings.

    Raises ValueError, naming the culprit constraints, when the request is
    infeasible; never returns a partial set.
    """
    validate_settings(settings)
    df = _sorted_pool(df_ranked)
    sets = _player_sets(df)
    pool_names = _names_from_pool(df)
    n = settings.n_entries

    problems = _precheck(df, settings, sets, pool_names)
    if problems:
        raise ValueError("assemble infeasible:\n  " + "\n  ".join(problems))

    ranks = df["Final_Rank"].astype(int).tolist()
    constraints = _constraints(settings, pool_names)
    started = time.perf_counter()
    status, chosen = _solve(sets, ranks, n, constraints)
    seconds = time.perf_counter() - started
    if status != "Optimal":
        reasons = diagnose_infeasible(df, settings) if status == "Infeasible" else [f"solver status {status}"]
        raise ValueError("assemble infeasible:\n  " + "\n  ".join(reasons))

    df_sel = df.iloc[chosen].sort_values("Final_Rank", kind="stable").reset_index(drop=True)
    df_sel.insert(0, "Entry_Order", range(1, len(df_sel) + 1))

    counts: Dict[int, int] = {}
    for i in chosen:
        for pid in sets[i]:
            counts[pid] = counts.get(pid, 0) + 1
    exposures = [
        {"dk_id": pid, "name": _name(settings, pool_names, pid), "count": c, "pct": round(100 * c / n, 1)}
        for pid, c in sorted(counts.items(), key=lambda kv: (-kv[1], _name(settings, pool_names, kv[0])))
    ]
    worst = int(df_sel["Final_Rank"].max())
    selected = set(df_sel["Final_Rank"].astype(int))
    return AssembleResult(
        df_selected=df_sel,
        exposures=exposures,
        solve={"status": status, "objective_rank_sum": int(df_sel["Final_Rank"].sum()),
               "seconds": round(seconds, 2), "worst_rank": worst},
        kept_top_n=sum(1 for r in ranks[:n] if r in selected),
        skipped_above_worst=sum(1 for r in ranks if r < worst and r not in selected),
    )


def settings_payload(settings: AssembleSettings, pool_names: Optional[Dict[int, str]] = None) -> dict:
    """The record's ``settings`` block: each cap with the count it becomes."""
    pool_names = pool_names or {}
    n = settings.n_entries
    return {
        "max": [{"dk_id": k, "name": _name(settings, pool_names, k), "pct": v, "count": max_count(v, n)}
                for k, v in settings.max.items()],
        "min": [{"dk_id": k, "name": _name(settings, pool_names, k), "pct": v, "count": min_count(v, n)}
                for k, v in settings.min.items()],
        "max_all": settings.max_all,
    }


def print_summary(result: AssembleResult, settings: AssembleSettings) -> None:
    n = settings.n_entries
    print(f"Entries: {n}")
    for c in settings_payload(settings)["max"]:
        print(f"  max {c['name']}: {fmt_pct(c['pct'])}% of {n} -> at most {c['count']}")
    for c in settings_payload(settings)["min"]:
        print(f"  min {c['name']}: {fmt_pct(c['pct'])}% of {n} -> at least {c['count']}")
    if settings.max_all is not None:
        print(f"  max-all: {fmt_pct(settings.max_all)}% of {n} -> at most {max_count(settings.max_all, n)} per player")
    by_id = {e["dk_id"]: e for e in result.exposures}
    for dk_id in list(settings.max) + [k for k in settings.min if k not in settings.max]:
        e = by_id.get(dk_id)
        count = e["count"] if e else 0
        name = e["name"] if e else _name(settings, {}, dk_id)
        print(f"  {name}: {count}/{n} ({100 * count / n:.1f}%)")
    if settings.max_all is not None and result.exposures:
        top = result.exposures[0]
        print(f"  most exposed: {top['name']} {top['count']}/{n}")
    print(f"Solve: {result.solve['status']} in {result.solve['seconds']:.1f} s")
    print(f"Worst selected rank: {result.solve['worst_rank']}; {result.kept_top_n} of ranks 1-{n} kept")


def assembled_path(cfg: Config, slate: Optional[dict], run_time: datetime) -> str:
    slate_date = slate["slate_date"] if slate else run_time.strftime("%Y-%m-%d")
    slate_type = slate["slate_type"] if slate else cfg.slate_type
    type_part = "" if slate_type == "main" else f"{slate_type.capitalize()}-"
    timestamp = f"{type_part}{slate_date}_{run_time.strftime('%H%M%S')}"
    return os.path.join(cfg.ranked_lineup_dir, f"{ASSEMBLED_PREFIX}-{timestamp}.csv")


def run(
    cfg: Config,
    ranked_file: str,
    settings: AssembleSettings,
    run_time: Optional[datetime] = None,
    slate: Optional[dict] = None,
    inherited: Optional[List[str]] = None,
) -> str:
    """Assemble from *ranked_file*; write the CSV, then its JSON record. Returns the CSV path.

    Raises ValueError (nothing written) when the settings are infeasible.
    """
    run_time = (run_time or datetime.now()).astimezone().replace(microsecond=0)
    print(f"Assembling from: {os.path.basename(ranked_file)}")
    df_ranked = pd.read_csv(ranked_file)
    result = assemble(df_ranked, settings)
    print_summary(result, settings)

    os.makedirs(cfg.ranked_lineup_dir, exist_ok=True)
    output_file = assembled_path(cfg, slate, run_time)
    cols = ["Entry_Order"] + [c for c in df_ranked.columns]
    result.df_selected[cols].to_csv(output_file, index=False)
    print(f"Saved to: {output_file}")

    run_record = {}
    rec_path = records.run_record_path(ranked_file)
    if os.path.isfile(rec_path):
        run_record = records.read_json(rec_path)
    slate_id = (slate or {}).get("slate_id") or run_record.get("slate_id")
    ts = records.compact_ts(run_time)
    payload = {
        "schema": records.SCHEMA_VERSION,
        "assembly_id": f"{slate_id}_A{ts}" if slate_id else f"A{ts}",
        "slate_id": slate_id,
        "generated_at": records.iso_seconds(run_time),
        "run_id": run_record.get("run_id"),
        "ranked_file": os.path.basename(ranked_file),
        "assembled_file": os.path.basename(output_file),
        "n_entries": settings.n_entries,
        "settings": settings_payload(settings, _names_from_pool(df_ranked)),
        "inherited": list(inherited or []),
        "solve": result.solve,
        "exposures": result.exposures,
        "skipped_above_worst": result.skipped_above_worst,
    }
    path = os.path.splitext(output_file)[0] + ".json"
    records.write_json_atomic(path, payload)
    print(f"Assembly record: {os.path.basename(path)}")
    return output_file
