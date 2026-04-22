# NBA DFS Optimizer Backlog

## Active Tasks

### [Design] Flexible File Parsing for Exposure Report
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/exposure_report.py`, `src/nba_optimizer/utils.py`
* **Context**: The exposure report currently hardcodes the filename prefix (`upload-ready-DKEntries-`). It needs to handle late swap files automatically and allow users to pass an explicit filename argument via CLI.
* **Acceptance Criteria**:
  * [ ] CLI accepts an optional `--entries_file` or `--prefix` argument.
  * [ ] Fallback logic correctly identifies whether to look for standard or late-swap exports if no argument is passed.
* **LLM Instructions**: Act as a software architect. Review `run` and `main` in `exposure_report.py`. Draft a pseudocode plan showing how we will refactor the `get_latest_file` logic and the `argparse` configuration to support this. Wait for my approval before coding.

### [Design] Graceful Early Interruption for Engine Generator
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`, `scripts/run_optimizer.py`
* **Context**: We want the ability to safely interrupt (`Ctrl+C` or GUI stop button) the parallel lineup generation in `engine.py` without losing the lineups already generated. The pipeline should then proceed to ranking/exporting those completed lineups.
* **Acceptance Criteria**:
  * [ ] Catch `KeyboardInterrupt` gracefully in `engine.py`.
  * [ ] Ensure the `ProcessPoolExecutor` shuts down cleanly and returns all valid lineups generated up to the interruption point.
* **LLM Instructions**: Act as a senior Python systems developer. Review the `concurrent.futures.ProcessPoolExecutor` block in `engine.py`. Propose a design to implement a graceful shutdown mechanism that intercepts `SIGINT` (Ctrl+C) and flushes the completed futures into the remaining pipeline.

### [Research] MILP Grouping Constraints (Min/Max & Projection Multipliers)
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`, `src/nba_optimizer/late_swapper.py`
* **Context**: We need to add player grouping logic to our PuLP formulation. Examples include "max 2 of these 5 players" or applying a percentage bump/decrease to a specific group's projections.
* **Acceptance Criteria**:
  * [ ] Document the mathematical LP formulation for these grouping constraints.
  * [ ] Detail tradeoffs between solver runtime vs. model complexity.
* **LLM Instructions**: Act as a senior Operations Research Data Scientist. Review `engine.py`. Propose exactly how we would inject arbitrary grouping constraints and projection multipliers into the `generate_single_lineup` PuLP formulation. Provide a markdown summary of the tradeoffs.

### [Research] MILP Exposure Caps
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`, `src/nba_optimizer/late_swapper.py`
* **Context**: We want to restrict player exposures (e.g., max 30% exposure for Player X) across the entire pool of generated lineups.
* **Acceptance Criteria**:
  * [ ] Provide a mathematical framework to achieve global exposure caps across a parallelized, randomized generation engine.
  * [ ] Assess feasibility: Does this require moving from parallel single-lineup generation to a multi-lineup global optimization model, or can we enforce this via dynamic tracking?
* **LLM Instructions**: Act as an Operations Research Data Scientist. The optimizer generates independent lineups in parallel. Detail 3 strategies for implementing global exposure caps in this architecture. Compare a pure LP global solve vs. sequential generation with dynamic probability updating. 

