# NBA DFS Optimizer - Usage Guide

This guide explains how to use the CLI tools to generate, score, and export NBA DFS lineups for DraftKings.

## **Quick Start (Recommended)**

The easiest way to run the entire workflow (Generate -> Rank -> Export) is using the main script:

```bash
# Generate 20 lineups with default settings
python run_optimizer.py
```

### **Customizing the Run**

You can customize the number of lineups, randomness, and ranking weights directly:

```bash
python run_optimizer.py --num_lineups 50 --randomness 0.2 --proj_weight 1.0 --geo_weight 0.5
```

---

## **Individual Modules**

If you want to run specific parts of the pipeline individually, use the scripts below.

### **1. Engine (`engine.py`)**
**Goal:** Generates a pool of valid, optimized lineups using vectorized simulation.

**Arguments:**
*   `--num_lineups` (int): Number of lineups to generate. Default: `10`.
*   `--randomness` (float): Percentage of random variance applied to projections (e.g., `0.15` = +/- 15%). Default: `0.1`.

**Example:**
```bash
python engine.py --num_lineups 100 --randomness 0.15
```
**Output:** Saves a CSV to `G:\My Drive\Documents\CSV-Exports\lineup-pools\lineup-pool-YYYY-MM-DD_HHMMSS.csv`.

### **2. Ranker (`ranker.py`)**
**Goal:** Scores and sorts the generated lineups based on weighted metrics.

**Arguments:**
*   `--proj_weight` (float): Weight for Total Projection Rank (Higher is better). Default: `0.85`.
*   `--own_weight` (float): Weight for Total Ownership Rank (Lower is better). Default: `0.0`.
*   `--geo_weight` (float): Weight for Geometric Mean Ownership Rank (Lower is better). Default: `0.15`.

**Example:**
```bash
python ranker.py --proj_weight 1.0 --own_weight 0.5 --geo_weight 0.5
```
**Output:** Saves a CSV to `G:\My Drive\Documents\CSV-Exports\lineup-pools\ranked-lineups-YYYY-MM-DD_HHMMSS.csv`.

### **3. Exporter (`exporter.py`)**
**Goal:** Maps the top-ranked lineups into your `DKEntries.csv` template for upload.

**Logic:**
*   Reads `DKEntries.csv` from your Downloads folder.
*   Counts how many valid entry slots exist.
*   Fills them with the top lineups from the most recent `ranked-lineups` file.

**Example:**
```bash
python exporter.py
```
**Output:** Saves `upload_ready_DKEntries-YYYY-MM-DD_HHMMSS.csv` to your **Downloads** folder.

---

## **Configuration**

To change file paths or core constraints (like Salary Cap), edit the `CONFIGURATION` section at the top of the respective Python files (`engine.py`, `ranker.py`, `exporter.py`).

**Key Constants:**
*   `SALARY_CAP`: Default `50000`.
*   `ROSTER_SIZE`: Default `8`.
*   `PROJS_DIR`: Directory where `NBA-Projs-*.csv` are located.
*   `ENTRIES_PATH`: Path to your downloaded `DKEntries.csv`.
