# GEMINI.md - NBA DFS Optimizer Context

## Project Overview
The **NBA DFS Optimizer** is a high-performance optimization pipeline designed to generate, rank, and export NBA lineups for DraftKings. It leverages linear programming (LP) to maximize projected fantasy points while adhering to salary caps, roster requirements, and multi-game constraints.

### Core Technologies
- **Language:** Python 3.x
- **Optimization:** [PuLP](https://coin-or.github.io/pulp/) with the [HiGHS](https://highs.dev/) solver.
- **Data Processing:** Pandas and NumPy.
- **Parallelism:** `concurrent.futures` and `multiprocessing` for high-speed lineup generation.

### Architecture
The project follows a modular pipeline orchestrated by `run_optimizer.py`:
1.  **Engine (`engine.py`):** Generates a pool of candidate lineups in parallel. It uses randomness to explore the solution space and ensures uniqueness between lineups.
2.  **Ranker (`ranker.py`):** Scores the generated pool using a weighted combination of projections, total ownership, and geometric mean ownership (to optimize for "leverage").
3.  **Exporter (`exporter.py`):** Maps the top-ranked lineups into a DraftKings-compatible `DKEntries.csv` template.
4.  **Late Swapper (`late_swapper.py`):** A specialized tool to re-optimize remaining roster slots for players whose games haven't started, preserving locked players.

---

## Building and Running

### Prerequisites
- Python installed on the system.
- HiGHS solver (installed automatically via `highspy` dependency).
- Access to the `C:\Users\jrank\Downloads` folder and Google Drive (configured paths).

### Installation
```bash
pip install -r requirements.txt
```

### Execution
The primary entry point is `run_optimizer.py`.

```bash
# Run with default settings (20 lineups, 10% randomness)
python run_optimizer.py

# Custom run: 50 lineups, 20% randomness, 2 min unique players
python run_optimizer.py -n 50 -r 0.2 -u 2
```

**Common Flags:**
- `-n`, `--num_lineups`: Number of lineups to generate.
- `-r`, `--randomness`: Variance applied to projections (0.0 - 1.0).
- `-u`, `--min_unique`: Minimum number of players that must differ between lineups.
- `-pw`, `-ow`, `-gw`: Weights for Projection, Ownership, and Geomean Ownership respectively.

---

## Development Conventions

### Configuration
Most scripts contain a `--- CONFIGURATION ---` section at the top. Key variables include:
- `ENTRIES_PATH`: Path to the source `DKEntries.csv`.
- `PROJS_DIR`: Directory containing `NBA-Projs-*.csv` files.
- `SALARY_CAP`: Default is 50,000.
- `ROSTER_SIZE`: Default is 8.

### Optimization Logic
- **Parallelization:** Lineup generation is parallelized across all available CPU cores.
- **Slotting:** Lineups are post-processed to ensure players are slotted into the most "flexible" positions (e.g., placing late-start players in the UTIL or late-eligible slots) to maximize late-swap potential.
- **Constraints:** Scripts strictly enforce DraftKings roster rules (PG, SG, SF, PF, C, G, F, UTIL) and the requirement to use players from at least 2 different games.

### Testing/Verification
- There is no formal test suite. Verification is currently performed by running the pipeline and checking the generated CSV outputs in the `Downloads` folder.
