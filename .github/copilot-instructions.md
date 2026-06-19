# Copilot Cloud Agent Instructions

## Quick Orientation

This is a **Python NBA DFS (Daily Fantasy Sports) lineup optimizer** for DraftKings. It is a single-user, locally-run CLI tool — no web server, no API, no database. The codebase is small (~11 source files) but domain-specific.

**Before exploring the code yourself, read the existing documentation:**

- `docs/codebase/STACK.md` — runtime, dependencies, key commands
- `docs/codebase/STRUCTURE.md` — file layout, entry points, module boundaries
- `docs/codebase/ARCHITECTURE.md` — pipeline flow, module responsibilities, reused patterns
- `docs/codebase/CONVENTIONS.md` — naming rules, import style, error handling
- `docs/codebase/CONCERNS.md` — known risks, tech debt, fragile areas
- `docs/codebase/TESTING.md` — testing status (no automated tests exist)
- `docs/codebase/INTEGRATIONS.md` — external systems (all file-based CSV exchange)
- `AGENTS.md` — agent-specific project guidelines (also embedded in custom instructions)
- `BACKLOG.md` — current task backlog with status and LLM-ready instructions

These docs are maintained and accurate. Use them instead of re-discovering the repo from scratch.

## Setup and Build

```bash
# Core CLI install (no GUI dependencies)
pip install -e .

# Install with GUI support (requires a display; will fail in headless environments)
pip install -e .[gui]
```

This installs the `nba-dfs-optimizer` package in editable mode. There is no separate build step. GUI dependencies (`Gooey`, `wxPython`) are optional extras and are not required for the core optimizer functionality.

## Running the Pipeline

The optimizer requires two input CSV files that are **not included in the repo** (they are user-specific DraftKings downloads):
- `DKEntries.csv` — player pool with salaries, positions, game info
- `NBA-Projs-*.csv` — projection data with ownership percentages

Paths are configured via `.env` (see `.env.example`). Without real input files, the pipeline will fail at data loading — this is expected.

```bash
# Full pipeline
python scripts/run_optimizer.py

# Late swap mode
python scripts/run_optimizer.py --late_swap

# GUI (requires wxPython — will fail in headless environments)
python scripts/run_optimizer_gui.py
```

## Architecture — The 60-Second Version

Sequential file-based pipeline. Each stage reads the previous stage's timestamped CSV output:

```
DKEntries.csv + NBA-Projs-*.csv
    → engine.py      (parallel LP solve → lineup-pool-{timestamp}.csv)
    → ranker.py       (weighted scoring → ranked-lineups-{timestamp}.csv)
    → exporter.py     (DK template fill → upload-ready-DKEntries-{timestamp}.csv)
    → exposure_report.py (console analytics)
```

Late swap is a separate path: `late_swapper.py` → `late-swap-entries-{timestamp}.csv`

Orchestration lives in `src/nba_optimizer/orchestrator.py`, called by thin wrappers in `scripts/`.

## Module Boundaries — What Goes Where

| Module | Owns | Must NOT own |
|--------|------|-------------|
| `engine.py` | LP model, parallel solving, slot optimization | Ranking, export |
| `ranker.py` | Lineup scoring, weighted rank calculation | Lineup generation, file export |
| `exporter.py` | DK template parsing, lineup-to-entry mapping | Scoring, optimization |
| `exposure_report.py` | Post-export analytics, leverage calculation | Everything else |
| `late_swapper.py` | Lock detection, constrained re-optimization | Full lineup generation |
| `config.py` | Configuration dataclass, env var loading | Business logic |
| `utils.py` | File discovery, ID/time parsing, CSV reading | Module-specific logic |
| `orchestrator.py` | Pipeline orchestration, Config injection | Core optimization logic |

**Do not move export, ranking, or report logic into the optimizer engine.**

## Coding Conventions

- **Imports:** Inside `src/nba_optimizer/`, use relative imports (`from . import config`, `from .utils import get_latest_file`). In `scripts/`, use absolute package imports (`from nba_optimizer import engine`).
- **Naming:** `snake_case` for files/functions, `UPPER_SNAKE_CASE` for constants, `df_` prefix for DataFrames, `_dict`/`_map` suffix for lookup dictionaries.
- **Error handling:** `try/except` at `run()` level with `print()` + `traceback.print_exc()`. No logging framework.
- **Output:** Simple `print()` statements for progress. Do not introduce a logging framework unless the task explicitly requires it.
- **Config injection:** All module `run()` functions accept a `Config` instance. Use `dataclasses.replace()` for overrides.

## Critical Pitfalls

1. **Stale file pickup:** Stages find inputs via "latest file by timestamp" heuristic. A failed run leaves partial outputs that the next stage may incorrectly pick up. Be careful with any file-discovery logic.

2. **Duplicate data loading:** `engine.py` and `late_swapper.py` each have their own `load_data()` with subtly different CSV parsing. If you change projection or DKEntries parsing, **check both files for parity**.

3. **Cross-module coupling:** `ranker.py` imports `engine.load_data()`. Avoid creating more cross-module dependencies unless intentionally refactoring shared data loading.

4. **High-risk files:** `engine.py` and `late_swapper.py` are the largest, highest-churn, and completely untested files. Make changes to these carefully and verify outputs manually.

5. **No automated tests:** There is no test suite. Verification is manual (run pipeline, inspect CSV output). Do not add generic or opaque tests — any future tests must be transparent, domain-relevant, and tied to real optimizer behavior.

## Testing and Verification

There are no linters, formatters, or test runners configured. To verify changes:

1. Check that `pip install -e .` succeeds
2. Verify Python syntax: `python -c "from nba_optimizer import engine, ranker, exporter"`
3. For logic changes, the only real verification is running the pipeline with actual DraftKings CSV inputs and inspecting the output — these inputs are not in the repo

## Documentation Updates

When making code changes, check if documentation needs updating:
- `README.md` for user-facing changes (new flags, features, setup changes)
- `docs/codebase/` files for architectural or convention changes
- `BACKLOG.md` if completing a tracked task

Prefer linking to existing docs in `docs/codebase/` instead of duplicating content.

## Environment Notes for Cloud Agents

- **No CI/CD pipelines exist** — there are no GitHub Actions workflows to check
- **No secrets or credentials** — `.env` contains only local file paths
- **Windows-primary development** — the owner develops on Windows, but the code is cross-platform Python
- **No database** — all data exchange is via CSV files on the local filesystem
- **GUI dependencies are optional** — `Gooey` and `wxPython` are only needed for `pip install -e .[gui]`; the core `pip install -e .` is clean in headless/Linux environments
