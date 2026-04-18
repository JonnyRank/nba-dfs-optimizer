# Codebase Structure

## Core Sections (Required)

### 1) Top-Level Map

| Path | Purpose | Evidence |
|------|---------|----------|
| `src/nba_optimizer/` | Core package: engine, ranker, exporter, late swapper, config, utilities | All `.py` files in directory |
| `scripts/` | Entry point scripts (CLI orchestrator, GUI launchers) | `run_optimizer.py`, `run_optimizer_gui.py` |
| `design_docs/` | Project plan, data loader spec, standardization instructions | `project_plan.md`, `implement_data_loader.md` |
| `deprecated/` | Archived code no longer in active use | `late_swapper_deprecated.py` |
| `example_projs/` | Sample projection CSV for reference | `NBA-Projs-2026-02-11_153604.csv` |
| `docs/codebase/` | Auto-generated codebase documentation | This file |

### 2) Entry Points

- **Main runtime entry:** `scripts/run_optimizer.py` — CLI orchestrator that runs all 4 pipeline phases sequentially
- **GUI entry:** `scripts/run_optimizer_gui.py` — Gooey-wrapped GUI version of the orchestrator
- **How entry is selected:** User runs a script directly. Scripts add project root to `sys.path` and import from `src.nba_optimizer`.
- **Standalone modules:** Each module in `src/nba_optimizer/` (`engine.py`, `ranker.py`, `exporter.py`, `exposure_report.py`, `late_swapper.py`) has its own `main()` with `argparse` and can be run independently.

### 3) Module Boundaries

| Boundary | What belongs here | What must not be here |
|----------|-------------------|------------------------|
| `src/nba_optimizer/engine.py` | Lineup generation, LP solving, parallel execution, time-based slotting | Ranking logic, CSV export formatting |
| `src/nba_optimizer/ranker.py` | Scoring lineups by weighted rank metrics | Lineup generation, file export |
| `src/nba_optimizer/exporter.py` | Mapping ranked lineups into DraftKings CSV template | Ranking, optimization |
| `src/nba_optimizer/exposure_report.py` | Analyzing exported lineups for player exposure vs. ownership | Optimization, ranking |
| `src/nba_optimizer/late_swapper.py` | Re-optimizing unlocked roster slots post-lock | Full lineup generation |
| `src/nba_optimizer/config.py` | Constants (salary cap, roster size) and env-var path loading | Business logic |
| `src/nba_optimizer/utils.py` | Shared utilities: file lookup, ID extraction, CSV parsing, time parsing | Module-specific logic |
| `scripts/` | Orchestration, argument parsing, user-facing entry points | Core optimization logic |

### 4) Naming and Organization Rules

- File naming pattern: `snake_case` (e.g., `late_swapper.py`, `exposure_report.py`)
- Directory organization pattern: Layer-based (`src/` for library, `scripts/` for entry points)
- Import convention: Scripts use `sys.path.insert` to add project root, then `from src.nba_optimizer import ...`. Internal package modules use relative imports (`from . import config`, `from .utils import ...`).

### 5) Evidence

- Scan output directory tree
- `scripts/run_optimizer.py` (sys.path manipulation and imports)
- `src/nba_optimizer/__init__.py` (empty, marks package)
