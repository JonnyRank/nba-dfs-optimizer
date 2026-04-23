# NBA DFS Optimizer Code Review Style Guide

## Introduction

This style guide outlines the coding conventions for the NBA DFS Optimizer project. It is based on the project's established patterns and best practices, designed to maintain consistency and quality across the codebase.

## Key Principles

* **Simplicity First:** Avoid over-engineering. Only make changes that are directly requested or clearly necessary. Keep solutions simple and focused.
* **Surgical Modifications:** Preserve existing code structure. Make minimal necessary changes to implement features. Do not refactor untouched code.
* **Readability:** Code should be easy for all team members to understand. Prioritize clarity over cleverness.
* **Maintainability:** Code should be simple to modify and extend. Break complex operations into focused, reusable functions.
* **Consistency:** Follow established patterns in the codebase. When adding new functionality, match the style and structure of existing code.

## Architecture and Design

### Module Boundaries

The project follows a **sequential pipeline architecture** with strict module boundaries:

* **`config.py`:** Configuration dataclass, environment variable loading, directory creation. Must not contain business logic.
* **`utils.py`:** Shared utilities (file discovery, ID/time parsing, CSV reading). Must not contain optimization or ranking logic.
* **`engine.py`:** Lineup generation, LP solving, parallel execution. Must not contain ranking or export logic.
* **`ranker.py`:** Lineup scoring and weighted rank calculation. Must not contain generation or export logic.
* **`exporter.py`:** DraftKings CSV template parsing and lineup mapping. Must not contain scoring logic.
* **`exposure_report.py`:** Post-export analytics and leverage calculation. Must not contain optimization or ranking.
* **`late_swapper.py`:** Lock detection and constrained re-optimization. Must not contain full lineup generation.
* **`orchestrator.py`:** Pipeline orchestration and Config injection. Must not contain core logic.

**Do not move logic between modules unless explicitly refactoring boundaries.**

### Dependency Injection Pattern

All module `run()` functions must accept a `Config` instance as a parameter. Never use global state or module-level configuration variables.

```python
def run(cfg: Config) -> None:
    # Use cfg.salary_cap, cfg.base_dir, etc.
```

CLI overrides should use `dataclasses.replace()` to immutably override Config defaults.

## Naming Conventions

| Item | Rule | Example |
|------|------|---------|
| Files | `snake_case.py` | `late_swapper.py`, `exposure_report.py` |
| Functions/methods | `snake_case` | `generate_single_lineup()`, `rank_lineups()` |
| Classes | `PascalCase` | `Config` |
| Constants | `UPPER_SNAKE_CASE` | `SALARY_CAP`, `ROSTER_SLOTS` |
| Local variables | `snake_case` | `min_salary`, `projs_file` |
| DataFrame variables | `df_` prefix | `df_players`, `df_ranked`, `df_entries` |
| Dictionary lookups | `_dict` or `_map` suffix | `salary_dict`, `pos_dict`, `proj_map` |
| Config instances | `cfg` or `config` | `cfg: Config` |

## Import Conventions

* **Import order:** stdlib → third-party (`pandas`, `numpy`, `pulp`) → local (relative imports)
* **Within-package imports:** Use relative imports (`from .config import Config`, `from .utils import get_latest_file`)
* **Script-level imports:** Use absolute package imports (`from nba_optimizer import engine, ranker`)
* **No `sys.path` manipulation:** The project uses `pip install -e .` and `pyproject.toml` entry points

### Example

```python
# Good - inside src/nba_optimizer/engine.py
from . import config
from .utils import get_latest_file

# Bad - inside src/nba_optimizer/engine.py
import src.nba_optimizer.config as config  # Wrong!
```

## Code Style and Formatting

* **Line length:** Generally 88-100 characters (no strict enforcement)
* **No formatter configured:** Match existing code style in the file being modified
* **No linter configured:** Follow PEP 8 conventions where practical
* **Comments:** Only add comments where logic is not self-evident. Do not add docstrings or comments to code you didn't change.
* **Type hints:** Optional. Use where they improve clarity, but not required.

## Error Handling and Logging

* **Error strategy:** Use `try/except` at the `run()` function level. Print errors with `print(f"Error: {e}")` and call `traceback.print_exc()`.
* **Logging:** Use simple `print()` statements for all output. No logging framework is configured.
* **Progress reporting:** Print percentage-based progress at 20% intervals for long operations.

### Example

```python
def run(cfg: Config) -> None:
    try:
        # Main logic here
        print("Starting lineup generation...")
    except Exception as e:
        print(f"Error in engine: {e}")
        traceback.print_exc()
```

