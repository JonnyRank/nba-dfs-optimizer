# *WARNING: Late Swap Script Is WIP - Do Not Use*
# Jonny Rankin's NBA DFS Optimizer

A high-performance optimization pipeline designed to generate, rank, and export NBA lineups for DraftKings. It leverages linear programming (LP) to maximize projected fantasy points while adhering to salary caps, roster requirements, and multi-game constraints.

## Features

- **Linear Programming Optimization:** Uses [PuLP](https://coin-or.github.io/pulp/) with the [HiGHS](https://highs.dev/) solver for optimal roster construction.
- **Parallel Generation:** Rapidly generates candidate lineup pools using multi-core processing.
- **Smart Ranking:** Scores lineups using a weighted combination of projections and ownership metrics (Total Ownership and Geometric Mean) to find high-leverage builds.
- **Late Swap Support:** Re-optimizes remaining roster slots for players whose games haven't started.
- **DraftKings Integration:** Exports directly to a DK-compatible `DKEntries.csv` template.

## Architecture

The project follows a modular pipeline orchestrated by `run_optimizer.py`:

1.  **Engine (`engine.py`):** Generates a pool of candidate lineups in parallel using randomness to explore the solution space while ensuring uniqueness.
2.  **Ranker (`ranker.py`):** Scores the generated pool based on user-defined weights for projections and ownership.
3.  **Exporter (`exporter.py`):** Maps the top-ranked lineups into a DraftKings-compatible template and saves it to your Downloads folder.

## Installation

### Prerequisites
- Python 3.x
- HiGHS solver (installed automatically via the `highspy` dependency)

### Setup
1. Clone the repository.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure your environment:
   - Copy `.env.example` to `.env`.
   - Update the paths in `.env` to match your local directory structure.

## Usage

### The Orchestrator
The easiest way to run the full pipeline is using `run_optimizer.py`. This script runs the Engine, Ranker, and Exporter sequentially.

```bash
# Basic run (20 lineups, default settings)
python run_optimizer.py

# Custom run (50 lineups, 20% randomness, 2 min unique players)
python run_optimizer.py -n 50 -r 0.2 -u 2
```

#### Available Arguments:
| Long Flag | Short Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `--num_lineups` | `-n` | 20 | Total lineups to generate and export. |
| `--randomness` | `-r` | 0.1 | Random variance applied to projections (0.0 to 1.0). |
| `--min_unique` | `-u` | 1 | Min unique players that must differ between every lineup. |
| `--proj_weight" | `-pw` | 0.85 | Weight for the Projection Rank in final scoring. |
| `--own_weight` | `-ow` | 0.0 | Weight for the Total Ownership Rank. |
| `--geo_weight` | `-gw` | 0.15 | Weight for the Geomean Ownership Rank. |

### Late Swap (`late_swapper.py`)
Use this tool after the slate has started to re-optimize remaining slots:
1. Download a fresh `DKEntries.csv` from DraftKings.
2. Ensure you have the latest projections available.
3. Run the script:
   ```bash
   python late_swapper.py
   ```

## Configuration
The project uses environment variables for path configuration to avoid exposing local directory structures. You can set these in a `.env` file:

- `NBA_ENTRIES_PATH`: Path to your source `DKEntries.csv`.
- `NBA_PROJS_DIR`: Directory containing your `NBA-Projs-*.csv` files.
- `NBA_LINEUP_DIR`: Directory where intermediate lineup pools are stored.
- `NBA_OUTPUT_DIR`: Directory where the final upload-ready files are saved.

Core roster constants (salary cap, roster size, etc.) are managed in `config.py`.
