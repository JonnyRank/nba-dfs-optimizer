# Plan 004: Consolidate player-pool loading into a shared utility

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat d6cbd5f..HEAD -- src/nba_optimizer/engine.py src/nba_optimizer/late_swapper.py src/nba_optimizer/ranker.py src/nba_optimizer/utils.py README.md docs/codebase/ARCHITECTURE.md docs/codebase/CONCERNS.md BACKLOG.md`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/001-establish-verification-baseline.md`
- **Category**: tech-debt
- **Planned at**: commit `d6cbd5f`, 2026-06-11

## Why this matters

The codebase currently has two different player-pool loading implementations: one in `engine.py` and one in `late_swapper.py`. They parse the same DraftKings/projections inputs differently, merge with different semantics (`inner` vs `left`), and compute different derived columns. On top of that, `ranker.py` reaches into `engine.py` to reuse its loader, which couples ranking to engine internals. This plan creates a single shared loading utility with explicit modes so future fixes land once and every stage consumes the same documented data contract.

## Current state

Relevant files and their current roles:

- `src/nba_optimizer/engine.py` — loads DK entries + projections for full generation.
- `src/nba_optimizer/late_swapper.py` — separately loads DK entries + projections for late-swap re-optimization.
- `src/nba_optimizer/ranker.py` — imports `engine.load_data` to get merged player context.
- `src/nba_optimizer/utils.py` — already owns shared parsing helpers and is the most natural home for a shared loader unless a new dedicated module is clearly cleaner.

Current-state excerpts:

- `src/nba_optimizer/engine.py:23-52`

  ```py
  def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
      df_raw = pd.read_csv(entries_file, skiprows=7)
      ...
      df = pd.merge(df_players, df_projs, on="ID", how="inner")
      df["StartTime"] = df["Game Info"].apply(parse_time)
      df["Game"] = df["Game Info"].str.split(" ").str[0]
  ```

- `src/nba_optimizer/late_swapper.py:20-45`

  ```py
  def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
      ...
      df_raw = pd.read_csv(io.StringIO("".join(lines[player_pool_start_idx:])))
      ...
      df = pd.merge(df_players, df_projs, on="ID", how="left")
      df["Projection"] = pd.to_numeric(df["Projection"]).fillna(0)
  ```

- `src/nba_optimizer/ranker.py:14-23`

  ```py
  def load_data(...):
      ...
      from .engine import load_data as engine_load_data
      df_players = engine_load_data(projs_file, cfg.entries_path)
  ```

- `src/nba_optimizer/utils.py:8-77` already contains shared parsing helpers like `extract_player_id`, `parse_game_time`, and `read_ragged_csv`.

Repo conventions to follow:

- Shared code belongs in a utility/module boundary, not copied between stage modules.
- Keep relative imports inside `src/nba_optimizer/`.
- Preserve simple `Config` injection and `print()`-based error handling at the `run()` layer.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Imports after refactor | `python -c "from nba_optimizer import engine, late_swapper, ranker, utils"` | exit 0 |
| Full baseline tests | `python -m pytest -q` | exit 0 |
| Focused loader tests | `python -m pytest tests/test_utils.py -q` | exit 0 |

## Scope

**In scope**:

- `src/nba_optimizer/utils.py` or a new `src/nba_optimizer/data_loader.py`
- `src/nba_optimizer/engine.py`
- `src/nba_optimizer/late_swapper.py`
- `src/nba_optimizer/ranker.py`
- `README.md`
- `docs/codebase/ARCHITECTURE.md`
- `docs/codebase/CONCERNS.md`
- tests added under the baseline from plan 001
- `BACKLOG.md` (optional status update only)

**Out of scope**:

- changing late-swap optimization behavior beyond matching the intended loader contract
- broad refactoring of `engine.py` beyond removing duplicated loading logic
- adding database-backed historical data
- simulator implementation

## Git workflow

