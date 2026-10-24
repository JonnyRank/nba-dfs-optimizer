# Jonny Rankin's NBA DFS Optimizer

A high-performance optimization pipeline designed to generate, rank, and export NBA lineups for DraftKings. It leverages linear programming (LP) to maximize projected fantasy points while adhering to salary caps, roster requirements, and multi-game constraints.

## Features

- **Linear Programming Optimization:** Uses [PuLP](https://coin-or.github.io/pulp/) with the [HiGHS](https://highs.dev/) solver for optimal roster construction.
- **Parallel Generation:** Rapidly generates candidate lineup pools using multi-core processing.
- **Customizable Lineup Ranking:** Scores lineups using a weighted combination of projections and ownership metrics.
- **Late Swap Support:** Re-optimizes remaining roster slots for players whose games haven't started.
- **DraftKings Integration:** Exports directly to a DK-compatible `DKEntries.csv` template.

## Architecture

The project follows a modular pipeline orchestrated by the `nba-dfs-optimizer` command (or `scripts/run_optimizer.py` wrapper):

1.  **Engine (`engine.py`):** Generates a pool of candidate lineups in parallel using randomness to explore the solution space.
2.  **Ranker (`ranker.py`):** Scores the generated pool based on user-defined weights for projections and ownership.
3.  **Exporter (`exporter.py`):** Maps the top-ranked lineups into a DraftKings-compatible template and saves it to your folder of choice.
4.  **Exposure Report (`exposure_report.py`):** Analyzes the exported lineups to calculate player exposures, projected ownership, and leverage.

## Installation

### Prerequisites
- Python 3.x
- HiGHS solver (installed automatically via the `highspy` dependency)

### Setup
Use `pip install -e .` as the standard install path. `requirements.txt` is kept only as a compatibility mirror for tools that still expect that file format.

1. Clone the repository.
2. Install the project and required dependencies:
   ```bash
   # Core CLI (recommended for headless / agent environments)
   pip install -e .

   # With GUI support (requires a desktop display)
   pip install -e .[gui]
   ```
3. Configure your environment:
   - Copy `.env.example` to `.env`.
   - Update the paths in `.env` to match your local directory structure.

## Usage

### The GUI

The GUI is the usual way to run the optimizer. It runs the same pipeline as the CLI, with the same settings.

**Launching**
- `pip install -e .[gui]`, then `nba-dfs-optimizer-gui` or `python scripts\run_optimizer_gui.py`.
- A desktop shortcut that runs the venv's `pythonw.exe` on `scripts\run_optimizer_gui.py` opens the GUI without a console window.
- `.env` is read the same way however the GUI is launched: it is found from the package's location, not the working directory, so no terminal or environment-variable steps are needed.

#### Settings

One table for the GUI and the CLI, in the order the GUI shows them. The GUI box label is the argument name.

| GUI box | CLI flag | Default | Stage(s) | What it does |
| :--- | :--- | :--- | :--- | :--- |
| `late_swap` | `--late_swap` | off | late swap | Re-optimize the unlocked slots of tonight's DKEntries instead of a full run. |
| `from_stage` | `--from` | generate | all | Stage to start at; earlier stages' latest outputs are reused. |
| `to_stage` | `--to` | export | all | Stage to stop after. |
| `num_lineups` | `-n`, `--num_lineups` | 2500 | generate | Lineups to generate for the pool. |
| `randomness` | `-r`, `--randomness` | 0.25 | generate | Random variance applied to projections (0.0-1.0). |
| `min_unique` | `-u`, `--min_unique` | 1 | assemble | Min unique players between any two entries. |
| `min_salary` | `-ms`, `--min_salary` | 49500 | generate | Min salary for a lineup. |
| `min_projection` | `-mp`, `--min_projection` | 10.0 | generate | Min projection for a player to be considered. |
| `proj_weight` | `-pw`, `--proj_weight` | 0.8 | rank | Weight for the projection rank. |
| `own_weight` | `-ow`, `--own_weight` | 0.0 | rank | Weight for the total-ownership rank. |
| `geo_weight` | `-gw`, `--geo_weight` | 0.2 | rank | Weight for the geomean-ownership rank. |
| `top_x` | `-t`, `--top_x` | 25 | export | Players shown in the exposure report (0 for all). |
| `slate_type` | `--slate-type` | main | all | Picks the projections folder and names the slate folder. |
| `entries` | `--entries` | blank (auto) | all | DKEntries file; blank uses the newest matching download. |
| `no_slate_folder` | `--no-slate-folder` | off | all | This run only: keep out of the night's capture (legacy exports layout). |
| `slate_dir` | `--slate-dir` | tonight's | all | Work in an existing slate folder, e.g. a past slate. |
| `max_caps` | `--max` | none | assemble | Max exposure `PLAYER=PCT` (percent of entries). |
| `max_all` | `--max-all` | none | assemble | Max exposure PCT for every player (a player's own `--max` replaces it). |
| `proj` | `--proj` | none | generate, rank | Projection override `PLAYER=VALUE` (name or DK ID). |
| `own` | `--own` | none | rank | Ownership override `PLAYER=VALUE`. |
| `min_caps` | `--min` | none | assemble | Min exposure `PLAYER=PCT`. |
| `clear_overrides` | `--clear-overrides` | none | rank | Drop inherited `--proj`/`--own` overrides. |
| `clear_caps` | `--clear-caps` | none | assemble | Drop inherited `--max`/`--min` caps (`all` also drops `--max-all`). |
| `reset_settings` | `--reset-settings` | off | rank, assemble | Inherit nothing: weights, overrides, caps and `-u` return to defaults. |
| `pool` | `--pool` | latest | rank | Lineup pool CSV for `--from rank`. |
| `ranked` | `--ranked` | latest | assemble | Ranked lineups CSV for `--from assemble`. |
| `assembled` | `--assembled` | latest | export | Assembled lineups CSV for `--from export`. |
| `seed` | `--seed` | fresh | generate | Base seed for the engine (a fresh one is printed and recorded). |

**How the boxes behave**
- The weight boxes and `min_unique` start filled in and are sent as shown. Clearing one on a `from_stage` run inherits the last run's value.
- The `proj`, `own`, `max_caps` and `min_caps` boxes take `;`-separated lists, e.g. `Dylan Harper=80; OG Anunoby=50`.
- The clear boxes take `all` or `;`-separated player names.
- A blank `entries` box means auto-pick: the newest `DKEntries*.csv` in Downloads from the last 24 h whose players match the slate type's projections.
- Settings carry forward on `from_stage` runs; `reset_settings` undoes that.

**Inputs per slate type.** `main` reads `NBA_PROJS_DIR`; any other type reads the sibling folder `<NBA_PROJS_DIR>-<type>` (e.g. `projections-night`) or `NBA_PROJS_DIR_<TYPE>`. The newest export by the timestamp in its name is used, and a file named for another type is skipped. The DKEntries and projections must share their players, and the DKEntries must belong to the slate folder, or the run stops before anything is written.

**What a run prints, in order**
1. The inputs: `Slate type: …`, `Projections: …`, `DKEntries: …`.
2. The Effective settings block (each value and where it came from).
3. The phase headers and the progress bar (driven by `Lineups generated: N%`).
4. The assembly summary.
5. The exposure report.

Outputs land in the slate folder (`NBA_DATA_ROOT\<date>_classic_<type>`); the upload-ready CSV goes to `NBA_OUTPUT_DIR`.

**Recipes**
- *A normal run:* set the weights and caps you want; leave `from_stage` at generate and `entries` blank.
- *Re-rank with new weights:* `from_stage` = rank, new weights.
- *Change caps or `min_unique` only:* `from_stage` = assemble. Set `to_stage` = assemble to preview without exporting.
- *Re-export an earlier assembly:* `from_stage` = export, `assembled` = that file.
- *An alternate slate:* `slate_type` = night (or the night's type), `entries` blank.
- *An experiment that stays out of the night's capture:* tick `no_slate_folder`.

For internals see [`docs/codebase/ARCHITECTURE.md`](docs/codebase/ARCHITECTURE.md).

### The Orchestrator
The easiest way to run the full pipeline is using the `nba-dfs-optimizer` console command (installed via `pip install -e .`) or `scripts/run_optimizer.py`. This runs the Engine, Ranker, Exporter, and Exposure Report sequentially.

When run through the orchestrator, each stage passes its output file path directly to the next stage. This means a stale output from a previous failed run cannot be silently picked up between stages. Each individual stage (`ranker.py`, `exporter.py`, `exposure_report.py`) still supports standalone invocation via `python -m nba_optimizer.<module>`, in which case it falls back to resolving the most recent matching file from disk.

```bash
# Basic run (default settings)
nba-dfs-optimizer

# Custom run (2000 lineups, 12 min projection, 25% randomness, projection weight 80%, geomean weight 20%, top 25 exposures displayed)
nba-dfs-optimizer -n 2000 -mp 12 -r 0.25 -pw 0.8 -gw 0.2 -t 25
```

The arguments are listed in the [settings table](#settings) above, shared with the GUI.

### Exposure Report (`exposure_report.py`)
Generates a detailed breakdown of player exposures from your latest export, comparing your exposure to projected ownership to identify leverage points. This report is automatically generated at the end of an `nba-dfs-optimizer` run, but can also be run standalone:

```bash
# Run standalone (auto-detects latest standard or late-swap export)
python -m nba_optimizer.exposure_report

# Show only top 10 exposures
python -m nba_optimizer.exposure_report --top_x 10

# Use a specific entries file
python -m nba_optimizer.exposure_report --entries_file path/to/exports/specific-entries-file.csv
```

### Late Swap (`late_swapper.py`)
Use this tool after the slate has started to re-optimize remaining slots. It can be run independently or via the main orchestrator:

1. Download a fresh `DKEntries.csv` from DraftKings.
2. Ensure you have the latest projections available.
3. Run the script via Orchestrator or stand-alone:

```bash
# Run via Orchestrator
nba-dfs-optimizer --late_swap

# Run standalone
python -m nba_optimizer.late_swapper
```

## Configuration
The project uses environment variables for path configuration to avoid exposing local directory structures. You can set these in a `.env` file:

- `NBA_PROJS_DIR`: Directory containing the main slate's `NBA-Projs-*.csv` files.
- `NBA_PROJS_DIR_<TYPE>` (optional, e.g. `NBA_PROJS_DIR_NIGHT`): another slate type's projections folder, when it isn't the sibling `<NBA_PROJS_DIR>-<type>`.
- `NBA_DOWNLOADS_DIR` (optional, default `~/Downloads`): where DKEntries downloads land; searched for the auto-picked DKEntries and by `nba-dfs-capture finalize`.
- `NBA_ENTRIES_PATH` (optional): an extra DKEntries candidate outside the downloads folder.
- `NBA_LINEUP_DIR`: Base directory where intermediate `lineup-pools` and `ranked-lineups` subdirectories will be created.
- `NBA_OUTPUT_DIR`: Directory where the final upload-ready files are saved.

Core roster constants (salary cap, roster size, etc.) are managed in `config.py`.

## Testing

A small, deterministic test suite covers shared CSV-parsing helpers and the
core LP constraints used by the engine (roster size, salary band, positional
eligibility, and minimum games). It is a safety rail for refactors, not a
substitute for manual verification against real DraftKings exports.

Install the dev dependencies and run the suite:

```bash
pip install -e .[dev]
python -m pytest -q
```

Run a focused subset:

```bash
python -m pytest tests/test_engine_constraints.py tests/test_utils.py -q
```

The suite also covers late-swap lock handling and enforced minimum games
(`tests/test_late_swap.py`) and explicit artifact handoff between pipeline stages
(`tests/test_pipeline_artifacts.py`).

## Development Notes

- **Shared data loading.** DKEntries and projection parsing is consolidated in
  `src/nba_optimizer/utils.py` (`parse_dk_entries`, `merge_player_pool`) and shared by the
  engine, ranker, and late swapper. The engine and ranker merge the player pool with an inner
  join; the late swapper uses a left join and derives the matchup `Game` column itself.
- **Claude Code on the web.** A `SessionStart` hook (`.claude/hooks/session-start.sh`, wired in
  `.claude/settings.json`) bootstraps a `.venv` and installs `pip install -e .[dev]` for remote
  cloud sessions. It runs only when `CLAUDE_CODE_REMOTE=true` and is a no-op on local machines,
  so local development is unaffected.
