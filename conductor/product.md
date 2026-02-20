# Initial Concept
NBA DFS Optimizer (Existing Project)

# NBA DFS Optimizer Product Guide

## Vision
A high-performance optimization pipeline tailored for professional DFS players and advanced analysts. This tool provides granular control over lineup generation, prioritizing leverage, speed, and late-swap flexibility to maximize edge in GPP contests.

## Target Audience
- **Professional DFS Players:** Those managing high-volume, multi-entry strategies.
- **Advanced Analysts:** Users who require extensive control over weights, constraints, and roster logic.

## Core Differentiators
- **Leverage Metrics:** Integrated ownership and geometric mean metrics to identify high-upside, low-owned builds.
- **Speed:** Rapid generation of candidate lineup pools using multi-core processing.
- **Flexibility:** Smart roster slotting designed for maximum late-swap flexibility.

## Key Features
- **Late Swap (WIP):** Tools to re-optimize remaining roster slots for players whose games haven't started.
- **Groups & Constraints:** Support for min/max rules on specified player sets (e.g., stacking or fading specific teams/games).
- **Exposure Management:** Fine-grained control over player exposure percentages during both solver execution and post-generation ranking.
- **Streamlit UI:** A modern interface for uploading projections, adjusting weights, and reviewing results before exporting.

## Data Strategy
- **Manual CSV Upload:** Leverages existing workflows using `NBA-Projs-*.csv` and `DKEntries.csv` files for maximum user control and platform flexibility.
