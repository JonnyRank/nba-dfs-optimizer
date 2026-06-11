# Plan 001: Establish a deterministic verification baseline for core optimizer logic

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat d6cbd5f..HEAD -- pyproject.toml README.md docs/codebase/TESTING.md docs/codebase/STACK.md docs/codebase/CONCERNS.md tests`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `d6cbd5f`, 2026-06-11
- **Issue**: https://github.com/JonnyRank/nba-dfs-optimizer/issues/40

## Why this matters

The repository currently has no automated test runner, no test files, and no one-command way to tell whether a refactor of the optimizer core preserved behavior. That makes every change to `engine.py`, `ranker.py`, and `late_swapper.py` rely on manual CSV inspection with user-local inputs. This plan creates the minimum transparent verification baseline the repo is missing: deterministic fixture-backed tests for core helper behavior and optimizer constraints, plus contributor documentation for how to run them.

## Current state

Relevant files and their current roles:

- `docs/codebase/TESTING.md` — canonical repo note on testing; currently says there is no test stack.
- `.github/copilot-instructions.md` — current verification guidance for agents.
- `pyproject.toml` — package metadata; currently has no dev/test dependency group.
- `src/nba_optimizer/engine.py` — contains the LP worker logic that most future refactors will touch.
- `src/nba_optimizer/utils.py` — shared CSV and parsing helpers with deterministic behaviors that are cheap to test.

Current-state excerpts:

- `docs/codebase/TESTING.md:5-25`

  ```md
  - Primary test framework: None configured
  - Assertion/mocking tools: None configured
  - Commands: N/A
  ...
  - Current state: No test files exist in the repository.
  ```

- `.github/copilot-instructions.md:104-114`

  ```md
  1. Check that `pip install -e .` succeeds
  2. Verify Python syntax: `python -c "from nba_optimizer import engine, ranker, exporter"`
  3. For logic changes, the only real verification is running the pipeline with actual DraftKings CSV inputs and inspecting the output
  ```

- `src/nba_optimizer/engine.py:55-123` defines `generate_single_lineup(...)`, the solver worker used by the engine, and `src/nba_optimizer/utils.py:8-77` defines deterministic helpers like `extract_player_id`, `parse_game_time`, and `read_ragged_csv`.

Repo conventions to follow:

- Use `snake_case` names, `df_` prefixes for DataFrames, and relative imports inside `src/nba_optimizer/`; see `docs/codebase/CONVENTIONS.md:5-33`.
- Tests in this repo must be transparent and domain-relevant. Do not add opaque snapshot tests or broad mock-heavy scaffolding; the project guidance explicitly rejects generic tests and values behavior-focused coverage.
- Keep `print()`-based runtime behavior untouched unless a test needs a narrow assertion on a returned value.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install core + test tools | `pip install -e .[dev]` | exit 0 |
| Import smoke | `python -c "from nba_optimizer import engine, ranker, exporter, late_swapper, utils"` | exit 0 |
| Run full test suite | `python -m pytest -q` | exit 0; all tests pass |
| Run focused engine/util tests | `python -m pytest tests/test_engine_constraints.py tests/test_utils.py -q` | exit 0; all targeted tests pass |

## Scope

**In scope**:

- `pyproject.toml`
- `tests/test_engine_constraints.py` (new)
- `tests/test_utils.py` (new)
- `tests/fixtures/` (new lightweight CSV fixtures only if code-based fixtures become too noisy)
- `README.md`
- `docs/codebase/TESTING.md`
- `docs/codebase/STACK.md`
- `docs/codebase/CONCERNS.md`
- `BACKLOG.md` (only if you want to mark the testing task complete after implementation)

**Out of scope**:

- GUI tests
- orchestrator / CLI argument parsing tests
- end-to-end tests that require real DraftKings downloads
- performance benchmarking
- changing runtime solver behavior beyond what is needed to make deterministic tests possible

## Git workflow

- Branch: `advisor/001-verification-baseline`
- Commit per logical unit using the repo’s observed conventional style, for example: `test: add deterministic optimizer smoke tests`
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Add a minimal test tool entry point

Update `pyproject.toml` to define a small dev-only dependency group for test execution. Prefer `[project.optional-dependencies].dev` over adding `pytest` to the runtime dependency list. Keep the core runtime install path unchanged for end users.

Also decide whether the repo needs a tiny `pytest.ini` or similar config file. Only add one if it materially reduces noise; otherwise keep the setup minimal.

**Verify**: `pip install -e .[dev]` → exit 0

### Step 2: Add deterministic utility tests

Create `tests/test_utils.py` with explicit, easy-to-read cases for:

- `extract_player_id()` parsing a normal `Name (ID)` string and a null/missing value
- `parse_game_time()` parsing a valid DK game-info string and falling back to `datetime.max` on invalid input
- `read_ragged_csv()` preserving valid columns and padding ragged rows without throwing

Use tiny inline CSV fixtures or tiny fixture files under `tests/fixtures/`. Avoid broad fixture factories.

**Verify**: `python -m pytest tests/test_utils.py -q` → exit 0

### Step 3: Add deterministic optimizer-constraint tests

Create `tests/test_engine_constraints.py` that calls `generate_single_lineup()` directly with a tiny synthetic `DataFrame`. Do not assert on exact player names unless the fixture makes only one valid lineup possible. Instead, assert on the behaviors this repo actually cares about:

- lineup size equals `cfg.roster_size`
- total salary stays within min/max bounds
- every selected player is slot-eligible for at least one of the eight DK roster slots
- selected lineup spans at least `min_games` distinct games

Set `randomness=0.0` and construct the test pool so the LP solve is deterministic or nearly deterministic. If multiple valid optimal lineups remain possible, assert on constraints rather than exact ordering.

**Verify**: `python -m pytest tests/test_engine_constraints.py -q` → exit 0

### Step 4: Document the baseline and how to use it

Update `README.md` and `docs/codebase/TESTING.md` to describe the new verification commands. Update `docs/codebase/STACK.md` to mention the new dev-only test dependency path. If you touched any task status in `BACKLOG.md`, keep that change factual and minimal.

Keep the documentation honest: manual CSV inspection still matters for real-slate behavior; the new suite is only a baseline for safe refactors.

**Verify**: `python -m pytest -q` → exit 0

## Test plan

- `tests/test_utils.py`
  - valid player ID extraction
  - missing player string handling
  - valid and invalid game-time parsing
  - ragged CSV padding and valid column preservation
- `tests/test_engine_constraints.py`
  - one test for salary + roster-size constraints
  - one test for positional eligibility + min-games behavior
- Use tiny synthetic data created inside the tests unless a CSV fixture is much clearer.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `pip install -e .[dev]` exits 0
- [ ] `python -c "from nba_optimizer import engine, ranker, exporter, late_swapper, utils"` exits 0
- [ ] `python -m pytest -q` exits 0
- [ ] The repo contains transparent tests covering utility parsing and core lineup constraints
- [ ] `README.md` and `docs/codebase/TESTING.md` document the new baseline accurately
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- the code in `engine.py` or `utils.py` has drifted enough that the excerpts above no longer describe the current behavior
- `generate_single_lineup()` cannot be exercised deterministically without a larger refactor to solver setup
- adding a dev-only dependency group unexpectedly requires a broader packaging redesign; that belongs in plan 002, not here
- the only viable tests would rely on hidden mocks or snapshot dumps rather than explicit domain assertions

## Maintenance notes

- Keep this suite small and behavior-driven. It is a safety rail for future refactors, not a coverage-maximization project.
- When later plans touch `ranker.py`, `late_swapper.py`, or new shared loaders, extend this suite by adding focused characterization tests rather than inventing a parallel test style.
- Reviewers should look for test readability first: if a human cannot understand why a fixture proves the behavior, the test is not good enough for this repo.
