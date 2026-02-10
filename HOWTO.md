# NBA DFS Optimizer - Usage Guide

This project provides a high-performance pipeline for generating, ranking, and exporting NBA DFS lineups for DraftKings.

---

## **1. Core Workflow (The Orchestrator)**

The easiest way to run the full pipeline is using `run_optimizer.py`. This script runs the **Engine**, **Ranker**, and **Exporter** sequentially.

```bash
# Basic run (20 lineups, default settings)
python run_optimizer.py

# Custom run using abbreviated flags (50 lineups, 20% randomness, 2 min unique players)
python run_optimizer.py -n 50 -r 0.2 -u 2
```

### **Available Arguments:**
| Long Flag | Short Flag | Default | Description |
| :--- | :--- | :--- | :--- |
| `--num_lineups` | `-n` | 20 | Total lineups to generate and export. |
| `--randomness` | `-r` | 0.1 | Random variance applied to projections (0.0 to 1.0). |
| `--min_unique` | `-u` | 1 | Min unique players that must differ between every lineup. |
| `--proj_weight` | `-pw` | 0.85 | Weight for the Projection Rank in final scoring. |
| `--own_weight` | `-ow` | 0.0 | Weight for the Total Ownership Rank. |
| `--geo_weight` | `-gw` | 0.15 | Weight for the Geomean Ownership Rank. |

---

## **2. Individual Modules**

### **The Engine (`engine.py`)**
**Goal:** Generates a pool of valid lineups in parallel using your computer's full CPU power.
*   **Arguments:** Supports `-n`, `-r`, and `-u`.
*   **Parallel Mode:** Uses all available CPU cores to generate candidates.
*   **Oversampling:** Generates more lineups than requested and then filters them to strictly satisfy the `min_unique` constraint.

### **The Ranker (`ranker.py`)**
**Goal:** Scores the pool based on your strategy.
*   **Geomean Ownership:** Penalizes "chalky" lineups by looking at the geometric mean of ownership, helping you find lower-duplicated builds.

### **The Exporter (`exporter.py`)**
**Goal:** Maps the best lineups into your `DKEntries.csv` template.
*   **Safety:** Preserves `Entry ID` and `Contest ID` exactly to prevent DraftKings upload errors.
*   **Output:** Saves a timestamped file to your **Downloads** folder (e.g., `upload_ready_DKEntries-YYYYMMDD_HHMMSS.csv`).

---

## **3. Late Swap (`late_swapper.py`)**

Use this tool after the slate has started to re-optimize remaining slots for players whose games haven't begun.

**How it works:**
1.  Download a fresh `DKEntries.csv` from DraftKings (which will have `(LOCKED)` next to players in started games).
2.  Ensure you have the latest projections in your Drive folder.
3.  Run the script:
    ```bash
    python late_swapper.py
    ```
4.  The script will identify every locked player in every entry and find the absolute best mathematical completion for the remaining slots.
5.  **Output:** Saves a timestamped `late-swap-entries-*.csv` to your **Downloads** folder.

---

## **4. Configuration & Paths**

Most settings are managed via CLI arguments, but core paths and roster rules are located in the `CONFIGURATION` section at the top of each script:

*   `ENTRIES_PATH`: Where your `DKEntries.csv` template lives.
*   `PROJS_DIR`: Where your `NBA-Projs-*.csv` files are stored.
*   `SALARY_CAP`: Default `$50,000`.
*   `ROSTER_SIZE`: Default `8`.
*   `MIN_GAMES`: Default `2`.
