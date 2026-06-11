# Plan 005: Vectorize lineup ranking without changing output semantics

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat d6cbd5f..HEAD -- src/nba_optimizer/ranker.py src/nba_optimizer/utils.py README.md docs/codebase/CONCERNS.md BACKLOG.md tests`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: `plans/001-establish-verification-baseline.md`, `plans/004-consolidate-player-data-loading.md`
- **Category**: perf
- **Planned at**: commit `d6cbd5f`, 2026-06-11
- **Issue**: https://github.com/JonnyRank/nba-dfs-optimizer/issues/44

## Why this matters

`ranker.py` currently iterates lineup-by-lineup with `iterrows()`, builds Python lists, and computes every projection/ownership total in pure Python. That is acceptable for small lineup pools, but it becomes the next clear bottleneck once lineup counts grow. This plan rewrites the metric calculation as vectorized pandas work while preserving the current ranking semantics and output columns.

## Current state

Relevant files and their current roles:

- `src/nba_optimizer/ranker.py` — loads lineup pools and player context, computes lineup metrics, ranks them, and writes ranked CSVs.
- tests created by plan 001 — should provide a safe place to add characterization coverage around ranking outputs.

Current-state excerpts:

- `src/nba_optimizer/ranker.py:27-52`

  ```py
  proj_map = df_players.set_index("Name + ID")["Projection"].to_dict()
  own_map = df_players.set_index("Name + ID")["Own_Proj"].to_dict()
  ...
  for idx, row in df_lineups.iterrows():
      lineup_names = [row[s] for s in slots]
      total_proj = sum([proj_map.get(name, 0) for name in lineup_names])
      total_own = sum([own_map.get(name, 0) for name in lineup_names])
      own_values = [own_map.get(name, 0) for name in lineup_names]
      geo_own = np.exp(np.mean(np.log([max(0.1, o) for o in own_values])))
  ```

- `src/nba_optimizer/ranker.py:61-71`

  ```py
  df_res["Proj_Rank"] = df_res["Total_Projection"].rank(ascending=False)
  df_res["Own_Rank"] = df_res["Total_Ownership"].rank(ascending=True)
  df_res["Geo_Rank"] = df_res["Geomean_Ownership"].rank(ascending=True)
  df_res["Lineup_Score"] = ...
  df_res = df_res.sort_values("Lineup_Score")
  ```

Repo conventions to follow:

- Keep DataFrame variables prefixed with `df_`.
- Preserve the current columns and public `run()` entry point behavior.
- Use pandas/numpy directly; do not add new runtime dependencies for this optimization.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Imports after refactor | `python -c "from nba_optimizer import ranker"` | exit 0 |
| Full regression suite | `python -m pytest -q` | exit 0 |
| Focused ranker tests | `python -m pytest tests/test_ranker.py -q` | exit 0 |

## Scope

**In scope**:

- `src/nba_optimizer/ranker.py`
- tests added for ranking behavior, likely `tests/test_ranker.py`
- `docs/codebase/CONCERNS.md` (optional if you want to retire the performance concern)
- `BACKLOG.md` (optional status update only)

**Out of scope**:

- changing ranking weights or semantics
- introducing new ranking metrics
- moving metric calculation into `engine.py`
- optimizer-engine performance work

## Git workflow

- Branch: `advisor/005-vectorize-lineup-ranking`
- Commit using the repo’s conventional style, for example: `perf: vectorize lineup scoring in ranker`
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Characterize the current ranker outputs

Before changing the implementation, add a focused test that locks down current ranking semantics on a tiny synthetic lineup pool. Capture:

- total projection
- total ownership
- geometric mean ownership with the current `max(0.1, own)` floor
- final ranking order for a fixture with unambiguous weighted scores

This test is the guardrail that lets you optimize the implementation without changing behavior.

**Verify**: `python -m pytest tests/test_ranker.py -q` → exit 0

### Step 2: Replace row iteration with vectorized column mapping

Refactor `rank_lineups()` to compute metrics column-wise. A likely pattern is:

- for each roster slot column, map `Name + ID` to projection and ownership series
- sum the mapped projection columns and ownership columns across axis 1
- compute geometric mean ownership using numpy over an ownership-value matrix with the same `max(0.1, own)` floor semantics
- preserve the final DataFrame shape and ranking columns

Do not change tie behavior unless your characterization test proves the current behavior more explicitly.

**Verify**: `python -m pytest tests/test_ranker.py -q` → exit 0

### Step 3: Remove now-unused Python-loop scaffolding

Delete obsolete `iterrows()`-based code, intermediate Python lists, and any imports that are no longer needed. Keep the function readable; this should be a straightforward vectorized implementation, not an over-engineered abstraction.

**Verify**: `python -c "from nba_optimizer import ranker"` → exit 0

### Step 4: Re-run the broader baseline and update docs if needed

Run the full test suite. If `docs/codebase/CONCERNS.md` currently flags `iterrows()` as an active performance concern, update that note to reflect the new state.

If you update `BACKLOG.md`, do so only if the vectorization task is actually complete.

**Verify**: `python -m pytest -q` → exit 0

## Test plan

- Add `tests/test_ranker.py` with a tiny lineup pool and tiny player-context frame that proves:
  - projections sum correctly across all roster slots
  - ownership sums correctly across all roster slots
  - geometric mean ownership preserves the current floor behavior
  - final sort order matches the pre-refactor implementation
- Re-run the full suite from plan 001.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest tests/test_ranker.py -q` exits 0
- [ ] `python -m pytest -q` exits 0
- [ ] `python -c "from nba_optimizer import ranker"` exits 0
- [ ] `src/nba_optimizer/ranker.py` no longer uses `iterrows()` for lineup metric calculation
- [ ] Output columns and ranking semantics remain unchanged for the characterization fixture
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- plan 001 has not landed and there is still no characterization coverage for ranker behavior
- plan 004 changes the player-context contract in a way that invalidates the fixture assumptions here
- the vectorized version cannot preserve current semantics without a larger redesign of ranking behavior
- performance improvements would require adding dependencies or changing artifact formats

## Maintenance notes

- Reviewers should compare semantics, not just speed. A faster ranker that changes lineup ordering is a regression.
- Keep the floor behavior for geometric mean ownership explicit in code; it is easy to lose during vectorization.
- If future ranking metrics are added, prefer composing additional vectorized columns rather than reintroducing row iteration.
