# Plan 004: Consolidate player-pool loading into a shared utility

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 2b9b262..HEAD -- src/nba_optimizer/engine.py src/nba_optimizer/late_swapper.py src/nba_optimizer/ranker.py src/nba_optimizer/utils.py README.md docs/codebase/ARCHITECTURE.md docs/codebase/CONCERNS.md BACKLOG.md`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/001-establish-verification-baseline.md`
- **Category**: tech-debt
- **Planned at**: commit `2b9b262`, 2026-06-23 (refreshed from `d6cbd5f` — see reconcile note below)
- **Issue**: https://github.com/JonnyRank/nba-dfs-optimizer/issues/43

## Why this matters

The codebase currently has two different player-pool loading implementations: one in `engine.py` and one in `late_swapper.py`. They parse the same DraftKings/projections inputs differently, merge with different semantics (`inner` vs `left`), and compute different derived columns. On top of that, `ranker.py` reaches into `engine.py` to reuse its loader, which couples ranking to engine internals. This plan creates a single shared loading utility with explicit modes so future fixes land once and every stage consumes the same documented data contract.

## Current state

Relevant files and their current roles:

- `src/nba_optimizer/engine.py` — loads DK entries + projections for full generation (inner merge).
- `src/nba_optimizer/late_swapper.py` — separately loads DK entries + projections for late-swap (left merge, uses `_attach_game_column` for canonical game keys that survive "In Progress" relabeling).
- `src/nba_optimizer/ranker.py` — imports `engine.load_data` directly to get merged player context; this is the primary coupling to fix.
- `src/nba_optimizer/utils.py` — owns shared parsing helpers (`extract_player_id`, `parse_game_time`, `read_ragged_csv`, `derive_game_key`) and is the natural home for a shared loader.

**Important: the two loaders diverge intentionally.** `engine.load_data` uses a simple `Game Info` string split for game keys (pre-lock games always have real matchup strings). `late_swapper.load_data` uses `derive_game_key` via `_attach_game_column` because post-lock, DraftKings replaces matchup strings with "In Progress". This divergence is documented in `engine.py:52-56` and must be preserved in any shared loader design.

Current-state excerpts (as of commit `2b9b262`):

- `src/nba_optimizer/engine.py:23-57`

  ```py
  def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
      df_raw = pd.read_csv(entries_file, skiprows=7)
      ...
      df = pd.merge(df_players, df_projs, on="ID", how="inner")
      ...
      # The pre-lock pipeline always has real matchup strings here (no "In
      # Progress" games), so the raw split is sufficient. This intentionally
      # diverges from late_swapper.load_data, which must use derive_game_key to
      # recover started games from the team/opponent pair.
      df["Game"] = df["Game Info"].str.split(" ").str[0]
      return df
  ```

- `src/nba_optimizer/late_swapper.py:57-84`

  ```py
  def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
      """Loads player pool and projections."""
      with open(entries_file, "r") as f:
          lines = f.readlines()
      ...
      df_raw = pd.read_csv(io.StringIO("".join(lines[player_pool_start_idx:])))
      df_players = df_raw.dropna(subset=["ID"])
      df_players["ID"] = df_players["ID"].astype(str).str.split(".").str[0]
      df = pd.merge(df_players, df_projs, on="ID", how="left")
      df["Projection"] = pd.to_numeric(df["Projection"]).fillna(0)
      df["Salary"] = pd.to_numeric(df["Salary"])
      _attach_game_column(df)
      return df
  ```

- `src/nba_optimizer/ranker.py:14-25`

  ```py
  def load_data(lineup_file: str, projs_file: str, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
      """Loads lineups and player data (projections/ownership)."""
      df_lineups = pd.read_csv(lineup_file)
      df_projs = pd.read_csv(projs_file)
      df_projs["ID"] = df_projs["ID"].astype(str)
      # Import the engine's merge logic to get full player context
      from .engine import load_data as engine_load_data
      df_players = engine_load_data(projs_file, cfg.entries_path)
      return df_lineups, df_players
  ```

- `src/nba_optimizer/utils.py:8-111` already contains `get_latest_file`, `extract_player_id`, `is_player_locked`, `parse_game_time`, `derive_game_key`, and `read_ragged_csv`. The `derive_game_key` function (added in commit `2b9b262`, lines 58-84) is already the shared game-key logic; it is the right abstraction for any shared loader's game column attachment. `read_ragged_csv` is at lines 87-111.

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

- plan 001 has not landed (it has, as of `2b9b262`: 27 tests pass — but verify before starting)
- consolidating the loader would force a broader re-architecture of `engine.py` beyond the scope of this plan
- the shared loader cannot cleanly express both the `inner` (engine) and `left` (late-swap) merge modes, with the `derive_game_key`-based game column for late-swap and the simple string-split for engine — these divergences are intentional and must be preserved, not unified
- any in-flight branch has introduced a new loader boundary that conflicts with this plan

## Reconcile note (2026-06-23)

This plan was refreshed from commit `d6cbd5f` to `2b9b262`. The core finding is unchanged: `ranker.py` still imports `engine.load_data` directly (line 21). Since the original plan was written, commit `2b9b262` significantly changed `late_swapper.py` (added `_attach_game_column`, `derive_game_key`, late-swap game-key logic) and added `derive_game_key` to `utils.py`. The key implication for this plan: the shared loader must support two modes (pre-lock engine style, post-lock late-swap style) because the divergence is now documented as intentional rather than accidental drift. The `derive_game_key` helper in `utils.py` is already the shared abstraction for the late-swap mode's game column — use it.

## Maintenance notes

- Reviewers should look closely at merge semantics. An accidental switch from `left` to `inner` in late swap would silently drop current-lineup players.
- Keep the loader API narrow and documented. If future features need more columns, extend the shared contract deliberately instead of reintroducing stage-local parsing.
- Once this lands, future feature plans like the simulator should depend on this shared loader rather than importing engine internals.