## Data Handling

### Constants and Configuration

* **DraftKings constants:** Use centralized constants from `config.py` (e.g., `ROSTER_SLOTS`, `ENTRY_HEADER_COLS`)
* **Never hardcode:** Position slots, entry headers, or magic numbers should be centralized in `config.py`

### File Communication

* **Timestamped CSV artifacts:** Stages communicate via timestamped CSV files (e.g., `lineup-pool-{timestamp}.csv`)
* **Latest file detection:** Use `utils.get_latest_file()` consistently. Do not implement custom file-finding logic.

### Performance Optimization

* **Dict-based lookups:** In LP constraint loops, use pre-built dictionaries (`salary_dict`, `pos_dict`) instead of `df.loc[]` lookups
* **Avoid `iterrows()`:** Vectorize operations with pandas where possible
* **Minimize DataFrame copying:** Be conscious of DataFrame size in multiprocessing contexts

### Example - Dict-based Lookup

```python
# Good - pre-build dictionaries
salary_dict = dict(zip(df_players['Name'], df_players['Salary']))
for player in candidate_players:
    salary = salary_dict[player]  # Fast O(1) lookup

# Bad - repeated DataFrame lookups
for player in candidate_players:
    salary = df_players.loc[df_players['Name'] == player, 'Salary'].values[0]  # Slow
```

## Testing and Verification

* **No formal test suite:** The repository has no automated tests. Do not add generic or opaque tests.
* **Manual verification:** Validate changes by running the pipeline with real CSV inputs and inspecting outputs.
* **Targeted testing:** If adding tests in the future, they must be transparent, domain-relevant, and tied to real optimizer behavior.

### Commands for Manual Testing

```bash
pip install -e .
python scripts/run_optimizer.py -n 100  # Small test run
python scripts/run_optimizer.py --late_swap  # Test late swap
```

## Security Considerations

* **No secrets in code:** Never commit API keys, credentials, or sensitive paths
* **Environment variables:** Use `.env` for local paths. Never commit `.env` (only `.env.example`)
* **Input validation:** This is a local single-user tool. Path validation at system boundaries is minimal by design.

## Code Review Focus Areas

When reviewing code in this repository, prioritize:

1. **Correctness:** Does the code achieve the stated goal? Are edge cases handled?
2. **Module boundaries:** Does the change respect the pipeline architecture? Is logic in the right module?
3. **Simplicity:** Is this the simplest solution? Are there unnecessary abstractions or premature optimizations?
4. **Backwards compatibility:** Do changes break existing CSV formats, configuration, or module interfaces?
5. **Performance:** Are there obvious inefficiencies (e.g., using `iterrows()` instead of vectorization)?
6. **Consistency:** Does the code match existing patterns (naming, imports, error handling)?

## Things to Avoid

* **Do not refactor untouched code:** Only modify code directly related to the task
* **Do not add unnecessary features:** Stick to the requirements. No "improvements" beyond what was asked
* **Do not add error handling for impossible scenarios:** Trust internal code and framework guarantees
* **Do not create abstractions for one-time operations:** Three similar lines are better than a premature abstraction
* **Do not remove or edit unrelated tests:** If tests exist in the future, only modify tests related to your changes
* **Do not use backwards-compatibility hacks:** Delete unused code completely. No `_var` renaming or `// removed` comments

## Repository-Specific Risks

Be especially careful with these high-risk areas:

* **`engine.py` (400+ lines, highest churn):** Test LP constraints independently before modifying
* **`late_swapper.py` (complex lock detection):** Verify against known DKEntries.csv with locked players
* **Stale file pickup:** "Latest file" heuristic can pick up outputs from previous failed runs. Consider adding validation.
* **Data loading duplication:** `engine.py` and `late_swapper.py` both have `load_data()`. Keep them in sync if modifying.

## References

* [Stack Documentation](../docs/codebase/STACK.md)
* [Structure Documentation](../docs/codebase/STRUCTURE.md)
* [Architecture Documentation](../docs/codebase/ARCHITECTURE.md)
* [Conventions Documentation](../docs/codebase/CONVENTIONS.md)
* [Concerns Documentation](../docs/codebase/CONCERNS.md)
* [Testing Documentation](../docs/codebase/TESTING.md)

## Final Notes

This is a **single-user, local optimization tool** for DFS contests. The code prioritizes:
* Practical functionality over enterprise patterns
* Simplicity over flexibility
* Manual verification over automated testing
* Direct solutions over architectural complexity

When in doubt, follow existing patterns in the codebase and keep changes minimal.
