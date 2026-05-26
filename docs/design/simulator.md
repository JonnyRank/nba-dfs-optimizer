# Design Doc: `src/nba_optimizer/simulator.py`

**Status:** Proposed — not yet implemented  
**Last updated:** 2026-05-25

---

## 1. Purpose

`simulator.py` would add a **Monte Carlo contest simulation stage** to the existing pipeline. Its job is to answer a question the current pipeline cannot: *given a pool of generated and ranked lineups, which ones perform best under uncertainty and real contest structure?*

The ranker already scores lineups deterministically using projected ownership and total projection. The simulator would complement this by running thousands of stochastic draws from player outcome distributions, then aggregating lineup-level metrics — mean score, score ceiling, win frequency, top-1% frequency, cash frequency, and expected payout/ROI — across those simulated contests.

The goal for an initial implementation is **lineup-pool simulation only**: simulate outcomes for the user's own generated lineups, not a full GPP contest field. Contest-field simulation, duplicate-aware payout splitting, and correlation modeling are planned but deferred to later phases.

---

## 2. Scope

### In scope (Phase 1)

- Load player projections and standard deviations from the existing merged player data.
- Load a lineup pool from `lineup-pool-{timestamp}.csv` or `ranked-lineups-{timestamp}.csv`.
- Simulate player fantasy scores using independent normal draws.
- Aggregate per-lineup metrics: mean, standard deviation, p90/p95, and within-pool rank frequencies.
- Write simulation results to a timestamped output CSV.
- Expose a `run(cfg, lineup_file=None, iterations=10000)` function matching the existing module interface.

### Out of scope for Phase 1

- Contest-field simulation (generating or loading opponent lineups).
- Duplicate-aware payout splitting.
- Correlated game-level simulation (multivariate normal draws).
- Late-swap / live game-state simulation.
- Automatic re-ranking based on simulation output (ranking remains in `ranker.py`).
- Any modification to `engine.py`, `ranker.py`, or `exporter.py`.

---

## 3. Architecture Fit

The simulator slots in as an **optional post-ranking analysis stage**, not a replacement for any existing stage. It reads ranked lineups from the file system and writes its own timestamped output, following the same artifact-based inter-stage contract every other module uses.

**Updated system flow (with simulator as optional stage):**

```text
DKEntries.csv + NBA-Projs-*.csv
       │
       ▼
[Engine] ── parallel LP solve ──► lineup-pool-{timestamp}.csv
       │
       ▼
[Ranker] ── weighted rank ──► ranked-lineups-{timestamp}.csv
       │
       ▼
[Simulator] ── Monte Carlo ──► sim-lineup-metrics-{timestamp}.csv  ← optional stage
       │
       ▼
[Exporter] ── DK template fill ──► upload-ready-DKEntries-{timestamp}.csv
       │
       ▼
[Exposure Report] ──► console output
```

The simulator is invoked after the ranker and before or instead of the exporter, or run standalone against any existing lineup pool file. The orchestrator (`orchestrator.py`) would conditionally call `simulator.run()` based on a new `--simulate` flag, analogous to how `--late_swap` routes to `late_swapper.run()` today.

The simulator must **not**:
- Import from or depend on `engine.py`, `ranker.py`, `exporter.py`, or `late_swapper.py` for anything other than shared utilities.
- Perform LP lineup generation.
- Reformat lineups for DraftKings export.
- Compute or apply ranking weights.

---

## 4. Module Responsibilities

| Owns | Must not own |
|------|-------------|
| Loading player distributions (projection, std dev) | Lineup generation (LP) |
| Loading a lineup pool from a file | Ranking formula or weights |
| Simulating player fantasy outcomes (Monte Carlo) | DK template formatting |
| Computing per-lineup simulation metrics | Stale-file resolution (delegate to `utils.py`) |
| Writing `sim-lineup-metrics-{timestamp}.csv` | Game-state ingestion or live scoring |
| Printing simulation progress to console | Bayesian posterior updates (late-swap simulation) |