### [Research] Post-Generation Lineup Filtering for Exposure Caps
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/ranker.py`, `src/nba_optimizer/exporter.py`, `src/nba_optimizer/config.py`
* **Context**: Unlike enforcing global MILP exposure constraints during generation, we want to restrict player exposures (e.g., max 30% for Player X) during the final selection phase. This means sequentially picking from the sorted, ranked pool of generated lineups and skipping any lineup that would push a player over their set maximum exposure limit.
* **Acceptance Criteria**:
  * [ ] Detail a fast, sequential filtering algorithm (using Pandas or standard Python dictionaries) to iterate through the ranked pool and track cumulative exposures.
  * [ ] Define the fallback behavior if the strict exposure caps cause the pool to run out of valid lineups before the requested number of export entries (e.g., `-n 150`) is met.
  * [ ] Determine whether this logic belongs at the end of `ranker.py` or the beginning of `exporter.py`.
* **LLM Instructions**: Act as a Python Data Engineer. Review how lineups are sorted in `ranker.py` and passed to `exporter.py`. Draft pseudocode for a greedy selection algorithm that accepts a dictionary of player exposure caps, iterates through the ranked DataFrame, and builds the final export list without exceeding the caps. Detail how we should handle the edge case where the pool is exhausted before the target lineup count is reached.

### [Research] Defer Duplicate Lineup Filtering to Post-Generation
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`, `src/nba_optimizer/exporter.py`
* **Context**: Currently, duplicate lineups are filtered out during or immediately after generation in `engine.py`. We want to investigate the pipeline speed and memory tradeoffs of completely skipping deduplication in the engine and instead overlooking/skipping duplicates dynamically during the final export selection phase.
* **Acceptance Criteria**:
  * [ ] Analyze the speed/memory impact on `engine.py` if it simply outputs all generated lineups (including duplicates) to the pool.
  * [ ] Detail how a deferred deduplication check can be integrated into the sequential selection algorithm in `exporter.py` (potentially alongside exposure caps).
  * [ ] Outline how to implement a user toggle to optionally *keep* duplicates in the final export if desired.
* **LLM Instructions**: Act as a Python Performance Engineer. Review the current duplicate removal logic in `engine.py`. Compare the computational cost of deduplicating within the generation phase versus carrying those duplicates through the pipeline and skipping them sequentially in `exporter.py`. Outline a strategy for this architectural change and summarize the expected impacts on overall pipeline speed.

### [Research] Data-Driven Randomization via Standard Deviation
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`
* **Context**: Instead of a global scalar for randomness (e.g., 25%), we want to sample from a normal distribution using a player's actual historical standard deviation stored in an `nba_fantasy_logs.db` SQLite database.
* **Acceptance Criteria**:
  * [ ] Determine how to efficiently read the SQLite data and merge it with the active DataFrame without bottlenecking the parallel workers.
  * [ ] Outline the updated `np.random.normal` formulation.
  * [ ] Define fallback logic for players missing historical standard deviation data (e.g., rookies or players with limited history).
  * [ ] Assess the expected impact on lineup diversity and projection accuracy compared to the current global scalar method.
* **LLM Instructions**: Act as a Data Engineer. Outline a strategy for loading historical standard deviations from an external SQLite file and integrating them into the `sim_proj` generation inside `engine.py`.

### [Research] Shift Lineup Metric Calculation to Engine Generator
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`, `src/nba_optimizer/ranker.py`
* **Context**: The `ranker.py` currently recalculates Total Projection and Total Ownership. To save time, we want to calculate these directly in `engine.py` during generation and save them to the `lineup-pool.csv`.
* **Acceptance Criteria**:
  * [ ] Evaluate memory/speed tradeoffs of doing this lookup inside `engine.py` vs. a vectorized Pandas operation in `ranker.py`.
* **LLM Instructions**: Act as a Python optimization expert. Read both `engine.py` and `ranker.py`. Analyze if moving the metric calculations (Sum Proj, Sum Own, Geomean Own) to the end of `engine.py` is faster or slower than keeping it as a vectorized merge operation in `ranker.py`. Provide your recommendation.

### [Research] GUI Framework Migration (Gooey -> PySimpleGUI / Others)
* **Status**: Not Started
* **Target Files**: `scripts/run_optimizer_gui.py`
* **Context**: Assess Python GUI frameworks to replace the current `Gooey` implementation, offering more flexibility for dynamic UI elements (like live progress bars, stop buttons, and real-time metric plotting).
* **Acceptance Criteria**:
  * [ ] Review PySimpleGUI, CustomTkinter, and PyQt/PySide.
  * [ ] Recommend the best framework for a multi-threaded data science pipeline.
* **LLM Instructions**: Act as a Python Frontend Developer. Compare Gooey, PySimpleGUI, and CustomTkinter for this specific project. Focus on ease of integration with a long-running multiprocessing script, system footprint, and custom styling capabilities. 

