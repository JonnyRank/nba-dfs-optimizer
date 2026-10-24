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
[Assembler] ── rank-sum ILP under --max/--min/--max-all ──► assembled-lineups-{timestamp}.csv/.json
       │
       ▼
[Exporter] ── map the assembly into DK template in Entry_Order ──► upload-ready-DKEntries-{timestamp}.csv
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

**Nightly capture (O-0):** with `NBA_DATA_ROOT` set, the orchestrator resolves the slate (`slate.load_or_write_slate`), writes `slate.json` once, copies the DKEntries and projections it read into `<NBA_DATA_ROOT>/<slate_id>/`, and points the pool/ranked outputs there. One run instant names every output; filenames use the slate date. The ranker writes a run-record JSON next to the ranked CSV, and the exporter writes an `L<k>-entry-set-*.json` (copying the upload-ready file into the slate folder). After the last lock, `nba-dfs-capture finalize` (`capture.py`) classifies the night's files by content, assigns them to locks by modified time, verifies each lock's entry set against the final DKEntries, and writes `finalize.json` + `slate-entries.csv`. Contest standings are copied in as delivered: a `contest-standings-*.zip` from Downloads has its single CSV streamed into the slate folder (the zip is only read), and a zip with other files is skipped with a warning. The engine is seeded (`--seed`): lineup j draws from `SeedSequence(base_seed, spawn_key=(j,))`, and candidates are sorted by j, so a seed reproduces the pool regardless of worker scheduling. When `--seed` is omitted, `engine.run` draws a seed and writes it back to `cfg.seed`; the orchestrator reads it from there to pass `base_seed` to the ranker's run record. Without `NBA_DATA_ROOT` (legacy layout) the run record and entry set are written next to their CSVs in `exports/` and the output folder. A run after a slate's last lock writes no entry set.