---

## 5. Phased Implementation Plan

### Phase 1 — Independent lineup-pool simulation (recommended starting point)

Simulate outcomes for the user's own lineup pool only. No contest field, no correlations, no payouts.

**Player outcome model:**

$$X_i \sim \mathcal{N}(\mu_i,\ \sigma_i^2)$$

where:
- $\mu_i$ = player projected fantasy points
- $\sigma_i$ = player standard deviation (from projection CSV column or fallback rule)

**Lineup score per simulation:**

$$S_{L,t} = \sum_{i \in L} X_{i,t}$$

**Metrics per lineup over $T$ iterations:**

- Mean score: $\bar{S}_L = \frac{1}{T}\sum_t S_{L,t}$
- Standard deviation of score: $\sigma_{S_L}$
- p90 / p95: empirical 90th/95th percentile of $S_{L,t}$
- Within-pool top-1% rate: fraction of iterations where lineup $L$ ranked in the top 1% of all lineups in the pool
- Within-pool top-10% rate: fraction of iterations where lineup $L$ ranked in the top 10% of all lineups in the pool

**Output:** `sim-lineup-metrics-{timestamp}.csv` with one row per lineup.

---

### Phase 2 — Contest-field simulation

Add a field of opponent lineups to simulate against. Field can be:
1. User-supplied via `--field_file` (CSV of DK-format lineups)
2. Ownership-weighted stochastic generation (heuristic field construction)

**New metrics per lineup:**
- Contest win % (first place across field + user lineups)
- Top-1% finish %
- Cash % (paid places)

**New inputs:** optional `--field_file` and `--field_size` parameters in `main()`.

---

### Phase 3 — Duplicate-aware payout splitting

When the same lineup appears multiple times in the contest field, duplicates split prize payouts across the ranks they occupy:

$$\text{payout per duplicate} = \frac{1}{k}\sum_{m=r}^{r+k-1} p_m$$

where $k$ duplicates occupy ranks $r$ through $r+k-1$ with payouts $p_r, \ldots, p_{r+k-1}$.

**New inputs:** optional payout CSV (`--payout_file`) mapping rank to prize amount.

**New metrics per lineup:**
- Expected payout (average across simulations)
- ROI %: $\frac{\overline{\text{net payout}}}{\text{entry fee}} \times 100$

---

### Phase 4 — Correlated game-level simulation

Instead of independent normal draws, sample player outcomes jointly within each game using a multivariate normal:

$$X_{\text{game}} \sim \mathcal{N}(\mu_{\text{game}},\ \Sigma_{\text{game}})$$

**Covariance matrix construction:**

$$\Sigma_{ij} = \rho_{ij} \cdot \sigma_i \cdot \sigma_j, \quad \Sigma_{ii} = \sigma_i^2$$

where $\rho_{ij}$ is a position-pair correlation coefficient (configurable via `config.py` or a correlation table CSV).

**PSD repair:** Before sampling, apply eigenvalue clipping to ensure $\Sigma$ is positive semidefinite:
1. Decompose: $\Sigma = Q\Lambda Q^\top$
2. Clip: $\Lambda^+ = \max(\Lambda, 0)$
3. Reconstruct: $\Sigma^* = Q\Lambda^+ Q^\top$

This is Phase 4 rather than Phase 1 because validating correlated simulation outputs is harder — the simpler independent model is easier to sanity-check and should be proven first.

---

### Phase 5 — Late-swap / live-state simulation (future, separate module)

Adapt the simulator for partially completed contests using Bayesian-inspired projection updates. This would live in a separate `late_swap_simulator.py` rather than extending `simulator.py`, following the same boundary principle that `late_swapper.py` is separate from `engine.py`. Key additions:
- Ingest live game-state data (actual points, minutes played, minutes remaining).
- Update player projected mean and variance using game-progress weighting.
- Treat completed-game players as deterministic (variance = 0).

---

## 6. Proposed Functions and Interfaces