### [Implement] Consolidate Data Loading Logic
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`, `src/nba_optimizer/late_swapper.py`, `src/nba_optimizer/ranker.py`, `src/nba_optimizer/utils.py` (or a new `data_loader.py`)
* **Context**: `engine.py` and `late_swapper.py` currently have duplicate and slightly different `load_data()` implementations. Additionally, `ranker.py` imports `engine.load_data()`, creating tight coupling. This needs to be abstracted into a single, shared data-loading utility.
* **Acceptance Criteria**:
  * [ ] A single `load_data()` function handles CSV parsing for all modules.
  * [ ] `engine.py`, `late_swapper.py`, and `ranker.py` are updated to use this shared utility without breaking.
* **LLM Instructions**: Act as a Python Refactoring Expert. Extract the `load_data` logic from `engine.py` and `late_swapper.py` into a unified function within `utils.py` (or propose a new `data.py` module). Update all module imports and calls to use this new function. Ensure player context merging behaves correctly across the pipeline.

### [Implement] Standardize File Resolution Utilities
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`, `src/nba_optimizer/exposure_report.py`, `src/nba_optimizer/utils.py`
* **Context**: The codebase has fragmented ways of finding the newest files. `engine.py` uses a custom `get_latest_projections()` and `exposure_report.py` uses its own `get_latest_file()` using `getmtime`. We need to standardize all file resolution to use the existing `utils.get_latest_file()`.
* **Acceptance Criteria**:
  * [ ] `utils.get_latest_file()` supports `use_mtime=True` as a toggle.
  * [ ] Redundant file-finding functions in `engine.py` and `exposure_report.py` are replaced by the `utils.py` standard.
* **LLM Instructions**: Act as a Python Developer. Refactor `utils.get_latest_file()` to support timestamp sorting (`getmtime`) alongside its existing logic. Replace the redundant file fetching functions in `engine.py` and `exposure_report.py` with this central utility.

### [Design] Pipeline Run-ID Validation to Prevent Stale File Pickup
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`, `src/nba_optimizer/ranker.py`, `src/nba_optimizer/exporter.py`
* **Context**: Modules currently pick up the "latest file by timestamp." If the generation engine fails mid-run, the ranker might pick up a partial or stale `lineup-pool.csv` from a previous run. We need a mechanism to strictly link a pipeline execution from start to finish.
* **Acceptance Criteria**:
  * [ ] Outline a lightweight mechanism (e.g., passing a unique `run_id` string or utilizing row-count validation) to ensure the ranker only processes files generated by the immediately preceding engine run.
* **LLM Instructions**: Act as a Data Pipeline Architect. Review how files are handed off between `engine.py`, `ranker.py`, and `exporter.py`. Design a non-intrusive `run_id` linking system or validation step to guarantee the pipeline fails gracefully instead of processing stale data if an upstream step aborts. 

### [Design] Refactor and Decouple `engine.py`
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`
* **Context**: `engine.py` is over 400 lines and violates single-responsibility principles by mixing data loading, LP model construction, positional slotting, and multiprocessing orchestration.
* **Acceptance Criteria**:
  * [ ] Propose a clean module split (e.g., separating the PuLP formulation logic from the multiprocessing orchestration and the positional slotting logic).
* **LLM Instructions**: Act as a Python Software Architect. Analyze `engine.py`. Draft a plan to decompose this 400+ line file into focused, single-responsibility functions or internal modules without altering the underlying mathematical logic. Provide the proposed structure and wait for approval before writing code.

### [Implement] Add `pyproject.toml` for Standardized Execution
* **Status**: Completed
* **Target Files**: `pyproject.toml` (new), `scripts/run_optimizer.py`, `scripts/run_optimizer_gui.py`
* **Context**: The `scripts/` currently rely on a `sys.path.insert` hack to resolve the `nba_optimizer` package. We need to define the project formally using a `pyproject.toml` so it can be installed via `pip install -e .`.
* **Acceptance Criteria**:
  * [x] Create a standard `pyproject.toml` defining the project, dependencies, and script entry points.
  * [x] Remove the `sys.path.insert` hacks from the `scripts/` directory.
