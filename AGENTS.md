# Project Guidelines

## Start Here

Use the codebase docs for details instead of re-discovering the repo each time:
- `docs/codebase/STACK.md`
- `docs/codebase/STRUCTURE.md`
- `docs/codebase/ARCHITECTURE.md`
- `docs/codebase/CONVENTIONS.md`
- `docs/codebase/CONCERNS.md`
- `docs/codebase/TESTING.md`
- `docs/codebase/INTEGRATIONS.md`

## Environment

This project runs on Windows with PowerShell. Use PowerShell-compatible syntax for shell commands and status line configuration, not bash/POSIX syntax.

## Architecture

This repo is a sequential file-based pipeline:
1. `scripts/run_optimizer.py` orchestrates the flow.
2. `src/nba_optimizer/engine.py` generates lineup pools.
3. `src/nba_optimizer/ranker.py` ranks lineups.
4. `src/nba_optimizer/exporter.py` writes DraftKings upload CSVs.
5. `src/nba_optimizer/exposure_report.py` prints exposure analysis.
6. `src/nba_optimizer/late_swapper.py` is the separate late-swap path.

Keep responsibilities in those modules. Do not move export, ranking, or report logic into the optimizer engine.

## Build And Run

Use these commands unless the task clearly needs something narrower:

```bash
pip install -e .
python scripts/run_optimizer.py
python scripts/run_optimizer.py --late_swap
python scripts/run_optimizer_gui.py
```

Each package module also has its own `main()` and can be run directly when needed.

**Note on GUI dependencies:** The `Gooey` and `wxPython` GUI dependencies may fail to install in headless or CI environments. If you encounter build errors for `wxPython`, you can safely ignore them — the core optimizer functionality works without the GUI. To install without GUI deps:

```bash
pip install pandas numpy PuLP highspy python-dotenv -e .
```

## Conventions

- Inside `src/nba_optimizer/`, use relative imports such as `from . import config` and `from .utils import get_latest_file`.
- In `scripts/`, import from the installed package (for example `from nba_optimizer import engine, ranker`).
- Follow existing Python naming:
  - files and functions: `snake_case`
  - constants: `UPPER_SNAKE_CASE`
  - DataFrames: `df_` prefix
  - lookup dictionaries/maps: `_dict` or `_map` suffix
- Match the existing style of simple `print()`-based progress and error reporting unless the task explicitly introduces a logging system.

## Repo-Specific Pitfalls

- Stages communicate through timestamped CSV files. Be careful with any "latest file" logic because stale outputs from a previous failed run can be picked up.
- Data loading is currently split across `engine.py` and `late_swapper.py`. If you change projection or DKEntries parsing, check both paths for parity.
- `ranker.py` currently depends on `engine.load_data()`. Avoid creating more cross-module coupling unless you are intentionally refactoring shared data loading.
- `engine.py` and `late_swapper.py` are the riskiest files to change because they are large, high-churn, and untested.

## Testing And Verification

A small deterministic pytest baseline exists (`tests/test_utils.py`, `tests/test_engine_constraints.py`), covering shared parsing helpers and core `engine.generate_single_lineup` LP constraints. `ranker.py`, `exporter.py`, `exposure_report.py`, and `late_swapper.py` remain untested — prefer targeted manual verification with real CSV inputs and output inspection for those.

Do not add generic or opaque tests just to increase coverage. New tests must be transparent, domain-relevant, and directly tied to real optimizer behavior. See `docs/codebase/TESTING.md` for details.

To verify basic code correctness after changes, run:
```bash
python -c "from nba_optimizer import engine, ranker, exporter"
python -m pytest -q
```

## Documentation

When updating project guidance, prefer linking to the existing docs in `docs/codebase/` instead of duplicating content here.

When working on a GitHub issue, check if the task is already described in `backlog.md`. If so, update the task status upon completion.

This repo uses an existing mature AGENTS.md. When refreshing docs, identify the relevant recent commits and make targeted edits rather than regenerating documentation wholesale.