- Branch: `advisor/004-consolidate-player-data-loading`
- Commit using the repo’s conventional style, for example: `refactor: share player data loader across optimizer stages`
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Define the shared loader contract before moving code

Write down the concrete loader outputs the repo needs across stages. At minimum, decide:

- which columns are guaranteed in the returned DataFrame
- whether the helper should support both `inner` and `left` merge semantics through an explicit option
- whether DKEntries parsing differences should be represented as separate parser helpers that feed one shared merge step

The likely clean design is a small shared entry-pool parser plus a shared merge/normalization function, rather than one giant conditional loader.

**Verify**: `python -c "from nba_optimizer import utils; print('utils import ok')"` → prints `utils import ok`

### Step 2: Extract the shared parsing and merge logic

Move the common pieces into `utils.py` or a dedicated loader module. Make the API explicit enough that:

- engine can request the generation-ready loader behavior
- late swap can request the late-swap variant, including retaining unmatched current-lineup players when projections are missing
- ranker can get merged player context without importing from `engine.py`

Name the helpers clearly. Favor 2–3 small functions over one function with many boolean flags if that keeps the contract readable.

**Verify**: `python -c "from nba_optimizer import engine, late_swapper, ranker, utils"` → exit 0

### Step 3: Switch each stage to the shared loader

Update `engine.py`, `late_swapper.py`, and `ranker.py` to call the shared helper(s). Remove the duplicated stage-local `load_data()` functions if they become thin wrappers with no extra value.

If you keep wrapper functions for stage readability, make them tiny delegators to the shared loader so there is only one source of truth for parsing and merge semantics.

**Verify**: `python -m pytest -q` → exit 0

### Step 4: Add regression coverage for the loader contract

Extend the tests introduced in plan 001 so the shared loader behavior is proven explicitly. Cover both the engine-style and late-swap-style cases:

- a player present in DKEntries and projections merges correctly
- a late-swap current player missing from projections is retained with a filled projection default if that remains the intended behavior
- derived columns like `StartTime` and `Game` are present where callers expect them

Use tiny, readable CSV fixtures or in-memory CSV strings.

**Verify**: `python -m pytest tests/test_utils.py -q` → exit 0

### Step 5: Update docs to describe the new shared loader boundary

Update `docs/codebase/ARCHITECTURE.md` and `docs/codebase/CONCERNS.md` so they no longer describe duplicate loaders as the current state. If you choose a new module name instead of `utils.py`, document that boundary in `README.md` or the architecture docs.

If you update `BACKLOG.md`, reflect the exact completion state and do not claim more refactoring than was actually done.

**Verify**: `python -m pytest -q` → exit 0

## Test plan

- Extend `tests/test_utils.py` or add a dedicated loader test file with:
  - engine-style merge behavior
  - late-swap-style merge behavior
  - derived `StartTime`/`Game` column presence
- Re-run existing constraint tests from plan 001 to ensure the solver still receives the expected columns.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0
- [ ] `python -c "from nba_optimizer import engine, late_swapper, ranker, utils"` exits 0
- [ ] `ranker.py` no longer imports `engine.load_data`
- [ ] There is one documented source of truth for player-pool loading and merge normalization
- [ ] Engine and late swap still receive the columns they need without duplicating parsing code
- [ ] Docs reflect the new boundary accurately
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- plan 001 has not landed and there is still no deterministic regression harness
- the engine and late-swap loaders turn out to need fundamentally different contracts that cannot be expressed cleanly with shared helpers
- consolidating the loader would force a broader re-architecture of `engine.py` beyond the scope of this plan
- the simulator or another in-flight branch has already introduced a new loader boundary that conflicts with this plan

## Maintenance notes

- Reviewers should look closely at merge semantics. An accidental switch from `left` to `inner` in late swap would silently drop current-lineup players.
- Keep the loader API narrow and documented. If future features need more columns, extend the shared contract deliberately instead of reintroducing stage-local parsing.
- Once this lands, future feature plans like the simulator should depend on this shared loader rather than importing engine internals.
