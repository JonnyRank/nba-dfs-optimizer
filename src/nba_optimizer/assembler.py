"""Assemble the night's entries from a ranked pool under exposure caps (O-13).

First -u/--min_unique walks the pool in rank order and drops any lineup too
similar to a better-ranked one still in (O-14). Then a small integer program
picks exactly N of the survivors, minimising the sum of their Final_Rank,
with each player's count bounded by the --max/--min/--max-all settings.
With no caps or floors the answer is the first N survivors and no solver runs.
"""

import itertools
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
# Every solve, including each diagnosis re-solve, stops here (O-14 §3.6).
SOLVE_SECONDS = 10


@dataclass
class AssembleSettings:
    n_entries: int
    max: Dict[int, float] = field(default_factory=dict)
    min: Dict[int, float] = field(default_factory=dict)
    max_all: Optional[float] = None
    names: Dict[int, str] = field(default_factory=dict)
    min_unique: int = Config.min_unique


@dataclass
class AssembleResult:
    df_selected: pd.DataFrame  # ranked columns + Entry_Order, in entry order
    exposures: List[dict]
    solve: dict
    kept_top_n: int
    skipped_above_worst: int
    min_unique_removed: int = 0
    pool_size: int = 0


def max_count(pct: float, n: int) -> int:
    return math.floor(pct * n / 100 + 1e-9)


def min_count(pct: float, n: int) -> int:
    return math.ceil(pct * n / 100 - 1e-9)


def _player_sets(df_ranked: pd.DataFrame) -> List[set]:
    return [
        {int(pid) for pid in (extract_player_id(row[s]) for s in ROSTER_SLOTS) if pid}
        for _, row in df_ranked.iterrows()
    ]


def unique_survivors(sets: List[set], min_unique: int,
                     roster_size: int = len(ROSTER_SLOTS)) -> List[int]:
    """Row positions (in the given order, i.e. Final_Rank order) kept by the walk-down:
    a row is dropped when it shares >= roster_size + 1 - min_unique players with an
    earlier kept row. All rows when min_unique <= 0.
    """
    if min_unique <= 0:
        return list(range(len(sets)))
    # Two lineups share >= size players exactly when they share a size-player subset.
    size = roster_size + 1 - min_unique
    taken, keep = set(), []
    for i, players in enumerate(sets):
        subs = list(itertools.combinations(sorted(players), size))
        if not any(sub in taken for sub in subs):
            keep.append(i)
            taken.update(subs)
    return keep


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


@dataclass
class AssembleModel:
    """The rank-sum program, built once; constraints can be relaxed and restored between solves."""
    prob: pulp.LpProblem
    x: List[pulp.LpVariable]
    n: int
    constraints: List[dict]                       # each with "rows": its LpConstraints and "bound"


def build_model(sets: List[set], ranks: List[int], n: int, constraints: List[dict]) -> AssembleModel:
    """The rank-sum program over pool rows (in Final_Rank order) with every exposure constraint."""
    prob = pulp.LpProblem("Assemble", pulp.LpMinimize)
    x = [pulp.LpVariable(f"x{i}", cat=pulp.LpBinary) for i in range(len(sets))]
    prob += pulp.lpSum(r * xi for r, xi in zip(ranks, x))
    prob += pulp.lpSum(x) == n

    rows_by_player: Dict[int, List[int]] = {}
    for i, players in enumerate(sets):
        for pid in players:
            rows_by_player.setdefault(pid, []).append(i)

    def add(name, rows, sense, bound):
        constraint = pulp.LpConstraint(pulp.lpSum(x[i] for i in rows), sense=sense, rhs=bound, name=name)
        prob.addConstraint(constraint)
        return constraint

    # A player's own --max replaces --max-all for that player.
    own_max = {c["dk_id"] for c in constraints if c["kind"] == "max"}
    built = []
    for k, c in enumerate(constraints):
        c = dict(c)
        if c["kind"] == "max_all":
            # Only players who could exceed the cap need a row.
            c["rows"] = [
                add(f"c{k}_{pid}", rows_by_player[pid], pulp.LpConstraintLE, c["count"])
                for pid in sorted(rows_by_player)
                if pid not in own_max and len(rows_by_player[pid]) > c["count"]
            ]
        else:
            sense = pulp.LpConstraintLE if c["kind"] == "max" else pulp.LpConstraintGE
            c["rows"] = [add(f"c{k}", rows_by_player.get(c["dk_id"], []), sense, c["count"])]
        built.append(c)
    return AssembleModel(prob=prob, x=x, n=n, constraints=built)


