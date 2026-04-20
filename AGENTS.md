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

There is no formal automated test suite. Prefer targeted manual verification with real CSV inputs and output inspection.

Do not add generic or opaque tests just to increase coverage. If you add tests in the future, they must be transparent, domain-relevant, and directly tied to real optimizer behavior.

## Documentation

When updating project guidance, prefer linking to the existing docs in `docs/codebase/` instead of duplicating content here.

When working on a GitHub issue, check if the task is already described in `backlog.md`. If so, update the task status upon completion.
