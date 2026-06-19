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
- Current state: `tests/test_utils.py`, `tests/test_engine_constraints.py`, and `tests/test_pipeline_artifacts.py` exist, covering shared parsing helpers, core LP constraints, and the explicit artifact handoff contract between pipeline stages.

### 3) Test Scope Matrix

| Scope | Covered? | Typical target | Notes |
|-------|----------|----------------|-------|
| Unit | Yes (partial) | `nba_optimizer.utils` parsing helpers (`extract_player_id`, `parse_game_time`, `read_ragged_csv`) | Deterministic, pure-function tests |
| Unit/Integration | Yes (partial) | `nba_optimizer.engine.generate_single_lineup` | Exercises the LP solve directly with `randomness=0.0` against a tiny synthetic player pool; asserts roster size, salary band, positional eligibility, and min-games constraints |
| Integration | Partial | `ranker.run()`, `exporter.run()`, `exposure_report._resolve_entries_file()` artifact handoff | Covered by `test_pipeline_artifacts.py` using synthetic temp-file fixtures. Full end-to-end pipeline (LP solve → rank → export) is not covered. |
| E2E | No (manual) | Full pipeline | Verification is done by running the pipeline with real CSV inputs and inspecting output |

### 4) Mocking and Isolation Strategy

- No mocking. Tests call the real `generate_single_lineup()` worker and the real `nba_optimizer.utils` helpers against small, explicit, hand-built data (inline DataFrames or a tiny CSV fixture in `tests/fixtures/`).
- Tests are intentionally transparent and domain-relevant per project guidance: no opaque snapshot tests or broad mock-heavy scaffolding.

### 5) Coverage and Quality Signals

- Coverage tool + threshold: None configured
- Current reported coverage: Not measured
- Known gaps: end-to-end ranking and export logic in `ranker.py` and `exporter.py` (the artifact-handoff contract is tested; the scoring/formatting logic is not). `exposure_report.py` report generation and `late_swapper.py` are fully untested. Manual CSV-based verification is still required for real-slate behavior and these untested paths.

### 6) Evidence

- `tests/test_utils.py`, `tests/test_engine_constraints.py`, `tests/fixtures/ragged_sample.csv`
- `pyproject.toml`: `[project.optional-dependencies].dev` adds `pytest`
- Git churn output (scan): `tests/test_late_swapper.py` appears in high-churn list but no longer exists
- Commit `f0498b1`: "chore: remove deprecated test data and scripts"