@dataclass
class SolveOutcome:
    status: str        # "Optimal" (proven), "TimeLimit", "Infeasible", or another solver status
    chosen: List[int]  # [] unless exactly N rows
    proven: bool       # prob.sol_status == pulp.LpSolutionOptimal


def _timed_out(prob: pulp.LpProblem) -> bool:
    """HiGHS stopped at its time limit (PuLP maps a limit with nothing found to Not Solved)."""
    highs = getattr(prob, "solverModel", None)
    if highs is None:
        return False
    import highspy

    return highs.getModelStatus() == highspy.HighsModelStatus.kTimeLimit


def solve_model(model: AssembleModel, time_limit: float = SOLVE_SECONDS) -> SolveOutcome:
    """Solve the model as it stands, stopping after *time_limit* seconds."""
    # Default threads: see the comment above engine.LineupModel.__init__.
    model.prob.solve(pulp.HiGHS(msg=False, timeLimit=time_limit))
    # PuLP reports a HiGHS time limit as LpStatus "Optimal"; only sol_status says it isn't proven.
    proven = model.prob.sol_status == pulp.LpSolutionOptimal
    if proven:
        status = "Optimal"
    elif model.prob.sol_status == pulp.LpSolutionIntegerFeasible or _timed_out(model.prob):
        status = "TimeLimit"
    else:
        status = pulp.LpStatus[model.prob.status]
    chosen = []
    if status in ("Optimal", "TimeLimit"):
        chosen = [i for i, xi in enumerate(model.x) if (xi.value() or 0) > 0.5]
        if len(chosen) != model.n:
            chosen = []
    return SolveOutcome(status=status, chosen=chosen, proven=proven)


def _relaxed_solve(model: AssembleModel, c: dict) -> SolveOutcome:
    """Solve with *c* moved to a non-binding bound (a max to N, a min to 0), then restore it."""
    loose = model.n if c["kind"] in ("max", "max_all") else 0
    for row in c["rows"]:
        row.changeRHS(loose)
    try:
        return solve_model(model)
    finally:
        for row in c["rows"]:
            row.changeRHS(c["count"])


def _sorted_pool(df_ranked: pd.DataFrame) -> pd.DataFrame:
    return df_ranked.sort_values("Final_Rank", kind="stable").reset_index(drop=True)


def _precheck_floors(settings: AssembleSettings, sets: List[set], full_sets: List[set], pool_names) -> List[str]:
    """Floors the survivors (*sets*) can't meet, noting when the full pool would meet one."""
    n, size = settings.n_entries, len(sets)
    problems = []
    for dk_id, pct in settings.min.items():
        need = min_count(pct, n)
        have = sum(dk_id in s for s in sets)
        if have < need:
            problem = (f"{_name(settings, pool_names, dk_id)} min {fmt_pct(pct)}% (>={need} of {n}): "
                       f"in {have} of {size} lineups, need {need}")
            have_full = sum(dk_id in s for s in full_sets)
            if have_full >= need:
                problem += f" ({have_full} of the full pool before min_unique {settings.min_unique})"
            problems.append(problem)
    return problems


def _culprit_reason(c: dict, sets: List[set], n: int) -> str:
    size = len(sets)
    if c["kind"] == "max":
        have = sum(c["dk_id"] in s for s in sets)
        if size - have < n - c["count"]:
            return (f"{c['label']}: in {have} of {size} lineups of this pool, so only {size - have} "
                    f"lineups without this player; need {n - c['count']}")
        return f"{c['label']}: in {have} of {size} lineups of this pool; conflicts with the other constraints"
    if c["kind"] == "min":
        have = sum(c["dk_id"] in s for s in sets)
        return f"{c['label']}: in {have} of {size} lineups of this pool; conflicts with the other constraints"
    return f"{c['label']}: too few lineups in this pool to keep every player at or under the cap"