* **LLM Instructions**: Act as a Python Packaging Expert. Generate a `pyproject.toml` file mapping to the existing `src/` layout. Ensure script entry points for the CLI and GUI are defined. Provide instructions on removing the `sys.path` hacks.

### [Design] Unit Tests for Core LP Logic and Data Loading
* **Status**: Not Started
* **Target Files**: `tests/` (new), `src/nba_optimizer/engine.py`, `src/nba_optimizer/utils.py`
* **Context**: The project currently relies entirely on manual verification. We need to introduce automated unit tests to catch regressions, starting specifically with the mathematical LP constraint logic and the CSV parsing/merging.
* **Acceptance Criteria**:
  * [ ] Propose a testing strategy using `pytest` that feeds dummy/mock data into `generate_single_lineup` to ensure salary caps and positional constraints are respected.
* **LLM Instructions**: Act as a Senior QA Engineer. Draft a strategy for setting up a `pytest` suite for the `nba_optimizer`. Do not test the GUI or the orchestrator yet; focus solely on writing deterministic tests for the `PuLP` constraints in `engine.py` and the data loading in `utils.py`. Propose 3 specific test cases.

### [Research] Reduce Multiprocessing Serialization Overhead
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/engine.py`
* **Context**: The `ProcessPoolExecutor` in `engine.py` pickles the entire player pool DataFrame per worker, which creates significant serialization overhead on Windows environments as the pool scales.
* **Acceptance Criteria**:
  * [ ] Investigate Python's `multiprocessing.shared_memory` or strategies to pass only essential primitive data (like dicts or specific arrays) to the worker functions instead of full Pandas DataFrames.
* **LLM Instructions**: Act as a Python Performance Expert. Analyze the `concurrent.futures.ProcessPoolExecutor` implementation in `engine.py`. Detail the memory and time costs of pickling the DataFrame across workers on Windows. Propose the most efficient architectural fix to minimize IPC (Inter-Process Communication) overhead.

### [Implement] Vectorize Lineup Ranking Logic
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/ranker.py`
* **Context**: `ranker.py` loops through generated lineups using Pandas `iterrows()`, which creates an $O(n)$ bottleneck with a high constant factor. This needs to be converted into vectorized Pandas operations.
* **Acceptance Criteria**:
  * [ ] All calculations for summing projections, summing ownership, and geometric mean ownership are executed via vectorized Pandas methods.
  * [ ] `iterrows()` is completely removed.
* **LLM Instructions**: Act as a Pandas Data Scientist. Rewrite the `rank_lineups` function in `ranker.py` to eliminate loops/`iterrows()`. Implement the metric calculations using pure, vectorized Pandas DataFrame merges and operations.

### [Implement] Optimize Late Swapper LP Lookups
* **Status**: Comitted - To Be Tested
* **Target Files**: `src/nba_optimizer/late_swapper.py`
* **Context**: The late swapper is significantly slower at LP construction compared to the main engine because it uses Pandas `df.loc[i, ...]` lookups inside the constraint definition loops.
* **Acceptance Criteria**:
  * [x] The late swapper converts the DataFrame into standard Python dictionaries prior to the PuLP loop (matching the approach used in `engine.py`).
  * [ ] Prove improved speed on batch swap runs.
* **LLM Instructions**: Act as a Python Performance Engineer. Update `late_swapper.py`. Convert the iterative `df.loc[]` lookups within the `solve_late_swap_batch` constraint loops into fast Python dictionary lookups, mirroring the optimization pattern already used in `engine.py`.

### [Research] Player-Level Leverage Score (Ownership vs. Standard Deviation)
* **Status**: Not Started
* **Target Files**: `src/nba_optimizer/utils.py`, `src/nba_optimizer/ranker.py`, `src/nba_optimizer/config.py`
* **Context**: We want to introduce a new lineup metric that identifies high-variance leverage plays and fades "bad chalk." This will be achieved by calculating a risk-adjusted "Leverage Score" for each player based on their standard deviation, projected ownership, projection, and salary, which is then summed for the entire lineup. 
* **Acceptance Criteria**:
  * [ ] Draft a mathematical formula that accurately penalizes high-ownership/high-variance players (bad chalk) while rewarding low-ownership/high-variance players (leverage), weighted by their salary-implied value.
  * [ ] Detail the exact location in the data loading pipeline (e.g., `utils.load_data()`) where this metric should be pre-calculated and appended as a static column to the main player DataFrame.
  * [ ] Confirm that `ranker.py` will only need to perform a simple vectorized sum of this new column to score the lineup.
