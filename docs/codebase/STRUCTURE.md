# Codebase Structure

## Core Sections (Required)

### 1) Top-Level Map

| Path | Purpose | Evidence |
|------|---------|----------|
| `src/nba_optimizer/` | Core package: engine, ranker, exporter, late swapper, config, utilities | All `.py` files in directory |
| `scripts/` | Entry point scripts (CLI orchestrator, GUI launchers) | `run_optimizer.py`, `run_optimizer_gui.py` |
| `deprecated/` | Archived code no longer in active use | `late_swapper_deprecated.py` |
| `example_projs/` | Sample projection CSV for reference | `NBA-Projs-2026-02-11_153604.csv` |
| `docs/codebase/` | Auto-generated codebase documentation | This file |
| `tests/` | Deterministic pytest baseline (utils, engine constraints, pipeline artifact handoff, nightly capture) and small CSV fixtures | `tests/test_utils.py`, `tests/test_engine_constraints.py`, `tests/test_pipeline_artifacts.py`, `tests/test_capture.py`, `tests/fixtures/` (incl. trimmed 2026-10-20 opening-night files) |
| `.claude/skills/` | Project-level Claude Code skills (e.g. codebase audit/improve workflow) | `.claude/skills/improve/SKILL.md` |

### 2) Entry Points

- **Main runtime entry:** `nba-dfs-optimizer` console script (`nba_optimizer.cli:main`) with `scripts/run_optimizer.py` as a thin wrapper
- **Capture entry:** `nba-dfs-capture` console script (`nba_optimizer.capture:main`) with `finalize` and `record` subcommands
- **GUI entry:** `nba-dfs-optimizer-gui` console script (`nba_optimizer.gui:main`) with `scripts/run_optimizer_gui.py` as a thin wrapper
- **How entry is selected:** User runs console scripts after `pip install -e .`, or runs wrapper scripts directly.
- **Standalone modules:** Each module in `src/nba_optimizer/` (`engine.py`, `ranker.py`, `exporter.py`, `exposure_report.py`, `late_swapper.py`) has its own `main()` with `argparse` and can be run independently.

### 3) Module Boundaries

| Boundary | What belongs here | What must not be here |
|----------|-------------------|------------------------|
| `src/nba_optimizer/engine.py` | Lineup generation, LP solving, parallel execution, time-based slotting | Ranking logic, CSV export formatting |
| `src/nba_optimizer/ranker.py` | Scoring lineups by weighted rank metrics | Lineup generation, file export |
| `src/nba_optimizer/assembler.py` | Choosing the night's N entries from a ranked pool under exposure caps | Ranking, export |
| `src/nba_optimizer/overrides.py` | Typed player settings: `NAME=VALUE`, player lookup, projection/ownership overrides | Ranking |
| `src/nba_optimizer/settings.py` | `--from/--to` stage order and typed/inherited/default settings | Running stages |
| `src/nba_optimizer/exporter.py` | Mapping an assembly (or ranked lineups) into DraftKings CSV template | Ranking, optimization |
| `src/nba_optimizer/exposure_report.py` | Analyzing exported lineups for player exposure vs. ownership | Optimization, ranking |
| `src/nba_optimizer/late_swapper.py` | Re-optimizing unlocked roster slots post-lock | Full lineup generation |
| `src/nba_optimizer/config.py` | Constants (salary cap, roster size) and env-var path loading | Business logic |
| `src/nba_optimizer/utils.py` | Shared utilities: file lookup, ID extraction, CSV parsing, time parsing | Module-specific logic |
| `src/nba_optimizer/slate.py` | Slate facts, `slate.json`, lock numbering, slate-folder lookup | Optimization |
| `src/nba_optimizer/records.py` | Run records, entry sets, file classification, blend check, copy helpers | Optimization, ranking |
| `src/nba_optimizer/capture.py` | `nba-dfs-capture` CLI: nightly finalize and manual record | Lineup generation |
| `scripts/` | Orchestration, argument parsing, user-facing entry points | Core optimization logic |

### 4) Naming and Organization Rules

- File naming pattern: `snake_case` (e.g., `late_swapper.py`, `exposure_report.py`)
- Directory organization pattern: Layer-based (`src/` for library, `scripts/` for entry points)
- Import convention: Scripts import from installed package modules (`from nba_optimizer import ...`). Internal package modules use relative imports (`from . import config`, `from .utils import ...`).

### 5) Evidence

- Scan output directory tree
- `scripts/run_optimizer.py` (thin wrapper importing `nba_optimizer.cli:main`)
- `src/nba_optimizer/orchestrator.py` (shared orchestration flow for CLI and GUI)
- `pyproject.toml` (`[project.scripts]` console-script entrypoints)
- `src/nba_optimizer/__init__.py` (empty, marks package)