def _diagnose(model: AssembleModel, sets: List[set]) -> List[str]:
    """Culprits found by relaxing one constraint at a time in the already-built *model* (R1)."""
    if len(model.constraints) > MAX_DIAGNOSE_CONSTRAINTS:
        return ["infeasible; remove constraints to find the conflict"]
    found, unknown = [], []
    for c in model.constraints:
        outcome = _relaxed_solve(model, c)
        if outcome.chosen:
            found.append(_culprit_reason(c, sets, model.n))
        elif outcome.status == "TimeLimit":
            # Found nothing within the limit: not a culprit, but not ruled out either.
            unknown.append(c["label"])
    if unknown:
        found.append(f"couldn't check within {SOLVE_SECONDS:g} s whether removing one of these "
                     f"alone would fix it: {'; '.join(unknown)}")
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
    if not 0 <= settings.min_unique <= len(ROSTER_SLOTS):
        raise ValueError(f"min_unique must be 0-{len(ROSTER_SLOTS)}, got {settings.min_unique}")


def selection_violations(chosen_sets: List[set], settings: AssembleSettings) -> List[str]:
    """[] when there are N lineups, every pair shares <= 8 - u players (u >= 1), and all caps and floors hold."""
    n, u = settings.n_entries, settings.min_unique
    problems = []
    if len(chosen_sets) != n:
        problems.append(f"{len(chosen_sets)} lineups selected, need {n}")
    if u >= 1:
        most = len(ROSTER_SLOTS) - u
        for a, b in itertools.combinations(range(len(chosen_sets)), 2):
            if len(chosen_sets[a] & chosen_sets[b]) > most:
                problems.append(f"entries {a + 1} and {b + 1} share more than {most} players")
    counts: Dict[int, int] = {}
    for players in chosen_sets:
        for pid in players:
            counts[pid] = counts.get(pid, 0) + 1
    for dk_id, pct in settings.max.items():
        if counts.get(dk_id, 0) > max_count(pct, n):
            problems.append(f"{_name(settings, {}, dk_id)} over its max")
    for dk_id, pct in settings.min.items():
        if counts.get(dk_id, 0) < min_count(pct, n):
            problems.append(f"{_name(settings, {}, dk_id)} under its min")
    if settings.max_all is not None:
        cap = max_count(settings.max_all, n)
        problems += [f"{_name(settings, {}, pid)} over max-all" for pid, c in counts.items()
                     if pid not in settings.max and c > cap]
    return problems


def _infeasible(reasons: List[str]) -> ValueError:
    return ValueError("assemble infeasible:\n  " + "\n  ".join(reasons))