* **LLM Instructions**: Act as a Data Scientist specializing in Daily Fantasy Sports. Propose a mathematical formula to quantify "good vs. bad chalk" and "leverage" by evaluating a player's projected ownership against their historical standard deviation and salary-implied value. Explain how to pre-compute this as a static player-level column in pandas during data initialization so that `ranker.py` only needs to perform a simple, highly optimized vectorized sum.

### [Implement] Refactor Global Configuration State
* **Status**: Completed
* **Target Files**: `src/nba_optimizer/config.py`, `src/nba_optimizer/engine.py`, `src/nba_optimizer/late_swapper.py`, `src/nba_optimizer/ranker.py`, `src/nba_optimizer/exporter.py`, `scripts/run_optimizer.py`
* **Context**: `config.py` currently loads environment variables into global module-level variables upon import. This hardcodes the state, preventing isolated unit testing or running concurrent instances with different settings. We need to refactor this into an instantiated `Config` class.
* **Acceptance Criteria**:
  * [x] `config.py` is rewritten to use a `Config` class (using `dataclasses` or `pydantic`).
  * [x] All modules are updated to accept a `Config` instance (dependency injection) rather than importing global variables directly.
* **LLM Instructions**: Act as a Python Software Architect. Refactor `config.py` to define a configuration class instead of global variables. Trace all imports of `config.py` across the codebase (`engine.py`, `ranker.py`, `scripts/run_optimizer.py`, etc.) and update them to initialize and pass a configuration instance. Ensure the CLI arguments in the scripts still correctly override these class defaults.

### [Implement] Centralize Magic Strings and Positional Slots
* **Status**: Completed
* **Target Files**: `src/nba_optimizer/config.py` (or new `constants.py`), `src/nba_optimizer/engine.py`, `src/nba_optimizer/late_swapper.py`, `src/nba_optimizer/ranker.py`
* **Context**: Hardcoded lists of DraftKings roster slots (`["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]`) are duplicated across multiple files. They need to be moved to a single source of truth to prevent bugs and enable easier adaptation to other contest types or sports.
* **Acceptance Criteria**:
  * [x] A single constant or Enum representing the roster slots is defined in `config.py` or a dedicated `constants.py` file.
  * [x] All hardcoded positional arrays in `engine.py`, `late_swapper.py`, and `ranker.py` are replaced with a reference to this central constant.
* **LLM Instructions**: Act as a Python Refactoring Expert. Create a centralized constant for the DraftKings NBA roster slots in `config.py` or a new `constants.py` file. Search through `engine.py`, `late_swapper.py`, and `ranker.py`, and replace all hardcoded lists of these slots with the new central reference.

---

## Completed Tasks
* **[x] Research**: Investigate MILP options for generating multiple late swap options per lineup.
* **[x] Design**: Stream optimizer output to GUI in real-time.
* **[x] Implement**: Repo standardization (init.py, utils.py, etc.).
* **[x] Implement**: Change default arguments (-n = 2500, -r = 0.25, -pw 0.8, -gw 0.2).
* **[x] Implement**: Late swap batching to prevent duplication of lineups with same players locked.
* **[x] Documentation**: Update readme with exposure report information and late swap argument.
* **[x] Implement**: Standardize output files naming convention (prefer - to _).
* **[x] Implement**: Print exposures.
* **[x] Implement**: No oversample/heavily reduced, return number of dupes.
* **[x] Implement**: Print solver runtime.
* **[x] Implement**: Clean up folder structure.
* **[x] Implement**: Fix late swap.
* **[x] Implement**: Default min salary 49500.
* **[x] Implement**: Normally distributed randomization.
* **[x] Implement**: Display solver progress as % of requested lineups.