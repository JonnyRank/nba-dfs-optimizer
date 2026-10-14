# Plan 006: Generate lineups from one long-lived worker pool with a persistent per-worker HiGHS model

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 29809ed..HEAD -- src/nba_optimizer/engine.py tests/test_engine_constraints.py docs/codebase/ARCHITECTURE.md docs/codebase/CONCERNS.md docs/codebase/TESTING.md AGENTS.md src/nba_optimizer/gui.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (plans 001 and 004 are already DONE; this builds on their tests and loader)
- **Category**: perf
- **Planned at**: commit `29809ed`, 2026-10-14
- **Reviewed at**: commit `4784083`, 2026-10-14 — the plan's Step 1/3/4 code was applied to a scratch copy of `engine.py` and run: all 5 new test scenarios pass and the benchmark below was reproduced (see "Why this matters")
- **Issue**: https://github.com/JonnyRank/nba-dfs-optimizer/issues/58

## Why this matters

`engine.run` sends the whole player DataFrame with **every** task, uses two
separate `ProcessPoolExecutor`s, and rebuilds the PuLP model from scratch for
every lineup. Measurements taken on the maintainer's Windows machine (Python
3.14.2, 20 logical / 14 physical cores, pandas 3.0.1, PuLP 3.3.0, highspy
1.12.0, 138-player pool from `tests/fixtures`) show where the cost actually is:

