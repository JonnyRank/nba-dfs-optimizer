# Coding Conventions

## Core Sections (Required)

### 1) Naming Rules

| Item | Rule | Example | Evidence |
|------|------|---------|----------|
| Files | `snake_case.py` | `late_swapper.py`, `exposure_report.py` | All files in `src/nba_optimizer/` |
| Functions/methods | `snake_case` | `generate_single_lineup()`, `slot_lineup_by_time()`, `rank_lineups()` | `engine.py`, `ranker.py` |
| Classes | `PascalCase` | `Config` | `config.py` |
| Module-level constants | `UPPER_SNAKE_CASE` | `ROSTER_SLOTS`, `ENTRY_HEADER_COLS`, `STANDARD_EXPORT_PREFIX`, `LATE_SWAP_PREFIX` | `config.py` |
| Constants (within Config dataclass) | `snake_case` attributes | `salary_cap`, `roster_size`, `min_projection` | `config.py` |
| Local variables | `snake_case` | `df_players`, `projs_file`, `min_salary` | All modules |
| DataFrame variables | `df_` prefix | `df_raw`, `df_projs`, `df_ranked`, `df_entries` | `engine.py`, `ranker.py`, `exporter.py` |
| Dictionary lookup vars | `_dict` suffix | `salary_dict`, `pos_dict`, `own_map`, `proj_map` | `engine.py`, `ranker.py` |
| Config instances | `cfg` or `config` | `cfg: Config` parameter | All modules' `run()` functions |

### 2) Formatting and Linting

- Formatter: None configured
- Linter: None configured
- Code style observed: Generally follows PEP 8 with ~88-100 character line lengths. No enforced rules.
- Run commands: N/A

### 3) Import and Module Conventions

- Import grouping/order: stdlib → third-party (`pandas`, `numpy`, `pulp`) → local (`from .config import Config`, `from .utils import get_latest_file`)
- Within-package imports: Relative (`from .config import Config`, `from .utils import get_latest_file`)
- Script-level imports: Absolute package imports (`from nba_optimizer import engine, ranker`)
- No barrel exports; `__init__.py` is empty
- Configuration: Use dependency injection pattern - modules accept `Config` instance as parameter, initialized via `load_config_from_env()` in orchestrator/main functions

### 4) Error and Logging Conventions

- Error strategy: `try/except` at the `run()` function level in every module. Errors are caught, printed with `print(f"Error: {e}")`, and `traceback.print_exc()` is called. No exceptions propagate to callers.
- Logging: All output uses `print()` statements. No logging framework is used.
- Progress reporting: Percentage-based progress printed at 20% intervals during engine generation (`Lineups generated: X%`).
- Sensitive-data redaction: Not applicable (no secrets in runtime data).

### 5) Testing Conventions

- A small deterministic pytest baseline exists: `tests/test_utils.py` and `tests/test_engine_constraints.py`, covering shared parsing helpers and core `engine.generate_single_lineup` LP constraints (see `docs/codebase/TESTING.md`). Git history also shows earlier deleted test files (`tests/test_late_swapper.py`, `tests/test_data/DKEntries.csv`) that were removed; the current suite is a fresh baseline, not a restoration.
- `ranker.py`, `exporter.py`, `exposure_report.py`, and `late_swapper.py` remain untested. Verification for those is manual: run the pipeline and inspect generated CSVs.

### 6) Evidence

- `src/nba_optimizer/config.py` (naming, constants)
- `src/nba_optimizer/engine.py` (import order, function naming, error handling)
- `src/nba_optimizer/utils.py` (type hints, function signatures)
- `.gitignore` (lists removed test files in churn history)
