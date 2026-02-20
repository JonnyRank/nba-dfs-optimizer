# Specification: Complete and Validate Late Swap Functionality

## Overview
The goal of this track is to finalize the `late_swapper.py` script, which is currently marked as Work-In-Progress (WIP). This script must allow users to re-optimize remaining roster slots in an existing `DKEntries.csv` file, preserving players whose games have already started (locked players) while maximizing the projected fantasy points of the remaining slots.

## User Stories
- **As an Advanced Analyst**, I want to re-optimize my lineups after the slate has started to account for late-breaking news or unexpected player performance.
- **As a Professional DFS Player**, I want to ensure my late-swap lineups are as mathematically optimal as possible while respecting DraftKings' roster constraints and my original locked players.

## Functional Requirements
- **Locking Logic:** Correct identify "locked" players based on game start times.
- **Optimization:** Re-run the PuLP solver for only the remaining open slots in each lineup.
- **Constraint Adherence:** Maintain all DraftKings roster rules (PG, SG, SF, PF, C, G, F, UTIL) and multi-game requirements.
- **CSV Processing:** Read from a standard `DKEntries.csv` and export a new, valid version for upload.
- **Projection Integration:** Use the latest available projections from the specified directory.

## Technical Constraints
- **Language:** Python 3.x
- **Libraries:** PuLP, Pandas, NumPy
- **Input:** `DKEntries.csv` (source entries), `NBA-Projs-*.csv` (projections)
- **Output:** A updated CSV file compatible with DraftKings' late-swap upload.

## Success Criteria
- The solver successfully generates valid lineups for all entries in the input CSV.
- Locked players are never swapped out.
- The new lineups have higher or equal total projected points than the original (assuming projections haven't drastically dropped for remaining players).
- The exported CSV is accepted by DraftKings without errors.
