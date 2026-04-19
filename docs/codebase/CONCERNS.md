# Codebase Concerns

## Core Sections (Required)

### 1) Top Risks (Prioritized)

| Severity | Concern | Evidence | Impact | Suggested action |
|----------|---------|----------|--------|------------------|
| High | No automated tests | No test files in repo; test files were deleted | Regressions go undetected; manual verification only | Add unit tests for core LP logic and data loading |
| High | Duplicate `load_data()` implementations | `engine.py:load_data()` vs `late_swapper.py:load_data()` have different CSV parsing logic | Bugs fixed in one may not be fixed in the other; subtle data inconsistencies | Consolidate into `utils.py` or a shared data loader |
| Medium | Stale file pickup after failed runs | All modules use "latest file by timestamp" heuristic | A failed engine run leaves a partial lineup pool that the ranker may pick up | Add validation (e.g., row count check) or a run-ID linking mechanism |
| Medium | `engine.py` is 400+ lines mixing data loading, LP construction, slotting, and orchestration | `engine.py` (13.9KB, highest churn at 14 commits) | Hard to modify one concern without risking another | Extract `load_data`, `slot_lineup_by_time`, and `generate_single_lineup` into focused modules |

### 2) Technical Debt

| Debt item | Why it exists | Where | Risk if ignored | Suggested fix |
|-----------|---------------|-------|-----------------|---------------|
| `engine.py` has its own `get_latest_projections()` while `utils.py` has `get_latest_file()` | Predates utils extraction | `engine.py:get_latest_projections()` | Inconsistent file resolution behavior | Replace with `utils.get_latest_file(config.PROJS_DIR, "NBA-Projs-*.csv")` |
| `exposure_report.py` has its own `get_latest_file()` using `getmtime` instead of basename sorting | Different sorting requirement | `exposure_report.py:get_latest_file()` | Two file-finding implementations with different semantics | Use `utils.get_latest_file()` with `use_mtime=True` |
| `ranker.py` imports `engine.load_data()` for player context | Avoids duplicating merge logic | `ranker.py:load_data()` | Tight coupling between ranker and engine | Extract shared data loading to a common module |
| Deprecated code in `deprecated/` folder | Legacy late swapper kept for reference | `deprecated/late_swapper_deprecated.py` (12.6KB) | Confusion about which is canonical | Remove or archive outside repo |
| Legacy `sys.path.insert` script hack | Replaced by package-based imports and `pyproject.toml` entry points | `pyproject.toml`, `scripts/run_optimizer.py`, `scripts/run_optimizer_gui.py` | Resolved | Keep execution standardized via `pip install -e .` and console scripts |

### 3) Security Concerns

| Risk | OWASP category | Evidence | Current mitigation | Gap |
|------|----------------|----------|--------------------|-----|
| File paths from `.env` used without validation | N/A (local tool) | `config.py` | `os.makedirs(exist_ok=True)` with fallback | No path traversal risk in practice (single-user local tool) |
| Raw `traceback.print_exc()` in all error handlers | A09: Security Logging and Monitoring Failures | All modules | None | Low risk for local tool; would matter if exposed via web UI |

This is a single-user, locally-run tool with no network exposure. Security risks are minimal.

### 4) Performance and Scaling Concerns

| Concern | Evidence | Current symptom | Scaling risk | Suggested improvement |
|---------|----------|-----------------|-------------|-----------------------|
| DataFrame pickled per worker on Windows | `engine.py` uses `ProcessPoolExecutor` | Serialization overhead when player pool is large | Grows linearly with worker count × DataFrame size | Consider using `multiprocessing.shared_memory` or passing only necessary columns |
| `ranker.py` uses `iterrows()` for all lineups | `ranker.py:rank_lineups()` | Slow for large lineup pools (2500+) | O(n) with high constant factor due to Python loop | Vectorize with pandas operations |
| `late_swapper.py` uses `df.loc[i, ...]` inside LP constraint loops | `late_swapper.py:solve_late_swap_batch()` | Slower LP construction vs engine's dict-based approach | Gets worse with larger player pools | Convert to dict-based lookups like `engine.py` does |

### 5) Fragile/High-Churn Areas

| Area | Why fragile | Churn signal | Safe change strategy |
|------|-------------|-------------|----------------------|
| `engine.py` | Largest source file, mixes multiple concerns, highest churn | 14 changes in 90 days | Test LP constraints independently before modifying |
| `late_swapper.py` | Complex lock-detection logic, batch solving with iterative exclusion | 8 changes in 90 days | Verify against a known DKEntries.csv with locked players |
| `run_optimizer.py` (scripts) | Orchestrator updated whenever module interfaces change | 12 changes (old location) + 2 (new) | Ensure all module `run()` signatures are stable |

### 6) Resolved Questions (from user, 2026-04-18)

1. **GUI:** Gooey has replaced Streamlit for now. User is researching alternative GUI frameworks due to Gooey's inflexibility (button placement locked to OS, no start-on-enter option). **SQLite:** Still planned but pending architectural decision on whether to use SQLite or migrate to Postgres in a separate project.
2. **Excel data loader:** Still desired but low priority. Do not implement until user requests it.
3. **Test suite:** User is conflicted. Previous AI-assisted pytest effort produced opaque, non-useful tests. User values manual testing as a learning tool. Revisit when user is ready — any future implementation should prioritize transparent, domain-relevant tests over coverage metrics.
4. **Import standardization:** Resolved. Absolute imports in `engine.py` and `exposure_report.py` have been converted to relative imports to match the rest of the package.

### 7) Evidence

- Scan output: high-churn files, code metrics, directory tree
- `src/nba_optimizer/engine.py` (duplicate load_data, get_latest_projections)
- `src/nba_optimizer/exposure_report.py` (duplicate get_latest_file)
- `src/nba_optimizer/ranker.py` (engine import dependency)
- `design_docs/project_plan.md` (planned but unimplemented phases)
- Git commit history (scan output)