**Stage control (O-13):** `nba-dfs-optimizer --from {generate,rank,assemble,export} --to …` runs a slice of generate → rank → assemble → export. A `--from` stage reads the newest artifact of the stage before it from the slate folder by its record's `generated_at` (`--pool/--ranked/--assembled` override; `--slate-dir` works on a past slate; legacy layout falls back to latest-file lookup). `settings.resolve_settings` resolves weights, `--proj/--own` overrides (`overrides.py`) and caps with precedence typed > inherited from the latest record of that stage > `Config` default, and prints an `Effective settings` block; a full run never inherits. An inherited override carries while the newest export still has its recorded `from` value. `assembler.py` first applies `-u/--min_unique` (O-14) by walking the ranked pool in `Final_Rank` order and dropping any lineup that shares more than 8−u players with a better-ranked survivor, then picks N survivors minimising the sum of `Final_Rank` (PuLP + HiGHS, 10 s limit, `proven_optimal` recorded; with no caps or floors it takes the first N survivors without a solver); `-u` carries forward like the caps (`--clear-caps` leaves it, `--reset-settings` resets it); infeasible requests fail with the culprit constraints and write nothing; the diagnosis reuses the one built model, relaxing one constraint's bound per re-solve. On a finished slate the newest export is another slate's, so a `--from rank` ranks with the parent run's projections copy and a full run uses the folder's newest `L0-NBA-Projs-*` copy (pre-lock-0 numbers, no later news; this includes a full run on tonight's slate after its last lock, which fails if no run happened before lock 0), and every rank fails if any pool player lacks a projection. `--no-slate-folder` makes one run use the legacy layout even with `NBA_DATA_ROOT` set. The re-rank's run record adds `parent_run_id`, `overrides`, `inherited`, `projections_rule`; the export's L0 entry set adds `assembly_id`. The exporter writes an entry set only at lock 0 (computed from `slate.json` at the export's own time). `cli.add_pipeline_args` defines the arguments once for the CLI and the Gooey GUI; the GUI pre-fills the weight and `-u` boxes with their defaults and uses them as typed, so a cleared box inherits.

**Input resolution (O-15):** before anything is written, `orchestrator.resolve_run_inputs` calls `inputs.resolve_inputs`, which picks the run's projections and DKEntries for `--slate-type`. The type chooses the projections folder (`main` → `NBA_PROJS_DIR`; any other type → `NBA_PROJS_DIR_<TYPE>` or the sibling `<NBA_PROJS_DIR>-<type>`); the newest `NBA-Projs-*.csv` there by the `YYYY-MM-DD_HH-MM-SS` in its name (modified time without one) is used, and a file named for another type (`NBA-Projs-Night-…` in the main folder) is skipped with a warning. `--entries` (a GUI file chooser) is used as given; blank means the newest `DKEntries*.csv` in `NBA_DOWNLOADS_DIR` (plus `NBA_ENTRIES_PATH` when it exists) modified within 24 h of the run whose players match those projections. DK player IDs are per slate, so at least `inputs.MATCH_MIN` (50%) of the DKEntries' pool IDs must appear in the projections, and `slate.check_slate_folder` requires the same share against an existing slate folder's `Pre-L0-DKEntries.csv` (or, for a new folder, that no other folder of that date matches). Once a slate has finished, the newest export is usually the next slate's, so a DKEntries whose finished slate folder holds its players (`slate.finished_slate_dir`) skips the projections match, and auto mode falls back to the newest recent download for a finished slate; the past-slate rules then use the folder's own projections. The config then reads from the type's folder and the chosen DKEntries, so every later fallback reads the right files; `--from assemble/export` resolve the same way for the slate's identity only. `--slate-dir` skips resolution and takes the type from the folder's `slate.json`. Late swap resolves the same way and writes `late-swap-entries-<Type>-…` for non-main types. `nba-dfs-capture finalize` with no arguments finalizes every slate folder of that night's date (`capture.finalize_targets`), each searching its own type's projections folder; `record` without `--slate-dir` picks among a date's folders by player IDs.

1. **Data Loading:** Engine reads DKEntries.csv (player pool with salaries, positions, game info) and merges with projection CSV on player ID.
2. **Parallel Generation:** One `ProcessPoolExecutor` whose workers receive the player pool once via `initializer` (`_init_worker`) and build a persistent HiGHS `LineupModel` once per worker. Workers then solve and slot lineups in batches (`_generate_batch`), applying random noise to projections and re-solving the same model with only the objective swapped, and return row positions + slotted names.
3. **Ranking:** Ranker loads the lineup pool CSV (every generated lineup, exact duplicates included), computes per-lineup Total Projection / Total Ownership / Geomean Ownership, applies user-specified weights to rank positions, and sorts by composite score.
4. **Assembly:** Assembler walks the ranked pool for `min_unique` (of two too-similar lineups the better-ranked stays), then picks the N entries from the survivors under the exposure caps.
5. **Export:** Exporter reads the DKEntries template (ragged CSV), fills entry slots with the assembled lineups, and writes the upload-ready file.
6. **Reporting:** Exposure report resolves the target entries file via `_resolve_entries_file()`. If `--entries_file` is given, that path is used directly. Otherwise, it tries three glob patterns against `output_dir` in order — `upload-ready-DKEntries-*.csv`, `late-swap-entries-*.csv`, and `{base}*{ext}` (derived from `cfg.entries_path`, e.g. `DKEntries*.csv` to catch variants like `DKEntries(1).csv`) — collects the newest match from each pattern, and returns the overall most-recently-modified candidate. It then parses the file, counts per-player appearances, and computes leverage (exposure % − projected ownership %).

### 3) Layer/Module Responsibilities

| Layer or module | Owns | Must not own | Evidence |
|-----------------|------|--------------|----------|
| `config.py` | Configuration dataclass, env var loading (`.env` found from the package location), directory creation factory function | Any business logic | `src/nba_optimizer/config.py` |
| `inputs.py` | Per-slate-type projections folder, newest projections by name time, DKEntries auto-pick, DKEntries↔projections ID check (O-15) | Writing anything | `src/nba_optimizer/inputs.py` |
| `utils.py` | File discovery, ID/time parsing, ragged CSV reading, shared player-pool loading (`parse_dk_entries`, `merge_player_pool`) | Optimization or ranking | `src/nba_optimizer/utils.py` |
| `engine.py` | LP model construction, parallel solving, slot optimization | Ranking, export | `src/nba_optimizer/engine.py` |
| `ranker.py` | Lineup scoring, weighted rank calculation | Lineup generation | `src/nba_optimizer/ranker.py` |
| `assembler.py` | Selecting the N entries from a ranked pool under exposure caps (rank-sum ILP), infeasibility diagnosis, assembly record | Scoring, export | `src/nba_optimizer/assembler.py` |
| `overrides.py` | `NAME=VALUE` parsing, player lookup by DK ID/name, projection/ownership overrides | Ranking | `src/nba_optimizer/overrides.py` |
| `settings.py` | Stage order, typed/inherited/default setting resolution, ignored-flag warnings | Running stages | `src/nba_optimizer/settings.py` |
| `exporter.py` | DK template parsing, lineup-to-entry mapping | Scoring | `src/nba_optimizer/exporter.py` |
| `exposure_report.py` | Post-export analytics, leverage calculation, flexible file resolution via `_resolve_entries_file()` | Everything else | `src/nba_optimizer/exposure_report.py` |
| `late_swapper.py` | Lock detection, constrained re-optimization, batch solving | Full lineup generation | `src/nba_optimizer/late_swapper.py` |
| `orchestrator.py` | Pipeline orchestration, Config initialization and injection, slate resolution and input snapshots | Core logic | `src/nba_optimizer/orchestrator.py` |
| `slate.py` | Slate facts from the pre-lock DKEntries (locks, games, contests, entry IDs), `slate.json`, lock numbering, the DKEntries↔slate-folder guard | Optimization, file search | `src/nba_optimizer/slate.py` |
| `records.py` | Run-record/entry-set payloads, file classification by content, blend check, copy/atomic-write helpers | Optimization, ranking | `src/nba_optimizer/records.py` |
| `capture.py` | `nba-dfs-capture finalize` / `record`: search, lock assignment, chain verification against DK | Lineup generation | `src/nba_optimizer/capture.py` |

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
- **Data loading (resolved):** `engine.py`, `late_swapper.py`, and `ranker.py` all share `parse_dk_entries` and `merge_player_pool` from `utils.py`. Engine and ranker use `how="inner"` with a simple `"Game Info"` string split for the `Game` column (pre-lock, matchup strings are always valid). Late-swap uses `how="left"` (retaining current-lineup players without projections) and `_attach_game_column` (which calls `derive_game_key`) to recover games marked "In Progress".
- **Player pool sent once per worker:** the pool is shipped via the pool `initializer` (not per task), and `OPENBLAS_NUM_THREADS=1` is set so spawned workers do not each reserve ~700 MB of OpenBLAS buffers.
- **Worker function signature complexity:** `_init_worker()` must receive all config values as individual parameters (salary_cap, roster_size, min_games) since workers cannot access the Config instance in the multiprocessing context.

### 6) Evidence

- `scripts/run_optimizer.py` (pipeline orchestration)
- `src/nba_optimizer/engine.py` (parallel LP solving)
- `src/nba_optimizer/ranker.py` (scoring logic)
- `src/nba_optimizer/exporter.py` (DK template mapping)
- `src/nba_optimizer/late_swapper.py` (constrained re-optimization)