| Cost | Measured | Share of a 2500-lineup run (~75 s) |
|---|---|---|
| Pickling the DataFrame per task (31 cols, 41 KB pickled, 122 KB in memory) | 0.14 ms dump + 0.19 ms load per task; 2500 no-op tasks take 1.14 s with the df vs 0.51 s seed-only | **< 1 %** (and the dump runs on the parent's feeder thread, overlapping worker compute) |
| Spawning a second pool for slotting (Windows `spawn` re-imports numpy/pandas/pulp/highspy in every worker) | 1.6 s per pool for 20 workers | ~2 % |
| Memory: each spawned worker commits ~700 MB of private memory because OpenBLAS reserves per-thread buffers at `import numpy` | 698 MB/worker default; **87 MB/worker** with `OPENBLAS_NUM_THREADS=1` | ~14 GB commit charge per pool → ~1.7 GB |
| PuLP model build + PuLP→HiGHS transfer per lineup (incl. 1,250 single `changeColIntegrality` calls) | ~80 ms of ~275 ms profiled | ~30 % |
| HiGHS MIP solve per lineup | ~120–190 ms | the rest |

So **DataFrame IPC is not the bottleneck**; the fix that minimizes IPC is
also the one that removes the real costs. This plan: (1) ships the player
pool to each worker **once** via a pool `initializer`, (2) builds the HiGHS
MIP **once per worker** and re-solves it by swapping only the objective
(prototype measured 162 ms → 82 ms per lineup with an identical optimal
objective), (3) slots lineups inside the worker so the second pool
disappears, (4) sends tasks as a small integer batch size and returns
tuples of ints + 8 strings, and (5) caps OpenBLAS threads in workers.

End-to-end measurements of exactly the code in this plan (same machine,
benchmark script from Step 0):

| Lineups | Current `engine.run` wall | This plan wall | Ratio |
|---|---|---|---|
| 500 | 15.4 s / 17.9 s (two runs; noisy) | 10.9 s / 10.8 s | ≈ 0.70 (best vs best) |
| 2500 | 76.0 s | 50.5 s | ≈ 0.66 |

Per-lineup solve time in-process, single thread: ~170 ms (PuLP path) vs
~141 ms (persistent model). The end-to-end gain is larger than that; the
remainder is attributed (not individually measured) to `threads=1` per
worker avoiding solver-thread oversubscription, the removed second pool,
and the one-time data transfer.

## Current state

Files:

- `src/nba_optimizer/engine.py` — lineup generation. `generate_single_lineup` (lines 32–136) is the PuLP worker; `slot_lineup_by_time` (lines 139–210) assigns DK slots by start time; `run` (lines 213–365) drives two process pools.
- `tests/test_engine_constraints.py` — deterministic LP-constraint tests calling `generate_single_lineup` directly with `randomness=0.0` on hand-built pools (`_build_pool`, `_build_single_game_dominant_pool`, `_is_slot_eligible`).
- `tests/fixtures/NBA-Projs-sample.csv`, `tests/fixtures/unfilled-DKEntries.csv` — real-shaped fixture slate (138 players with Projection ≥ 10).
- `src/nba_optimizer/orchestrator.py:28` — only production caller of `engine.run`; its signature must not change.
- `src/nba_optimizer/gui.py:11` — the GUI parses progress with `progress_regex=r"Lineups generated: (\d+)%"`. The `Lineups generated: N%` print text must stay byte-identical.

Excerpt — the per-task DataFrame pickling (`engine.py:265-273`). The comment is wrong: on Windows `df` is pickled for **each** submit, not once:

```python
        with concurrent.futures.ProcessPoolExecutor() as executor:
            # We must pass df, randomness, and min_salary to each worker
            # Since df is static, it gets pickled once (or shared via COW on Linux, but picked on Windows)
            futures = [
                executor.submit(
                    generate_single_lineup, df, randomness, cfg.min_salary, cfg.salary_cap, cfg.roster_size, cfg.min_games
                )
                for _ in range(target_lineups)
            ]
```

Excerpt — the second pool, again pickling `df` per lineup (`engine.py:334-343`):

```python
        with concurrent.futures.ProcessPoolExecutor() as executor:
            # map() executes in parallel but yields results in the original order
            results = executor.map(
                slot_lineup_by_time,
                valid_raw_names,
                itertools.repeat(df, len(valid_raw_names)),
            )

            for slotted in results:
                final_lineups.append(slotted)
```

Excerpt — the uniqueness filter that must keep its behavior (`engine.py:307-321`):

```python
        for names, indices in candidates:
            if len(valid_raw_names) >= target_lineups:
                break

            is_valid = True
            for prev_indices in selected_indices_list:
                overlap = len(indices.intersection(prev_indices))
                if overlap > (cfg.roster_size - min_unique):
                    is_valid = False
                    duplicates_removed += 1
                    break

            if is_valid:
                valid_raw_names.append(names)
                selected_indices_list.append(indices)
```

The MIP formulation in `generate_single_lineup` (which the new model must
reproduce exactly): binary `player[i]`; binary `slot[i][s]` for 8 slots;
`sum(salary*player) <= salary_cap`; `>= min_salary`; `sum(player) == roster_size`;
per player `sum_s slot[i][s] == player[i]`; `slot[i][s] == 0` when ineligible
(UTIL: all; G: PG or SG in position string; F: SF or PF; else slot name in
position string); per slot `sum_i slot[i][s] == 1`; binary `game[g]` for each
non-NaN, non-empty `Game`, with `game[g] <= sum(player in g)` and
`sum(game) >= min_games`. Objective: maximize `sum(sim_proj[i]*player[i])`
where `sim_proj = np.random.normal(Projection, Projection*randomness)` when
`randomness > 0`, else `Projection`.

Conventions to match (from `AGENTS.md` / `docs/codebase/CONVENTIONS.md`):
relative imports inside the package (`from .config import ...`), `snake_case`
functions, `UPPER_SNAKE_CASE` constants, `df_` prefix for DataFrames, `_dict`/`_map`
suffix for lookups, plain `print()` progress messages. Tests are transparent,
domain-relevant, no mocking — see the docstrings in
`tests/test_engine_constraints.py` for the expected style.

## Commands you will need

Run from the repo root in PowerShell. If `python` is not the repo venv, use `.\venv\Scripts\python.exe` in place of `python`. `grep` is not available in Windows PowerShell — every search in this plan is written with `Select-String`.

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `pip install -e .[dev]` | exit 0 |
| Import check | `python -c "from nba_optimizer import engine, ranker, exporter"` | exit 0, no output |
| Tests | `python -m pytest -q` | `37 passed` before this plan; `42 passed` after |
| Engine tests only | `python -m pytest -q tests/test_engine_constraints.py` | all pass |
| Benchmark | `python $env:TEMP\bench_engine.py (Get-Location).Path 500` | last line `BENCH rows=500 bad_rows=0 wall=<s>s` |

## Scope

**In scope** (the only files you should modify):
- `src/nba_optimizer/engine.py`
- `tests/test_engine_constraints.py`
- `docs/codebase/ARCHITECTURE.md` (lines 41–42 and 79–80 only)
- `docs/codebase/CONCERNS.md` (the "DataFrame pickled per worker on Windows" row only, line 35)
- `docs/codebase/TESTING.md` (the `generate_single_lineup` row of the test-coverage table only, line 33)
- `AGENTS.md` (the `tests/test_engine_constraints.py` bullet only)
- `$env:TEMP\bench_engine.py` (create; outside the repo, never commit)

**Out of scope** (do NOT touch):
- The bodies and signatures of `generate_single_lineup` and `slot_lineup_by_time`. `generate_single_lineup` stays as the reference implementation the existing tests and the new equivalence test compare against; `slot_lineup_by_time` is reused unchanged inside the worker.
- `engine.run`'s signature and return value (`orchestrator.py:28` is the only caller; the CLI and GUI reach it through the orchestrator).
- `src/nba_optimizer/late_swapper.py` — has its own PuLP model; not part of this change.
- `src/nba_optimizer/utils.py` / `load_data` — loader stays as is.
- The O(n²) `min_unique` filter algorithm — keep its logic; only the tuple shape it iterates changes.
- `multiprocessing.shared_memory`, Arrow, or any other zero-copy DataFrame scheme — the payload is ~40 KB; not worth the complexity.
- `pyproject.toml` — `highspy==1.12.0` is already a pinned dependency.

## Git workflow

- Branch: `advisor/006-persistent-worker-model`
- One commit per step that changes code; message style from `git log`, e.g. `perf: build HiGHS lineup model once per worker (plan 006)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Record the baseline

Create `$env:TEMP\bench_engine.py` (outside the repo) with exactly:

```python
import sys, tempfile, time
import pandas as pd
from nba_optimizer import engine
from nba_optimizer.config import Config

if __name__ == "__main__":
    repo = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    out_dir = tempfile.mkdtemp(prefix="bench-engine-")
    cfg = Config(
        entries_path=f"{repo}/tests/fixtures/unfilled-DKEntries.csv",
        projs_dir=f"{repo}/tests/fixtures",
        lineup_pool_dir=out_dir,
    )
    t = time.perf_counter()
    path = engine.run(cfg, num_lineups=n, randomness=0.25, min_unique=1)
    wall = time.perf_counter() - t
    df_out = pd.read_csv(path)
    bad = df_out.isin(["ERROR", "EMPTY"]).any(axis=1).sum()
    print(f"BENCH rows={len(df_out)} bad_rows={bad} wall={wall:.2f}s")
```

Run it **three** times and write down the **lowest** `wall` value as
`BASELINE_WALL` (run-to-run noise on the maintainer's machine was ~15%).
Close other CPU-heavy programs while benchmarking.

**Verify**: `python $env:TEMP\bench_engine.py (Get-Location).Path 500` → last line `BENCH rows=500 bad_rows=0 wall=...` (15–18 s on the maintainer's machine; your number may differ — only the ratio matters). `rows` may occasionally be 499 on the *baseline* (a `min_unique` duplicate was dropped); that is pre-existing behavior, not a failure. `python -m pytest -q` → `37 passed`.

### Step 1: Add `LineupModel` (persistent HiGHS MIP) to `engine.py`

Add `import highspy` with the other third-party imports, and add the code
below **between** `generate_single_lineup` and `slot_lineup_by_time`. Do not
modify `generate_single_lineup`. This code was prototyped and validated
against highspy 1.12.0 (same optimal objective as `generate_single_lineup`
on the fixture slate).

```python
# --- PERSISTENT MODEL (built once per worker process) ---


def _is_slot_eligible(pos_str: str, slot: str) -> bool:
    """DK slot eligibility; same rules as generate_single_lineup."""
    if slot == "UTIL":
        return True
    if slot == "G":
        return "PG" in pos_str or "SG" in pos_str
    if slot == "F":
        return "SF" in pos_str or "PF" in pos_str
    return slot in pos_str


class LineupModel:
    """The generate_single_lineup MIP, built once and re-solved per lineup.

    Only the objective coefficients change between solves, so the PuLP model
    build and PuLP->HiGHS transfer (~30% of per-lineup time) are paid once per
    worker instead of once per lineup. Columns 0..n-1 are the player binaries
    in positional (row) order of df.
    """

    def __init__(
        self, df: pd.DataFrame, min_salary: int, salary_cap: int, roster_size: int, min_games: int
    ):
        n = len(df)
        self.n_players = n
        pos_list = df["Roster Position"].astype(str).tolist()
        salary_arr = df["Salary"].to_numpy(dtype=float)
        game_list = df["Game"].tolist()

        # Slot columns exist only for eligible (player, slot) pairs, which is
        # equivalent to generate_single_lineup's "slot_vars[i][s] == 0" rows.
        slot_pairs = [
            (i, s) for i in range(n) for s in ROSTER_SLOTS if _is_slot_eligible(pos_list[i], s)
        ]
        games = [g for g in pd.unique(df["Game"]) if pd.notna(g) and g != ""]
        n_cols = n + len(slot_pairs) + len(games)

        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        # One solver thread per worker; the process pool supplies the parallelism.
        h.setOptionValue("threads", 1)
        h.addVars(n_cols, np.zeros(n_cols), np.ones(n_cols))
        h.changeColsIntegrality(
            n_cols,
            np.arange(n_cols, dtype=np.int32),
            np.array([highspy.HighsVarType.kInteger] * n_cols),
        )

        def add_row(lower, upper, cols, coefs):
            h.addRow(
                float(lower),
                float(upper),
                len(cols),
                np.asarray(cols, dtype=np.int32),
                np.asarray(coefs, dtype=float),
            )

        player_cols = list(range(n))
        add_row(min_salary, salary_cap, player_cols, salary_arr)
        add_row(roster_size, roster_size, player_cols, [1.0] * n)

        slot_cols_by_player = {i: [] for i in range(n)}
        slot_cols_by_slot = {s: [] for s in ROSTER_SLOTS}
        for k, (i, s) in enumerate(slot_pairs):
            slot_cols_by_player[i].append(n + k)
            slot_cols_by_slot[s].append(n + k)
        for i in range(n):
            cols = slot_cols_by_player[i]
            # sum_s slot[i][s] - player[i] == 0
            add_row(0, 0, cols + [i], [1.0] * len(cols) + [-1.0])
        for s in ROSTER_SLOTS:
            cols = slot_cols_by_slot[s]
            add_row(1, 1, cols, [1.0] * len(cols))

        # game[g] - sum(players in g) <= 0 ; sum(game) >= min_games
        inf = highspy.kHighsInf
        game_cols = []
        for g_idx, game in enumerate(games):
            col = n + len(slot_pairs) + g_idx
            game_cols.append(col)
            members = [i for i in range(n) if game_list[i] == game]
            add_row(-inf, 0, [col] + members, [1.0] + [-1.0] * len(members))
        add_row(min_games, inf, game_cols, [1.0] * len(game_cols))

        h.changeObjectiveSense(highspy.ObjSense.kMaximize)
        self._highs = h
        self._player_cols = np.arange(n, dtype=np.int32)

    def solve(self, projections) -> Optional[List[int]]:
        """Maximize sum(projections * player). Returns sorted row positions, or None if not optimal."""
        h = self._highs
        h.changeColsCost(self.n_players, self._player_cols, np.asarray(projections, dtype=float))
        h.run()
        if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
            return None
        col_values = np.asarray(h.getSolution().col_value[: self.n_players])
        return np.flatnonzero(col_values > 0.5).tolist()
```

Also change the existing `from typing import List, Set, Tuple` line to
`from typing import List, Optional, Set, Tuple`.

**Verify**: `python -c "from nba_optimizer.engine import LineupModel; print('ok')"` → `ok`. `python -m pytest -q` → `37 passed`.

### Step 2: Add tests for `LineupModel`

Append to `tests/test_engine_constraints.py` (reuse its existing
`_build_pool`, `_build_single_game_dominant_pool` helpers). Add these imports
at the top alongside the existing ones: `import os`, and extend the engine
import to `from nba_optimizer.engine import LineupModel, generate_single_lineup, load_data`.
Write exactly these four tests, each with a docstring in the file's style:

1. `test_persistent_model_matches_pulp_objective_on_fixture_slate` — build
   `df_pool = load_data(<fixtures>/NBA-Projs-sample.csv, <fixtures>/unfilled-DKEntries.csv)`,
   filter `Projection >= 10.0`, `reset_index(drop=True)`. Solve with
   `LineupModel(df_pool, cfg.min_salary, cfg.salary_cap, cfg.roster_size, cfg.min_games).solve(df_pool["Projection"])`
   and with `generate_single_lineup(df_pool, randomness=0.0, min_salary=cfg.min_salary, salary_cap=cfg.salary_cap, roster_size=cfg.roster_size, min_games=cfg.min_games)`
   (keyword style, as the existing tests do; `cfg = Config()`). Assert both return 8
   players, then compute `a = df_pool.loc[positions, "Projection"].sum()`
   (LineupModel) and `b = df_pool.loc[list(selected_indices), "Projection"].sum()`
   (PuLP) and assert `abs(a - b) <= 1e-4 * max(a, b)`. (Measured: identical
   objective, 301.92006…, on the fixture slate.) The docstring must say why:
   both solvers use HiGHS's default `mip_rel_gap = 1e-4`, and the two models
   are structured differently, so each may legally stop at a slightly
   different near-optimal lineup. (Compare objectives, not player sets — ties
   may pick different but equally optimal lineups.) Build the fixture path with
   `os.path.join(os.path.dirname(__file__), "fixtures", ...)` as `tests/test_utils.py:24` does.
2. `test_persistent_model_selects_the_only_feasible_lineup` — on `_build_pool()`,
   `solve(df_pool["Projection"])` returns `[0, 1, 2, 3, 4, 5, 6, 7]` (the
   module docstring explains this pool has exactly one feasible lineup).
3. `test_persistent_model_enforces_min_games_against_single_game_optimum` — on
   `_build_single_game_dominant_pool()`, the returned positions have length 8
   and `df_pool.loc[positions, "Game"].nunique() >= 2`.
4. `test_persistent_model_resolve_replaces_objective` — on the fixture slate
   (build `df_pool` the same way as test 1; a small module-level helper
   `_load_fixture_pool()` shared by tests 1, 4 and 5 is fine), solve once,
   take the first selected position `p`, build
   `proj = df_pool["Projection"].to_numpy(dtype=float).copy()`,
   set `proj[p] = -1000.0`, solve again **on the same model instance**, assert
   `p` is not in the second result and the second result has 8 players. This
   proves the second solve uses the new objective rather than a stale one.

**Verify**: `python -m pytest -q tests/test_engine_constraints.py` → all pass (8 tests). `python -m pytest -q` → `41 passed`.

Commit: `perf: add persistent HiGHS LineupModel for engine workers (plan 006)`.

### Step 3: Add the worker initializer and batch task

Add below `LineupModel` in `engine.py`:

```python
# Columns a worker needs: model build (Salary, Roster Position, Game,
# Projection) and slot_lineup_by_time (Name + ID, Roster Position, StartTime).
WORKER_COLUMNS = ["Name + ID", "Roster Position", "Salary", "Projection", "Game", "StartTime"]

# Per-process state, populated once by _init_worker. Lives in each spawned
# worker; the parent process never reads it.
_WORKER_STATE = {}


def _init_worker(
    df_pool: pd.DataFrame, randomness: float, min_salary: int, salary_cap: int, roster_size: int, min_games: int
) -> None:
    """ProcessPoolExecutor initializer: receive the pool once, build the model once."""
    _WORKER_STATE["df_pool"] = df_pool
    _WORKER_STATE["names"] = df_pool["Name + ID"].tolist()
    _WORKER_STATE["projection"] = df_pool["Projection"].to_numpy(dtype=float)
    _WORKER_STATE["randomness"] = randomness
    _WORKER_STATE["rng"] = np.random.default_rng()
    _WORKER_STATE["model"] = LineupModel(df_pool, min_salary, salary_cap, roster_size, min_games)


def _generate_batch(batch_size: int) -> List[Tuple[Tuple[int, ...], List[str]]]:
    """Solve and slot batch_size lineups. Returns (row positions, slotted names) per lineup."""
    state = _WORKER_STATE
    results = []
    for _ in range(batch_size):
        try:
            projection = state["projection"]
            if state["randomness"] > 0:
                sim_proj = state["rng"].normal(projection, projection * state["randomness"])
            else:
                sim_proj = projection
            positions = state["model"].solve(sim_proj)
            if positions is None:
                continue
            names = [state["names"][p] for p in positions]
            slotted = slot_lineup_by_time(names, state["df_pool"])
            results.append((tuple(positions), slotted))
        except Exception:
            traceback.print_exc()
    return results
```

Then add a test (5th new test) in `tests/test_engine_constraints.py`:

5. `test_worker_batch_returns_slotted_lineups` — build the fixture `df_pool`
   as in test 1, then narrow it: `df_pool = df_pool[engine.WORKER_COLUMNS].reset_index(drop=True)`
   (this mirrors what `run()` ships to workers in Step 4).
   Call `engine._init_worker(df_pool, 0.25, cfg.min_salary, cfg.salary_cap, cfg.roster_size, cfg.min_games)`
   in-process, then `batch = engine._generate_batch(3)`. Assert `len(batch) == 3`;
   for each `(positions, slotted)`: `len(positions) == 8`,
   `len(slotted) == 8`, no entry in `slotted` is `"ERROR"` or `"EMPTY"`, and
   `set(slotted) == set(df_pool.loc[list(positions), "Name + ID"])`.
   Wrap the body in `try: ... finally: engine._WORKER_STATE.clear()` so the
   module-global worker state (including a live `Highs` instance) does not
   leak into later tests in the same pytest process.
   (Import `from nba_optimizer import engine` for the private names.)

**Verify**: `python -m pytest -q` → `42 passed`.

Commit: `perf: add one-time worker initializer and batched lineup task (plan 006)`.

### Step 4: Rewire `run()` to one pool with the initializer

In `run()`, replace **lines 256–343 inclusive** of the current file — from
the `print(` that starts the "Spinning up pool with ..." message through the
last line of the second `with concurrent.futures.ProcessPoolExecutor()` block
(`final_lineups.append(slotted)`) — with the block below, verbatim. This also
removes the `# DEPRECATED` comments at lines 323–331. **Keep** line 345
(`print(f"Final valid lineups slotted and selected: {len(final_lineups)}")`)
and everything after it unchanged.

Before deleting, confirm line 256 is `        print(` followed by the
`Spinning up pool` f-string, and line 343 is
`                final_lineups.append(slotted)`. If not, STOP (drift).

Print-text notes: `Lineups generated: N%` must stay byte-identical (the GUI's
progress regex at `gui.py:11` parses it). "Total solver time" becomes "Total
generation time" because the timed section now includes slotting. The
filtering message drops "then slotting by start time" because slotting
already happened in the workers.

```python
        # Windows caps ProcessPoolExecutor at 61 workers.
        num_workers = min(61, multiprocessing.cpu_count())
        print(
            f"Spinning up pool with {num_workers} cores to generate ~{target_lineups} candidates..."
        )

        # Positional index so LineupModel's column order == row label.
        df_pool = df[WORKER_COLUMNS].reset_index(drop=True)

        # Spawned workers inherit this env at "import numpy"; without it each
        # worker's OpenBLAS reserves per-thread buffers (~700 MB commit per
        # worker vs ~90 MB). Workers do no BLAS work.
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

        # Small batches amortize task overhead while keeping ~4 batches per
        # worker for load balancing and progress reporting.
        batch_size = max(1, min(25, math.ceil(target_lineups / (num_workers * 4))))
        batch_sizes = [batch_size] * (target_lineups // batch_size)
        if target_lineups % batch_size:
            batch_sizes.append(target_lineups % batch_size)

        candidates = []

        # Start the timer
        start_time = time.perf_counter()

        with concurrent.futures.ProcessPoolExecutor(
            max_workers=num_workers,
            initializer=_init_worker,
            initargs=(df_pool, randomness, cfg.min_salary, cfg.salary_cap, cfg.roster_size, cfg.min_games),
        ) as executor:
            future_size_map = {executor.submit(_generate_batch, b): b for b in batch_sizes}
            completed = 0
            last_bucket = 0
            for future in concurrent.futures.as_completed(future_size_map):
                try:
                    candidates.extend(future.result())
                except Exception as exc:
                    print(f"Worker generated exception: {exc}")
                completed += future_size_map[future]
                # Report in 20% steps; bucket 5 (100%) is reached exactly once.
                bucket = completed * 5 // target_lineups
                if bucket > last_bucket:
                    print(f"Lineups generated: {bucket * 20}%")
                    last_bucket = bucket

        # Stop the timer and calculate the duration
        end_time = time.perf_counter()
        execution_time = end_time - start_time

        print(
            f"Total candidates generated: {len(candidates)}; Total generation time: {execution_time:.2f} seconds"
        )

        # Filter for Uniqueness / Min Unique (lineups arrive already slotted)
        final_lineups = []
        selected_indices_list = []
        duplicates_removed = 0

        print("Filtering candidates for uniqueness...")
        for positions, slotted in candidates:
            if len(final_lineups) >= target_lineups:
                break

            indices = set(positions)
            is_valid = True
            for prev_indices in selected_indices_list:
                overlap = len(indices.intersection(prev_indices))
                if overlap > (cfg.roster_size - min_unique):
                    is_valid = False
                    duplicates_removed += 1
                    break

            if is_valid:
                final_lineups.append(slotted)
                selected_indices_list.append(indices)

        print(f"Duplicates removed (min_unique constraint): {duplicates_removed}")
```

Leave one blank line between this block and the kept
`print(f"Final valid lineups slotted and selected: ...")` line.

Then fix imports at the top of `engine.py`:
- Replace the line `import itertools` with `import math` (it sits in the
  same alphabetical position; after this step nothing uses `itertools`).
  Confirm: `Select-String -Path src\nba_optimizer\engine.py -Pattern 'itertools'` → no output.
- `multiprocessing` stays (used by `cpu_count` and `freeze_support`); `os`
  stays.

**Verify**:
- `python -c "from nba_optimizer import engine, ranker, exporter"` → exit 0
- `python -m pytest -q` → `42 passed`
- `python $env:TEMP\bench_engine.py (Get-Location).Path 500` → last line `BENCH rows=500 bad_rows=0 wall=W`; the output contains `Lineups generated: 100%` exactly once, `Total generation time`, and no second "Spinning up" line.
- Run the benchmark three times; take the lowest `W`. Expect `W <= 0.80 * BASELINE_WALL`. (Measured with exactly this code: 10.8 s vs a 15.4 s best baseline at 500 lineups, ≈0.70×; ≈0.66× at 2500. The 0.80 bound leaves room for machine noise.)

Commit: `perf: single initializer-backed worker pool for engine generation (plan 006)`.

### Step 5: Update docs

- `docs/codebase/ARCHITECTURE.md` lines 41–42: describe one pool whose
  workers receive the player pool once via `initializer`, build a persistent
  HiGHS `LineupModel`, solve and slot lineups in batches, and return row
  positions + slotted names; the parent only applies the `min_unique` filter.
- `docs/codebase/ARCHITECTURE.md` lines 79–80: replace the "DataFrame
  pickling overhead" bullet with a note that the pool is sent once per worker
  (not per task) and that `OPENBLAS_NUM_THREADS=1` is set for workers; keep
  the worker-signature bullet only if still accurate (it is for `_init_worker`).
- `docs/codebase/CONCERNS.md`: mark the "DataFrame pickled per worker on
  Windows" row resolved by plan 006 (or remove it, matching how other
  resolved rows in that file are handled).
- `docs/codebase/TESTING.md` line 33: extend the "Target" cell to also name
  `nba_optimizer.engine.LineupModel` and the `_init_worker` / `_generate_batch`
  worker path, and the "Notes" cell to mention the fixture-slate objective
  equivalence check against `generate_single_lineup`.
- `AGENTS.md`: extend the `tests/test_engine_constraints.py` bullet to
  mention the persistent `LineupModel` and worker batch path.

**Verify**: `git diff --stat` lists only in-scope files. `Select-String -Path docs\codebase\ARCHITECTURE.md -Pattern 'pickles the full DataFrame'` → no output.

Commit: `docs: describe initializer-backed engine pool (plan 006)`.

## Test plan

- 5 new tests in `tests/test_engine_constraints.py` (Steps 2 and 3), modeled
  on the existing tests in that file: explicit pools, `randomness=0.0` where
  determinism matters, docstrings explaining the domain reason.
- Coverage: objective equivalence vs the reference PuLP model on a real
  slate; unique-solution pool; `min_games` enforcement; objective swap on a
  reused model; worker initializer + batch plumbing including slotting.
- Existing 4 `generate_single_lineup` tests must keep passing unchanged.
- After Step 2: `tests/test_engine_constraints.py` has 8 tests; after Step 3: 9.
- Final: `python -m pytest -q` → `42 passed`.

## Done criteria

- [ ] `python -c "from nba_optimizer import engine, ranker, exporter"` exits 0
- [ ] `python -m pytest -q` → `42 passed`
- [ ] Benchmark: `bad_rows=0`, `rows` equals 500 minus the printed `Duplicates removed` count (normally `rows=500`), and best-of-3 `wall <= 0.80 * BASELINE_WALL`
- [ ] `(Select-String -Path src\nba_optimizer\engine.py -Pattern 'ProcessPoolExecutor(' -SimpleMatch).Count` → `1`
- [ ] `(Select-String -Path src\nba_optimizer\engine.py -Pattern 'initializer=_init_worker' -SimpleMatch).Count` → `1`
- [ ] `(Select-String -Path src\nba_optimizer\engine.py -Pattern 'OPENBLAS_NUM_THREADS' -SimpleMatch).Count` → `1`
- [ ] `(Select-String -Path src\nba_optimizer\engine.py -Pattern 'itertools' -SimpleMatch).Count` → `0`
- [ ] `generate_single_lineup` and `slot_lineup_by_time` are byte-for-byte unchanged (AST comparison against the planned-at commit) — run
  `python -c "import ast,subprocess; old=subprocess.run(['git','show','29809ed:src/nba_optimizer/engine.py'],capture_output=True,text=True,check=True).stdout; new=open('src/nba_optimizer/engine.py',encoding='utf-8').read(); f=lambda s:{n.name:ast.dump(n) for n in ast.parse(s).body if isinstance(n,ast.FunctionDef)}; o,n=f(old),f(new); print(all(o[k]==n[k] for k in ('generate_single_lineup','slot_lineup_by_time')))"`
  → `True`
- [ ] `git status` shows no modified files outside the in-scope list (the bench script lives in `$env:TEMP`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Test 1 (objective equivalence) fails, i.e. the objectives differ by more than the `1e-4` relative MIP gap — the persistent model is not the same MIP; do not "fix" it by loosening the tolerance further.
- Any `highspy` call in Step 1 raises `AttributeError`/`TypeError` (API differs from 1.12.0) — report the installed `highspy` version (`python -c "import highspy, importlib.metadata as m; print(m.version('highspy'))"`).
- The benchmark shows `bad_rows > 0`, `rows` lower than 500 minus the printed `Duplicates removed` count, or best-of-3 `wall > 0.80 * BASELINE_WALL` after Step 4. Report both numbers; do not tune batch sizes, worker counts, or solver options beyond what this plan specifies.
- The run hangs, or prints `Worker generated exception:` / `BrokenProcessPool`, or `Exception in initializer:` (an exception inside `_init_worker`; the traceback is printed above it). A broken pool does not hang — it prints one exception line per batch and then writes a near-empty CSV, so check the output, not just the exit code.
- The change appears to require editing `generate_single_lineup`, `slot_lineup_by_time`, `orchestrator.py`, or `late_swapper.py`.

## Maintenance notes

- `LineupModel` and `generate_single_lineup` now encode the same MIP twice.
  Any new constraint (e.g. the BACKLOG items for grouping constraints or
  global exposure caps) must be added to `LineupModel`; keep test 1 as the
  guard that the two stay equivalent, or retire `generate_single_lineup` in
  a follow-up once `LineupModel` has its own full constraint test set.
- The BACKLOG "Graceful Early Interruption for Engine Generator" item
  interacts with this: with batches, Ctrl+C loses at most the in-flight
  batches (≤25 lineups each); cancel pending futures via
  `executor.shutdown(cancel_futures=True)`.
- Worker RNG is `np.random.default_rng()` seeded from OS entropy per worker
  (spawn guarantees distinct seeds). If reproducible runs are ever wanted,
  pass a base seed through `initargs` and derive per-worker seeds with
  `np.random.SeedSequence.spawn` — do not reintroduce per-task seeding.
- `os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")` mutates the parent
  process env for the rest of the run; harmless today (the parent does no
  heavy BLAS work) but revisit if a later stage uses numpy linear algebra in
  the same process.
- Reviewer focus: the progress-print loop (no infinite loop, single 100%),
  that the `min_unique` filter logic is unchanged apart from the tuple shape,
  and that `df_pool` uses `reset_index(drop=True)` (positions must equal row
  labels for `slot_lineup_by_time` and the parent filter).
- Behavior change: every candidate is now slotted inside the worker
  *before* the parent's `min_unique` filter, whereas before only surviving
  lineups were slotted. With the defaults (`min_unique=1`,
  `randomness=0.25`) duplicates are rare and the extra cost is negligible;
  with `min_unique >= 2` or `randomness = 0` a noticeable share of the
  ~5 ms slotting solves is wasted. If that matters, return unslotted
  positions and slot only the survivors in the same pool (second
  `executor.map` over `_slot_positions`) — still one pool, still no
  DataFrame per task.
- The timing print is renamed "Total generation time" because it now
  includes slotting.
- Deferred: the `min_unique` filter is O(n²) set intersections (~3M for 2500
  lineups, ~1 s); vectorize only if it shows up in a profile.
