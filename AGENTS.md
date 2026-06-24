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
1. `scripts/run_optimizer.py` → `cli.py` → `src/nba_optimizer/orchestrator.py` drives the flow, passing each stage's output file path directly to the next stage (explicit artifact handoff).
2. `src/nba_optimizer/engine.py` generates lineup pools.
3. `src/nba_optimizer/ranker.py` ranks lineups.
4. `src/nba_optimizer/exporter.py` writes DraftKings upload CSVs.
5. `src/nba_optimizer/exposure_report.py` prints exposure analysis.
6. `src/nba_optimizer/late_swapper.py` is the separate late-swap path.
7. `src/nba_optimizer/utils.py` holds the shared player-pool loader (`parse_dk_entries`, `merge_player_pool`) plus file/parsing helpers used across stages.

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

**GUI dependencies are optional.** Core install (`pip install -e .`) is clean in headless and CI environments. To include the GUI:

```bash
pip install -e .[gui]
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

- Stages communicate through timestamped CSV files. The orchestrator now passes each stage's output path explicitly to the next stage, so stale outputs cannot be silently picked up on the orchestrated path. Standalone module invocations (`python -m nba_optimizer.<module>`) still fall back to "latest file" lookup, so beware stale outputs from a failed run there.
- Player-pool loading is consolidated in `utils.parse_dk_entries` and `utils.merge_player_pool`; engine, ranker, and late_swapper all share it (plan 004). Engine and ranker merge with `how="inner"`; late_swapper merges with `how="left"` and derives the canonical `Game` column via `derive_game_key`. If you change projection or DKEntries parsing, that single path covers every stage — but confirm both merge modes still behave.
- `engine.py` and `late_swapper.py` are the riskiest files to change because they are large and high-churn (`late_swapper.py` now has targeted tests; engine's LP constraints are covered, but its data/slotting plumbing is not).

## Testing And Verification

A deterministic pytest baseline exists:
- `tests/test_utils.py` — shared parsing/loader helpers (`parse_dk_entries`, `merge_player_pool`, etc.).
- `tests/test_engine_constraints.py` — core `engine.generate_single_lineup` LP constraints (roster size, salary band, positional eligibility, `min_games`).
- `tests/test_late_swap.py` — late-swap game-key resolution, lock detection, and enforced `min_games`.
- `tests/test_pipeline_artifacts.py` — explicit artifact handoff between stages (ranker/exporter/exposure_report honor passed-in paths over "latest file").

The core ranking/export/leverage logic in `ranker.py`, `exporter.py`, and `exposure_report.py` remains otherwise untested — prefer targeted manual verification with real CSV inputs and output inspection for those.

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
