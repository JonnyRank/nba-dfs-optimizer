# Testing Patterns

## Core Sections (Required)

### 1) Test Stack and Commands

- Primary test framework: `pytest` (dev-only, via `pip install -e .[dev]`)
- Assertion/mocking tools: plain `pytest` asserts; no mocking framework
- Commands:

```bash
# Install core + dev dependencies
pip install -e .[dev]

# Run the full suite
python -m pytest -q

# Run a focused subset (utility helpers + engine constraints)
python -m pytest tests/test_engine_constraints.py tests/test_utils.py -q
```

### 2) Test Layout

- Test file placement pattern: `tests/` at the repo root, mirroring the `src/nba_optimizer/` module names (`tests/test_utils.py`, `tests/test_engine_constraints.py`). Small CSV fixtures live in `tests/fixtures/`.
- History note: an earlier `tests/` directory (`tests/test_late_swapper.py`, `tests/test_data/DKEntries.csv`) was removed in commit `f0498b1` ("chore: remove deprecated test data and scripts"). The current suite is a fresh, intentionally minimal baseline rather than a restoration of that code.
- Current state: `tests/test_utils.py` and `tests/test_engine_constraints.py` exist, covering shared parsing helpers and core LP constraints.

### 3) Test Scope Matrix

| Scope | Covered? | Typical target | Notes |
|-------|----------|----------------|-------|
| Unit | Yes (partial) | `nba_optimizer.utils` parsing helpers (`extract_player_id`, `parse_game_time`, `read_ragged_csv`) | Deterministic, pure-function tests |
| Unit/Integration | Yes (partial) | `nba_optimizer.engine.generate_single_lineup` | Exercises the LP solve directly with `randomness=0.0` against a tiny synthetic player pool; asserts roster size, salary band, positional eligibility, and min-games constraints |
| Integration | No | Full `engine` -> `ranker` -> `exporter` -> `exposure_report` pipeline | Not covered; would require real DraftKings CSV fixtures |
| E2E | No (manual) | Full pipeline | Verification is done by running the pipeline with real CSV inputs and inspecting output |

### 4) Mocking and Isolation Strategy

- No mocking. Tests call the real `generate_single_lineup()` worker and the real `nba_optimizer.utils` helpers against small, explicit, hand-built data (inline DataFrames or a tiny CSV fixture in `tests/fixtures/`).
- Tests are intentionally transparent and domain-relevant per project guidance: no opaque snapshot tests or broad mock-heavy scaffolding.

### 5) Coverage and Quality Signals

- Coverage tool + threshold: None configured
- Current reported coverage: Not measured
- Known gaps: `ranker.py`, `exporter.py`, `exposure_report.py`, and `late_swapper.py` have no automated tests. The new suite is a baseline for `engine.py`'s core constraint logic and shared `utils.py` helpers only; manual CSV-based verification is still required for real-slate behavior and the rest of the pipeline.

### 6) Evidence

- `tests/test_utils.py`, `tests/test_engine_constraints.py`, `tests/fixtures/ragged_sample.csv`
- `pyproject.toml`: `[project.optional-dependencies].dev` adds `pytest`
- Git churn output (scan): `tests/test_late_swapper.py` appears in high-churn list but no longer exists
- Commit `f0498b1`: "chore: remove deprecated test data and scripts"
