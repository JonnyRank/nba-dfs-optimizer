# Coding Conventions

## Core Sections (Required)

### 1) Naming Rules

| Item | Rule | Example | Evidence |
|------|------|---------|----------|
| Files | `snake_case.py` | `late_swapper.py`, `exposure_report.py` | All files in `src/nba_optimizer/` |
| Functions/methods | `snake_case` | `generate_single_lineup()`, `slot_lineup_by_time()`, `rank_lineups()` | `engine.py`, `ranker.py` |
| Constants | `UPPER_SNAKE_CASE` | `SALARY_CAP`, `ROSTER_SIZE`, `LINEUP_POOL_DIR` | `config.py` |
| Local variables | `snake_case` | `df_players`, `projs_file`, `min_salary` | All modules |
| DataFrame variables | `df_` prefix | `df_raw`, `df_projs`, `df_ranked`, `df_entries` | `engine.py`, `ranker.py`, `exporter.py` |
| Dictionary lookup vars | `_dict` suffix | `salary_dict`, `pos_dict`, `own_map`, `proj_map` | `engine.py`, `ranker.py` |

### 2) Formatting and Linting

- Formatter: None configured
- Linter: None configured
- Code style observed: Generally follows PEP 8 with ~88-100 character line lengths. No enforced rules.
- Run commands: N/A

### 3) Import and Module Conventions

- Import grouping/order: stdlib → third-party (`pandas`, `numpy`, `pulp`) → local (`config`, `utils`)
- Within-package imports: Relative (`from . import config`, `from .utils import get_latest_file`)
- Script-level imports: Absolute with `sys.path` manipulation (`from src.nba_optimizer import engine, ranker`)
- No barrel exports; `__init__.py` is empty

### 4) Error and Logging Conventions

- Error strategy: `try/except` at the `run()` function level in every module. Errors are caught, printed with `print(f"Error: {e}")`, and `traceback.print_exc()` is called. No exceptions propagate to callers.
- Logging: All output uses `print()` statements. No logging framework is used.
- Progress reporting: Percentage-based progress printed at 20% intervals during engine generation (`Lineups generated: X%`).
- Sensitive-data redaction: Not applicable (no secrets in runtime data).

### 5) Testing Conventions

- No formal test suite exists. Git history shows deleted test files (`tests/test_late_swapper.py`, `tests/test_data/DKEntries.csv`) that were removed.
- Verification is manual: run the pipeline and inspect generated CSVs.

### 6) Evidence

- `src/nba_optimizer/config.py` (naming, constants)
- `src/nba_optimizer/engine.py` (import order, function naming, error handling)
- `src/nba_optimizer/utils.py` (type hints, function signatures)
- `.gitignore` (lists removed test files in churn history)
