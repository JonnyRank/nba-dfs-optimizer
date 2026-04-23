# NBA DFS Optimizer Code Review Style Guide

## Core Principles

* **Simplicity First:** Avoid over-engineering. Make only requested or necessary changes.
* **Surgical Modifications:** Preserve existing code structure. Minimal changes only.
* **Readability:** Prioritize clarity over cleverness.
* **Consistency:** Follow established patterns in the codebase.

## Architecture

The project uses a **sequential pipeline architecture** with strict module boundaries. See [Architecture Documentation](../docs/codebase/ARCHITECTURE.md) for details.

Key modules: `config.py` → `engine.py` → `ranker.py` → `exporter.py` → `exposure_report.py`

**Do not move logic between modules** unless explicitly refactoring boundaries.

### Dependency Injection

All module `run()` functions accept a `Config` instance. Never use global state. Use `dataclasses.replace()` for CLI overrides.

## Naming Conventions

See [Conventions Documentation](../docs/codebase/CONVENTIONS.md) for full details.

* Files: `snake_case.py`
* Functions: `snake_case`
* Classes: `PascalCase`
* `Config` attributes: `snake_case`
* Module-level constants: `UPPER_SNAKE_CASE`
* DataFrames: `df_` prefix
* Dictionaries: `_dict` or `_map` suffix

## Import Conventions

* **Within package:** Relative imports (`from .config import Config`)
* **Scripts:** Absolute imports (`from nba_optimizer import engine`)
* **Order:** stdlib → third-party → local
* No `sys.path` manipulation

## Code Style

* Line length: ~88-100 characters (no strict enforcement)
* No formatter or linter configured - match existing code style
* Comments only where logic is not self-evident
* Type hints optional

## Error Handling

* Use `try/except` at `run()` function level
* Print errors with `print(f"Error: {e}")` and `traceback.print_exc()`
* Simple `print()` for all output (no logging framework)

## Data Handling

* Use centralized constants from `config.py` (e.g., `ROSTER_SLOTS`)
* Stages communicate via timestamped CSV files
* Use `utils.get_latest_file()` consistently
* **Performance:** Pre-build dicts for LP loops instead of `df.loc[]` lookups

## Testing

* No formal test suite - manual verification only
* Run pipeline with real CSV inputs and inspect outputs
* Do not add generic or opaque tests

## Code Review Focus

1. **Correctness:** Does it work? Edge cases handled?
2. **Module boundaries:** Logic in the right module?
3. **Simplicity:** Simplest solution? No premature optimization?
4. **Backwards compatibility:** Breaks existing interfaces?
5. **Performance:** Obvious inefficiencies?
6. **Consistency:** Matches existing patterns?

## Things to Avoid

* Refactoring untouched code
* Adding unnecessary features
* Creating abstractions for one-time operations
* Backwards-compatibility hacks - delete unused code completely

## High-Risk Areas

* `engine.py` (400+ lines, highest churn)
* `late_swapper.py` (complex lock detection)
* "Latest file" heuristic can pick up stale outputs

## References

For detailed information, see:
* [STACK.md](../docs/codebase/STACK.md)
* [STRUCTURE.md](../docs/codebase/STRUCTURE.md)
* [ARCHITECTURE.md](../docs/codebase/ARCHITECTURE.md)
* [CONVENTIONS.md](../docs/codebase/CONVENTIONS.md)
* [CONCERNS.md](../docs/codebase/CONCERNS.md)
* [TESTING.md](../docs/codebase/TESTING.md)

## Summary

Single-user local tool prioritizing practical functionality over enterprise patterns. When in doubt, follow existing patterns and keep changes minimal.
