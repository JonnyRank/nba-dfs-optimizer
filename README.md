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

1.  **Engine (`engine.py`):** Generates a pool of candidate lineups in parallel using randomness to explore the solution space while ensuring uniqueness.
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
   pip install -e .
   ```
3. Configure your environment:
   - Copy `.env.example` to `.env`.
   - Update the paths in `.env` to match your local directory structure.

## Usage

### The Orchestrator
The easiest way to run the full pipeline is using the `nba-dfs-optimizer` console command (installed via `pip install -e .`) or `scripts/run_optimizer.py`. This runs the Engine, Ranker, Exporter, and Exposure Report sequentially.

```bash
# Basic run (default settings)
nba-dfs-optimizer

# Custom run (2000 lineups, 12 min projection, 25% randomness, projection weight 80%, geomean weight 20%, top 25 exposures displayed)
nba-dfs-optimizer -n 2000 -mp 12 -r 0.25 -pw 0.8 -gw 0.2 -t 25
```

#### Available Arguments:
| Long Flag | Short Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `--num_lineups` | `-n` | 2500 | Total lineups to generate and export. |
| `--min_unique` | `-u` | 1 | Minimum unique players between every lineup. |
| `--min_projection` | `-mp` | 10.0 | Minimum projection for a player to be considered. |
| `--min_salary` | `-ms` | 49500 | Minimum salary for a lineup. |
| `--randomness` | `-r` | 0.25 | Random variance applied to projections (0.0 to 1.0). |
| `--proj_weight` | `-pw` | 0.8 | Weight for the Projection Rank in final scoring. |
| `--own_weight` | `-ow` | 0.0 | Weight for the Total Ownership Rank. |
| `--geo_weight` | `-gw` | 0.2 | Weight for the Geomean Ownership Rank. |
| `--top_x` | `-t` | 25 | Display only top X exposed players in report (Use 0 to display all players used in export). |
| `--late_swap` | | False | Run late swap re-optimization instead of full generation. |

### Exposure Report (`exposure_report.py`)
Generates a detailed breakdown of player exposures from your latest export, comparing your exposure to projected ownership to identify leverage points. This report is automatically generated at the end of an `nba-dfs-optimizer` run, but can also be run standalone:

```bash
# Run standalone (shows all exposures)
python -m nba_optimizer.exposure_report

# Show only top 10 exposures
python -m nba_optimizer.exposure_report --top_x 10
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

- `NBA_ENTRIES_PATH`: Path to your source `DKEntries.csv`.
- `NBA_PROJS_DIR`: Directory containing your `NBA-Projs-*.csv` files.
- `NBA_LINEUP_DIR`: Base directory where intermediate `lineup-pools` and `ranked-lineups` subdirectories will be created.
- `NBA_OUTPUT_DIR`: Directory where the final upload-ready files are saved.

Core roster constants (salary cap, roster size, etc.) are managed in `config.py`.
