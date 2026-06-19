# Architecture

## Core Sections (Required)

### 1) Architectural Style

- Primary style: **Sequential pipeline with modular stages**
- Why this classification: The orchestrator (`run_optimizer.py`) calls four modules in strict order — Engine → Ranker → Exporter → Exposure Report. Each stage reads the previous stage's CSV output. Configuration is injected as a `Config` instance, eliminating global state.
- Primary constraints:
  1. DraftKings roster rules (8 players, positional slots, salary cap, multi-game requirement)
  2. File-system coupling — stages communicate via timestamped CSVs in configured directories
  3. Single-machine execution — parallel LP solving via `ProcessPoolExecutor` across local CPU cores

### 2) System Flow

```text
DKEntries.csv + NBA-Projs-*.csv
       │
       ▼
[Engine] ── parallel LP solve with randomized projections ──► lineup-pool-{timestamp}.csv
       │
       ▼
[Ranker] ── score by weighted projection/ownership ranks ──► ranked-lineups-{timestamp}.csv
       │
       ▼
[Exporter] ── map top N lineups into DK template ──► upload-ready-DKEntries-{timestamp}.csv
       │
       ▼
[Exposure Report] ── calculate player exposure vs. projected ownership ──► console output
```

**Alternate flow (Late Swap):**
```text
DKEntries.csv (with locked players) + NBA-Projs-*.csv
       │
       ▼
[Late Swapper] ── batch LP solve per unique lock state ──► late-swap-entries-{timestamp}.csv
```

1. **Data Loading:** Engine reads DKEntries.csv (player pool with salaries, positions, game info) and merges with projection CSV on player ID.
2. **Parallel Generation:** `ProcessPoolExecutor` spawns one LP solve per target lineup. Each worker applies random noise to projections, solves a binary LP (PuLP + HiGHS), and returns selected player names + indices.
3. **Uniqueness Filtering:** Main process filters candidates by `min_unique` overlap constraint, then parallelizes time-based slot assignment.
4. **Ranking:** Ranker loads the lineup pool CSV, computes per-lineup Total Projection / Total Ownership / Geomean Ownership, applies user-specified weights to rank positions, and sorts by composite score.
5. **Export:** Exporter reads the DKEntries template (ragged CSV), fills entry slots with top-ranked lineups, and writes the upload-ready file.
6. **Reporting:** Exposure report resolves the target entries file via `_resolve_entries_file()`. If `--entries_file` is given, that path is used directly. Otherwise, it tries three glob patterns against `output_dir` in order — `upload-ready-DKEntries-*.csv`, `late-swap-entries-*.csv`, and `{base}*{ext}` (derived from `cfg.entries_path`, e.g. `DKEntries*.csv` to catch variants like `DKEntries(1).csv`) — collects the newest match from each pattern, and returns the overall most-recently-modified candidate. It then parses the file, counts per-player appearances, and computes leverage (exposure % − projected ownership %).

### 3) Layer/Module Responsibilities

| Layer or module | Owns | Must not own | Evidence |
|-----------------|------|--------------|----------|
| `config.py` | Configuration dataclass, env var loading, directory creation factory function | Any business logic | `src/nba_optimizer/config.py` |
| `utils.py` | File discovery, ID/time parsing, ragged CSV reading | Optimization or ranking | `src/nba_optimizer/utils.py` |
| `engine.py` | LP model construction, parallel solving, slot optimization | Ranking, export | `src/nba_optimizer/engine.py` |
| `ranker.py` | Lineup scoring, weighted rank calculation | Lineup generation | `src/nba_optimizer/ranker.py` |
| `exporter.py` | DK template parsing, lineup-to-entry mapping | Scoring | `src/nba_optimizer/exporter.py` |
| `exposure_report.py` | Post-export analytics, leverage calculation, flexible file resolution via `_resolve_entries_file()` | Everything else | `src/nba_optimizer/exposure_report.py` |
| `late_swapper.py` | Lock detection, constrained re-optimization, batch solving | Full lineup generation | `src/nba_optimizer/late_swapper.py` |
| `orchestrator.py` | Pipeline orchestration, Config initialization and injection | Core logic | `src/nba_optimizer/orchestrator.py` |

### 4) Reused Patterns

| Pattern | Where found | Why it exists |
|---------|-------------|---------------|
| Dependency Injection | All module `run()` functions accept `Config` instance | Enables isolated testing, concurrent instances, and eliminates global state |
| PuLP LP model with HiGHS solver | `engine.py`, `late_swapper.py` | Core optimization mechanism for roster construction |
| Positional eligibility matrix (slot_vars) | `engine.py:generate_single_lineup()`, `engine.py:slot_lineup_by_time()`, `late_swapper.py:solve_late_swap_batch()` | DraftKings requires specific position-to-slot mapping with flex rules |
| Timestamped CSV artifacts | All modules | Enables pipeline stages to find the latest output without shared memory |
| Explicit artifact handoff in orchestrated runs | `orchestrator.py` captures the return value of each stage and passes it as an explicit parameter to the next | Prevents stale files from a failed previous run from being picked up mid-pipeline |
| Latest-file fallback for standalone usage | `ranker.run()`, `exporter.run()`, `exposure_report.run()` | When a stage is invoked directly (not via the orchestrator) its explicit-path parameters default to `None` and the module falls back to `get_latest_file()` discovery |
| Dict-based lookup optimization | `engine.py` (salary_dict, pos_dict, name_dict) | Avoids expensive `df.loc` inside LP constraint loops |
| `main()` with argparse per module | All modules | Allows standalone execution of any pipeline stage |
| `dataclasses.replace()` for config override | `orchestrator.py`, module `main()` functions | Immutably overrides Config defaults with CLI arguments |

### 5) Known Architectural Risks

- **File-system coupling (orchestrated path — mitigated):** When run through the orchestrator, each stage now passes its output path explicitly to the next stage, so stale files from a prior partial run cannot be picked up. The "latest file" heuristic is preserved only for standalone direct-module invocation (`python -m nba_optimizer.ranker`, etc.).
- **File-system coupling (standalone path — remaining):** Running any stage module directly still relies on the newest matching file in the relevant directory. A stale file from a failed run could still be picked up when a stage is invoked outside the orchestrator.
- **Data loading duplication:** `engine.py` and `late_swapper.py` each have their own `load_data()` function with subtly different CSV parsing logic. `ranker.py` imports `engine.load_data()` to reuse it but this creates a cross-module dependency.
- **DataFrame pickling overhead on Windows:** `ProcessPoolExecutor` pickles the full DataFrame for each worker on Windows (no copy-on-write). For large player pools this adds serialization cost.
- **Worker function signature complexity:** The `generate_single_lineup()` worker must receive all config values as individual parameters (salary_cap, roster_size, min_games) since it cannot access the Config instance in the multiprocessing context.

### 6) Evidence

- `scripts/run_optimizer.py` (pipeline orchestration)
- `src/nba_optimizer/engine.py` (parallel LP solving)
- `src/nba_optimizer/ranker.py` (scoring logic)
- `src/nba_optimizer/exporter.py` (DK template mapping)
- `src/nba_optimizer/late_swapper.py` (constrained re-optimization)