```python
# src/nba_optimizer/simulator.py

def load_simulation_inputs(
    cfg: Config,
    lineup_file: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load player projection data and lineup pool.

    Returns:
        df_players: one row per player with projection, std dev, matchup/game_id
        df_lineups: one row per lineup with player name columns
    """

def build_player_distribution_inputs(
    df_players: pd.DataFrame,
    default_stddev_factor: float = 0.25
) -> dict[str, tuple[float, float]]:
    """
    Build {player_name: (mean, stddev)} lookup from player DataFrame.
    Applies default stddev = projection * default_stddev_factor for missing values.
    """

def simulate_player_outcomes(
    player_dist: dict[str, tuple[float, float]],
    iterations: int = 10000,
    seed: int | None = None
) -> dict[str, np.ndarray]:
    """
    Draw T independent normal samples per player.
    Returns {player_name: np.ndarray of shape (iterations,)}.
    """

def score_lineups_from_samples(\n    df_lineups: pd.DataFrame,\n    player_samples_dict: dict[str, np.ndarray],
    player_cols: list[str]
) -> np.ndarray:
    """
    Compute lineup scores for each simulation iteration.
    Returns np.ndarray of shape (num_lineups, iterations).
    """

def summarize_lineup_results(
    scores_array: np.ndarray,
    lineup_ids: list[str | int]
) -> pd.DataFrame:
    """
    Aggregate per-lineup simulation metrics.
    Returns DataFrame with columns:
        lineup_id, mean_score, stddev_score, p90_score, p95_score,
        pool_top1pct, pool_top10pct
    """

def write_simulation_report(
    df_results: pd.DataFrame,
    cfg: Config,
    prefix: str = "sim-lineup-metrics"
) -> str:
    """
    Write results to timestamped CSV in cfg.output_dir.
    Returns the output file path.
    """

def run(
    cfg: Config,
    lineup_file: str | None = None,
    iterations: int = 10000,
    seed: int | None = None
) -> None:
    """
    Main entry point. Matches the run(cfg) interface of all other modules.
    Orchestrates load → simulate → summarize → write.
    """

def main() -> None:
    """
    argparse entry point for standalone execution:
        python -m nba_optimizer.simulator --lineup_file ranked-lineups-xxx.csv --iterations 10000
    """
```

---

## 7. Input and Output Artifacts

### Inputs

| Artifact | Source | Required | Notes |
|----------|--------|----------|-------|
| `ranked-lineups-{timestamp}.csv` or `lineup-pool-{timestamp}.csv` | Ranker or Engine output | Yes (one of the two) | Resolved via `utils.get_latest_file()` if `lineup_file` not specified |
| Player projection CSV (`NBA-Projs-*.csv`) | User-provided | Yes | Must include `StdDev` column or fallback to `Projection * factor` |
| Payout CSV | User-provided | No (Phase 3+) | Maps contest rank to prize amount |
| Field lineups CSV | User-provided | No (Phase 2+) | DK-format lineup entries for opponent field |

### Outputs

| Artifact | Path pattern | Phase | Notes |
|----------|-------------|-------|-------|
| Lineup simulation metrics | `{output_dir}/sim-lineup-metrics-{timestamp}.csv` | Phase 1+ | One row per lineup |
| Player exposure in top simulated lineups | `{output_dir}/sim-player-exposure-{timestamp}.csv` | Phase 2+ | Optional |
| Contest summary metrics | Console output | Phase 2+ | Win %, cash %, top-1% summary |

### `sim-lineup-metrics-{timestamp}.csv` schema (Phase 1)

| Column | Type | Description |
|--------|------|-------------|
| `lineup_id` | int | Row index from lineup pool file |
| `players` | str | Comma-separated player names (for reference) |
| `mean_score` | float | Mean simulated lineup score across all iterations |
| `stddev_score` | float | Standard deviation of simulated lineup scores |
| `p90_score` | float | 90th percentile simulated score |
| `p95_score` | float | 95th percentile simulated score |
| `pool_top1pct` | float | Fraction of iterations where this lineup ranked in the pool's top 1% |
| `pool_top10pct` | float | Fraction of iterations where this lineup ranked in the pool's top 10% |