def assemble(df_ranked: pd.DataFrame, settings: AssembleSettings) -> AssembleResult:
    """Pick N lineups minimising the rank sum under min_unique and the exposure settings.

    Raises ValueError, naming the culprit constraints, when the request is
    infeasible; never returns a partial set.
    """
    validate_settings(settings)
    df_full = _sorted_pool(df_ranked)
    full_sets = _player_sets(df_full)
    pool_names = _names_from_pool(df_full)
    n, u = settings.n_entries, settings.min_unique
    if n > len(df_full):
        raise _infeasible([f"{n} entries but the pool has only {len(df_full)} lineups"])

    # Walk-down (O-14 §3.3): of two lineups that are too similar, the better-ranked stays.
    keep = unique_survivors(full_sets, u)
    removed = len(df_full) - len(keep)
    if len(keep) < n:
        raise ValueError(f"min_unique {u}: only {len(keep)} of the pool's {len(df_full)} lineups "
                         f"are that different (need {n}); lower -u")
    df = df_full.iloc[keep].reset_index(drop=True)
    sets = [full_sets[i] for i in keep]

    problems = _precheck_floors(settings, sets, full_sets, pool_names)
    if problems:
        raise _infeasible(problems)

    ranks = df["Final_Rank"].astype(int).tolist()
    constraints = _constraints(settings, pool_names)
    if not constraints:
        # No caps or floors: the optimum is the first N survivors.
        chosen, method, status, proven, seconds = list(range(n)), "top_n", "Optimal", True, 0.0
    else:
        method = "ilp"
        started = time.perf_counter()
        model = build_model(sets, ranks, n, constraints)
        outcome = solve_model(model)
        seconds = time.perf_counter() - started
        status, chosen, proven = outcome.status, outcome.chosen, outcome.proven
        if status == "Infeasible":
            # The diagnosis reuses this model rather than rebuilding it per attempt.
            reasons = _diagnose(model, sets)
            if removed > 0:
                full_model = build_model(full_sets, df_full["Final_Rank"].astype(int).tolist(), n, constraints)
                if solve_model(full_model).chosen:
                    # The walk-down keeps the better-ranked lineup, so this says "try a lower -u",
                    # not "-u and these caps can't both be met".
                    reasons.append(f"min_unique {u}: removes {removed} of {len(df_full)} lineups; "
                                   "these caps are feasible without it (try a lower -u)")
            raise _infeasible(reasons)
        if status == "TimeLimit" and not chosen:
            raise ValueError(f"assemble: no solution found in {SOLVE_SECONDS:g} s; loosen caps or lower -u")
        if not chosen:
            raise _infeasible([f"solver status {status}"])
        if status == "TimeLimit":
            print(f"Warning: solver hit its {SOLVE_SECONDS:g} s limit; using its best solution so far "
                  f"(rank sum {sum(ranks[i] for i in chosen)}). Not proven optimal.")

    violations = selection_violations([sets[i] for i in chosen], settings)
    if violations:
        raise RuntimeError("assemble selection breaks its own rules: " + "; ".join(violations))

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
    # Against the full pool's ranks, so both min_unique and the caps count.
    full_ranks = df_full["Final_Rank"].astype(int).tolist()
    return AssembleResult(
        df_selected=df_sel,
        exposures=exposures,
        solve={"status": status, "method": method, "proven_optimal": proven,
               "objective_rank_sum": int(df_sel["Final_Rank"].sum()),
               "seconds": round(seconds, 2), "worst_rank": worst},
        kept_top_n=sum(1 for r in full_ranks[:n] if r in selected),
        skipped_above_worst=sum(1 for r in full_ranks if r < worst and r not in selected),
        min_unique_removed=removed,
        pool_size=len(df_full),
    )


def settings_payload(settings: AssembleSettings, pool_names: Optional[Dict[int, str]] = None) -> dict:
    """The record's ``settings`` block: each cap with the count it becomes, plus min_unique."""
    pool_names = pool_names or {}
    n = settings.n_entries
    return {
        "max": [{"dk_id": k, "name": _name(settings, pool_names, k), "pct": v, "count": max_count(v, n)}
                for k, v in settings.max.items()],
        "min": [{"dk_id": k, "name": _name(settings, pool_names, k), "pct": v, "count": min_count(v, n)}
                for k, v in settings.min.items()],
        "max_all": settings.max_all,
        "min_unique": settings.min_unique,
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
    u, removed, size = settings.min_unique, result.min_unique_removed, result.pool_size
    if u <= 0:
        print(f"  min_unique: {u} (duplicates allowed)")
    elif u == 1:
        print(f"  min_unique: 1 -> removed {removed} exact duplicates of {size}")
    else:
        print(f"  min_unique: {u} -> any two entries share at most {len(ROSTER_SLOTS) - u} players; "
              f"removed {removed} of {size}")
    by_id = {e["dk_id"]: e for e in result.exposures}
    for dk_id in list(settings.max) + [k for k in settings.min if k not in settings.max]:
        e = by_id.get(dk_id)
        count = e["count"] if e else 0
        name = e["name"] if e else _name(settings, {}, dk_id)
        print(f"  {name}: {count}/{n} ({100 * count / n:.1f}%)")
    if settings.max_all is not None and result.exposures:
        top = result.exposures[0]
        print(f"  most exposed: {top['name']} {top['count']}/{n}")
    if result.solve["method"] == "top_n":
        print(f"Selection: top {n} after min_unique (no caps)")
    elif result.solve["status"] == "TimeLimit":
        print(f"Solve: TimeLimit after {SOLVE_SECONDS:g} s; best solution found (not proven optimal)")
    else:
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
        "min_unique_removed": result.min_unique_removed,
        "solve": result.solve,
        "exposures": result.exposures,
        "skipped_above_worst": result.skipped_above_worst,
    }
    path = os.path.splitext(output_file)[0] + ".json"
    records.write_json_atomic(path, payload)
    print(f"Assembly record: {os.path.basename(path)}")
    return output_file
