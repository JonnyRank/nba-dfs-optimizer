import argparse
import math
import os
import traceback
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .config import Config, ROSTER_SLOTS
from .utils import get_latest_file


def load_simulation_inputs(cfg: Config, lineup_file: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """
    Load player projection data (mean/stddev inputs) and a lineup pool.

    Returns:
        df_players: one row per player with projection/stddev inputs (keyed by Name + ID)
        df_lineups: one row per lineup with player name columns (PG...UTIL, and possibly other columns)
        resolved_lineup_file: the lineup file path actually used
    """
    projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv")

    if lineup_file:
        resolved_lineup_file = lineup_file
    else:
        try:
            resolved_lineup_file = get_latest_file(cfg.ranked_lineup_dir, "ranked-lineups-*.csv")
        except FileNotFoundError:
            resolved_lineup_file = get_latest_file(cfg.lineup_pool_dir, "lineup-pool-*.csv")

    if not os.path.isabs(resolved_lineup_file):
        resolved_lineup_file = os.path.abspath(resolved_lineup_file)

    df_lineups = pd.read_csv(resolved_lineup_file)

    from .engine import load_data as engine_load_data

    df_players = engine_load_data(projs_file, cfg.entries_path)

    return df_players, df_lineups, resolved_lineup_file


def build_player_distribution_inputs(
    df_players: pd.DataFrame, default_stddev_factor: float = 0.25, stddev_floor: float = 0.1
) -> dict[str, tuple[float, float]]:
    """
    Build {player_key: (mean, stddev)} lookup from player DataFrame.

    player_key is the Name+ID string (e.g., "LeBron James (12345678)").
    Applies default stddev = projection * default_stddev_factor for missing values, enforcing a minimum
    positive floor to prevent errors during sampling.
    """
    if "Name + ID" not in df_players.columns:
        raise ValueError("Expected 'Name + ID' column in merged player data")
    if "Projection" not in df_players.columns:
        raise ValueError("Expected 'Projection' column in projection data")

    df_work = df_players[["Name + ID", "Projection"]].copy()
    df_work["Projection"] = pd.to_numeric(df_work["Projection"], errors="coerce")

    if "StdDev" in df_players.columns:
        df_work["StdDev"] = pd.to_numeric(df_players["StdDev"], errors="coerce")
    else:
        df_work["StdDev"] = np.nan

    dist_dict: Dict[str, Tuple[float, float]] = {}

    for key, proj, stddev_val in zip(df_work["Name + ID"], df_work["Projection"], df_work["StdDev"]):
        if pd.isna(key):
            continue

        mean = float(proj) if not pd.isna(proj) else 0.0
        if pd.isna(stddev_val) or float(stddev_val) <= 0:
            stddev = abs(mean) * float(default_stddev_factor)
        else:
            stddev = float(stddev_val)

        if stddev <= 0:
            stddev = float(stddev_floor)
        else:
            stddev = max(float(stddev_floor), stddev)

        dist_dict[str(key)] = (mean, stddev)

    return dist_dict


def simulate_player_outcomes(
    player_keys: list[str],
    player_dist_dict: dict[str, tuple[float, float]],
    iterations: int = 10000,
    seed: int | None = None,
) -> np.ndarray:
    """
    Draw T independent normal samples per player.

    Returns np.ndarray of shape (len(player_keys), iterations) aligned with player_keys order.
    """
    means = np.empty(len(player_keys), dtype=np.float32)
    stddevs = np.empty(len(player_keys), dtype=np.float32)

    for i, key in enumerate(player_keys):
        mean, stddev = player_dist_dict[key]
        means[i] = mean
        stddevs[i] = stddev

    rng = np.random.default_rng(seed)
    samples = rng.normal(loc=means[:, None], scale=stddevs[:, None], size=(len(player_keys), iterations))
    return samples.astype(np.float32, copy=False)


def score_lineups_from_samples(
    df_lineups: pd.DataFrame, player_samples: np.ndarray, player_keys: list[str], player_cols: list[str]
) -> np.ndarray:
    """
    Compute lineup scores for each simulation iteration.

    player_samples: shape (num_players, iterations), aligned with player_keys.
    Returns np.ndarray of shape (num_lineups, iterations).
    """
    num_lineups = len(df_lineups)
    num_players = len(player_keys)

    player_idx_map = {k: i for i, k in enumerate(player_keys)}

    lineup_players = df_lineups[player_cols].to_numpy()
    flat_players = lineup_players.ravel()

    missing = [p for p in pd.unique(flat_players) if p not in player_idx_map]
    if missing:
        sample_missing = ", ".join(str(p) for p in missing[:10])
        raise ValueError(
            f"Found {len(missing)} lineup player entries with no projection/stddev data. Sample: {sample_missing}"
        )

    player_idx_flat = np.array([player_idx_map[p] for p in flat_players], dtype=np.int32)
    row_idx_flat = np.repeat(np.arange(num_lineups, dtype=np.int32), len(player_cols))

    lineup_matrix = np.zeros((num_lineups, num_players), dtype=np.float32)
    lineup_matrix[row_idx_flat, player_idx_flat] = 1.0

    return lineup_matrix @ player_samples


def summarize_lineup_results(scores_array: np.ndarray, df_lineups: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate per-lineup simulation metrics.

    Returns DataFrame with columns:
        lineup_id, players, mean_score, stddev_score, p90_score, p95_score, pool_top1pct, pool_top10pct
    """
    num_lineups, iterations = scores_array.shape

    mean_scores = scores_array.mean(axis=1)
    std_scores = scores_array.std(axis=1, ddof=0)
    p90_scores, p95_scores = np.percentile(scores_array, [90, 95], axis=1)

    top1_k = max(1, math.ceil(0.01 * num_lineups))
    top10_k = max(1, math.ceil(0.10 * num_lineups))

    top1_idx = np.argpartition(scores_array, num_lineups - top1_k, axis=0)[num_lineups - top1_k:, :]
    top10_idx = np.argpartition(scores_array, num_lineups - top10_k, axis=0)[num_lineups - top10_k:, :]

    top1_counts = np.bincount(top1_idx.ravel(), minlength=num_lineups)
    top10_counts = np.bincount(top10_idx.ravel(), minlength=num_lineups)

    pool_top1pct = top1_counts / float(iterations)
    pool_top10pct = top10_counts / float(iterations)

    player_cols = [c for c in ROSTER_SLOTS if c in df_lineups.columns]
    players_str = df_lineups[player_cols].astype(str).agg(", ".join, axis=1).tolist()

    return pd.DataFrame(
        {
            "lineup_id": np.arange(1, num_lineups + 1, dtype=int),
            "players": players_str,
            "mean_score": mean_scores,
            "stddev_score": std_scores,
            "p90_score": p90_scores,
            "p95_score": p95_scores,
            "pool_top1pct": pool_top1pct,
            "pool_top10pct": pool_top10pct,
        }
    )


def write_simulation_report(df_results: pd.DataFrame, cfg: Config, prefix: str = "sim-lineup-metrics") -> str:
    """
    Write results to timestamped CSV in cfg.output_dir.

    Returns the output file path.
    """
    os.makedirs(cfg.output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_file = os.path.join(cfg.output_dir, f"{prefix}-{timestamp}.csv")
    df_results.to_csv(output_file, index=False)
    return output_file


def run(
    cfg: Config, lineup_file: str | None = None, iterations: int = 10000, seed: int | None = None
) -> None:
    """
    Main entry point. Matches the run(cfg) interface of all other modules.

    Orchestrates load → simulate → summarize → write.
    """
    print("Starting Monte Carlo lineup-pool simulation (Phase 1)...")

    try:
        df_players, df_lineups, resolved_lineup_file = load_simulation_inputs(cfg, lineup_file=lineup_file)

        player_cols = [c for c in ROSTER_SLOTS if c in df_lineups.columns]
        if not player_cols:
            raise ValueError(f"Could not find any roster slot columns in {resolved_lineup_file}")

        stddev_factor = cfg.sim_stddev_factor
        seed = seed if seed is not None else cfg.sim_seed
        iterations = int(iterations if iterations is not None else cfg.sim_iterations)

        print(f"Using lineup file: {os.path.basename(resolved_lineup_file)}")
        print(f"Iterations: {iterations}; StdDev fallback factor: {stddev_factor}; Seed: {seed}")

        dist_dict = build_player_distribution_inputs(df_players, default_stddev_factor=float(stddev_factor))

        lineup_players = df_lineups[player_cols].to_numpy().ravel()
        player_keys = pd.unique(lineup_players).tolist()

        missing_keys = [k for k in player_keys if k not in dist_dict]
        if missing_keys:
            sample_missing = ", ".join(str(k) for k in missing_keys[:10])
            raise ValueError(
                f"Found {len(missing_keys)} players in lineup pool with no projection/stddev data. Sample: {sample_missing}"
            )

        player_samples = simulate_player_outcomes(
            player_keys=player_keys, player_dist_dict=dist_dict, iterations=iterations, seed=seed
        )
        scores_array = score_lineups_from_samples(
            df_lineups=df_lineups, player_samples=player_samples, player_keys=player_keys, player_cols=player_cols
        )

        df_results = summarize_lineup_results(scores_array=scores_array, df_lineups=df_lineups)
        output_file = write_simulation_report(df_results=df_results, cfg=cfg)

        print(f"Saved simulation metrics for {len(df_results)} lineups to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


def main() -> None:
    """
    argparse entry point for standalone execution:
        python -m nba_optimizer.simulator --lineup_file ranked-lineups-xxx.csv --iterations 10000
    """
    from dataclasses import replace
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Lineup Simulator (Phase 1)")
    parser.add_argument(
        "--lineup_file",
        type=str,
        default=None,
        help="Optional path to lineup file (ranked-lineups-*.csv or lineup-pool-*.csv).",
    )
    parser.add_argument("--iterations", type=int, default=10000, help="Number of Monte Carlo iterations (Default: 10000)")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducibility.")
    parser.add_argument(
        "--stddev_factor",
        type=float,
        default=None,
        help="Fallback StdDev factor when projection CSV lacks StdDev (Default: cfg.sim_stddev_factor).",
    )
    args = parser.parse_args()

    cfg = load_config_from_env()
    if args.stddev_factor is not None:
        cfg = replace(cfg, sim_stddev_factor=float(args.stddev_factor))

    run(cfg, lineup_file=args.lineup_file, iterations=args.iterations, seed=args.seed)


if __name__ == "__main__":
    main()