Phase 2+ additions: `contest_wins`, `top1pct_count`, `cash_count`, `expected_payout`, `roi_pct`.

---

## 8. Data Requirements

### Required player columns

| Column | Source | Fallback |
|--------|--------|----------|
| `Name` | Projection CSV | — |
| `Fpts` or `Projection` | Projection CSV | None — required |
| `StdDev` | Projection CSV | `Projection * 0.25` (configurable) |
| `Own%` or `Ownership` | Projection CSV | Not required for Phase 1 |
| `Matchup` or `Game` | DKEntries.csv or projection CSV | Not required until Phase 4 (correlation) |

### Config additions

The following fields would be added to the `Config` dataclass in `config.py`:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `sim_iterations` | int | `10000` | Number of Monte Carlo draws |
| `sim_stddev_factor` | float | `0.25` | Fallback stddev as fraction of projection |
| `sim_seed` | int \| None | `None` | RNG seed for reproducibility |

---

## 9. Algorithm Choices for Phase 1

### Why independent normal draws first

The independent normal model ($X_i \sim \mathcal{N}(\mu_i, \sigma_i^2)$) is the right starting point because:

1. **Easiest to validate**: given known $\mu$ and $\sigma$, the expected lineup score distribution is analytically tractable — the simulated mean should converge to $\sum_i \mu_i$ and the simulated standard deviation should converge to $\sqrt{\sum_i \sigma_i^2}$.
2. **No correlation matrix to construct or repair**, eliminating a significant source of implementation complexity and numeric instability.
3. **Fast**: `numpy.random.normal` is vectorized; drawing `players × iterations` samples in one call is efficient.
4. **Still useful**: even without correlation, simulated ceiling and floor scores identify which lineups have the best tail upside within the pool.

Correlation (Phase 4) is deferred because validating that the covariance matrix is correctly constructed and PSD-repaired requires manual inspection against known game outcomes — appropriate once the simpler model is proven.

### Lineup scoring

Lineup scores are computed as a matrix multiply:

```python
# player_matrix: (num_lineups, num_players), binary membership
# samples: (num_players, iterations)
scores = player_matrix @ samples  # shape: (num_lineups, iterations)
```

This vectorized operation replaces any per-lineup loop.

### RNG seeding

Pass an optional `seed` parameter to `np.random.default_rng(seed)` to allow reproducible simulation runs during development and validation. Default is unseeded (non-reproducible) for production runs.

---

## 10. Future Extensions

### 10.1 Contest simulation (Phase 2–3)

The simulator can be extended to evaluate lineup performance against a modeled or uploaded contest field. The key idea is:

- Simulate outcomes for both user lineups and field lineups using the same player draw arrays.
- Rank all lineups per simulation iteration.
- Aggregate win %, top-1% %, cash % across iterations.

**Duplicate handling (Phase 3):** If the same lineup appears $k$ times in the field, those $k$ entries share adjacent ranks in the payout ladder. Each duplicate receives the average payout across those ranks. This is implemented efficiently using cumulative payout sums.

### 10.2 Correlation modeling (Phase 4)

Within each game, players' outcomes are correlated: a high-scoring game tends to benefit all players in it. Modeling this requires:
- Grouping players by `game_id` / `matchup`.
- Building a correlation matrix $R$ from position-pair heuristics (same team PG-SG positive, opposing team positive/negative by role, etc.).
- Computing covariance: $\Sigma_{ij} = \rho_{ij}\sigma_i\sigma_j$.
- Repairing $\Sigma$ to be positive semidefinite before drawing from $\mathcal{N}(\mu, \Sigma)$.

A configurable `correlation_table.csv` (position pair → $\rho$) would allow tuning without code changes.

### 10.3 Late-swap simulation (Phase 5)

After some games tip off, finished players have known scores and remaining players have narrowed uncertainty. This warrants a separate `late_swap_simulator.py` that:
- Ingests live game-state (actual points, minutes played, minutes remaining).
- Updates player distributions: $\mu_{\text{updated}} = \text{actual} + ppm_{\text{blend}} \times \text{minutes remaining}$, with variance decayed by game progress.
- Treats completed games as deterministic (variance = 0).
- Simulates only the remaining uncertainty in the contest.

This is kept separate from `simulator.py` to avoid conflating pre-lock and live-state logic, matching the existing separation between `engine.py` and `late_swapper.py`.

### 10.4 Non-Gaussian outcome models

The normal distribution can understate tail risk for volatile NBA players (e.g., players with injury risk or widely varying minutes). Possible future alternatives:
- Truncated normal (avoids negative fantasy scores)
- Mixture model (two-component normal for "normal game" vs. "blowup game")
- Empirical bootstrap from historical game logs (if the SQLite data store planned in the project roadmap is implemented)

---

## 11. Testing and Validation Ideas

Since there is no automated test suite, validation for Phase 1 should focus on **manual sanity checks** against analytically known results:

| Check | What to verify | How |
|-------|----------------|-----|
| Mean convergence | Simulated mean lineup score → sum of player projections | Run 100k iterations; compare to `df_lineups["Total Proj"]` |
| Std dev convergence | Simulated lineup std dev → $\sqrt{\sum_i \sigma_i^2}$ | Same run; compare mathematically |
| Reproducibility | Same seed → identical output CSV | Run twice with `--seed 42` |
| Column integrity | Output CSV has all expected columns, no nulls | `df.isnull().sum()` after load |
| Top-1% rate sanity | `pool_top1pct.mean()` ≈ 0.01 across all lineups (by definition) | Assertion in summarize function |
| Monotone metrics | Higher-projection lineups should tend to have higher mean sim scores | Visual spot-check in output CSV |

When the test suite is eventually added (see BACKLOG: [Design] Unit Tests for Core LP Logic), deterministic simulation with a fixed seed is straightforward to unit test.

---

## 12. Integration Points with the Current Pipeline

### `orchestrator.py`

Add a `--simulate` / `simulate: bool` flag. When true, call `simulator.run(cfg)` after `ranker.run(cfg)` and before `exporter.run(cfg)`:

```python
# In orchestrator.py:
if cfg.simulate:
    simulator.run(cfg)
```

This keeps the orchestrator as the single place that controls stage sequencing.

### `config.py`

Add `sim_iterations`, `sim_stddev_factor`, and `sim_seed` fields to the `Config` dataclass. These can have defaults and be overridden via CLI args in `simulator.main()` using the existing `dataclasses.replace()` pattern.

### `utils.py`

`simulator.py` should resolve its input lineup file using `utils.get_latest_file()` (same as all other stages). No new file-resolution utility is needed.

### `engine.py` / `ranker.py`

No changes required. The simulator reads the ranked lineup CSV as a consumer, not a collaborator.

### `scripts/run_optimizer.py` / `scripts/run_optimizer_gui.py`

Add `--simulate` as an argparse flag, passed through to the orchestrator. This is a thin interface change only.

---

## 13. Related Backlog Items

| Task | Status | Relevance |
|------|--------|-----------|
| [Research] Data-Driven Randomization via Standard Deviation | Not Started | Simulator would be the natural consumer of per-player std dev from `nba_fantasy_logs.db` |
| [Implement] Consolidate Data Loading Logic | Not Started | Simulator should use a shared `load_data()` once consolidated; do not add a third duplicate |
| [Design] Unit Tests for Core LP Logic and Data Loading | Not Started | Simulator's deterministic seed mode makes it well-suited for future unit tests |
| [Research] MILP Exposure Caps | Not Started | Simulation win % / EV metrics may eventually feed back into a sim-weighted ranker or exporter filter |
