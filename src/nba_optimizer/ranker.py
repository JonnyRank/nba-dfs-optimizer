import argparse
import os
import traceback
from datetime import datetime
from typing import Dict

import numpy as np
import pandas as pd

from .config import Config, ROSTER_SLOTS
from .utils import get_latest_file


def load_data(lineup_file: str, projs_file: str, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Loads lineups and player data (projections/ownership)."""
    df_lineups = pd.read_csv(lineup_file)
    df_projs = pd.read_csv(projs_file)
    df_projs["ID"] = df_projs["ID"].astype(str)

    # Import the engine's merge logic to get full player context
    from .engine import load_data as engine_load_data

    df_players = engine_load_data(projs_file, cfg.entries_path)

    return df_lineups, df_players


def rank_lineups(
    df_lineups: pd.DataFrame, df_players: pd.DataFrame, weights: Dict[str, float]
):
    """Calculates metrics and ranks lineups based on weighted scores."""
    proj_map = df_players.set_index("Name + ID")["Projection"].to_dict()
    own_map = df_players.set_index("Name + ID")["Own_Proj"].to_dict()

    lineup_results = []
    slots = ROSTER_SLOTS

    for idx, row in df_lineups.iterrows():
        lineup_names = [row[s] for s in slots]

        total_proj = sum([proj_map.get(name, 0) for name in lineup_names])
        total_own = sum([own_map.get(name, 0) for name in lineup_names])

        # Geomean Ownership (add small epsilon to avoid log(0))
        own_values = [own_map.get(name, 0) for name in lineup_names]
        geo_own = np.exp(np.mean(np.log([max(0.1, o) for o in own_values])))

        lineup_results.append(
            {
                "Lineup_ID": idx + 1,
                "Total_Projection": total_proj,
                "Total_Ownership": total_own,
                "Geomean_Ownership": geo_own,
                **{s: row[s] for s in slots},
            }
        )

    df_res = pd.DataFrame(lineup_results)

    # Calculate Ranks (1 is best)
    df_res["Proj_Rank"] = df_res["Total_Projection"].rank(ascending=False)
    df_res["Own_Rank"] = df_res["Total_Ownership"].rank(ascending=True)
    df_res["Geo_Rank"] = df_res["Geomean_Ownership"].rank(ascending=True)

    # Final Score: Weighted sum of ranks
    df_res["Lineup_Score"] = (
        df_res["Proj_Rank"] * weights.get("proj", 1.0)
        + df_res["Own_Rank"] * weights.get("own", 1.0)
        + df_res["Geo_Rank"] * weights.get("geo", 1.0)
    )

    # Sort by Score
    df_res = df_res.sort_values("Lineup_Score")
    df_res["Final_Rank"] = range(1, len(df_res) + 1)

    return df_res


def run(
    cfg: Config,
    proj_weight: float = 0.85,
    own_weight: float = 0.0,
    geo_weight: float = 0.15,
):
    print("Starting NBA DFS Sorter & Ranker...")

    try:
        # 1. Identify latest files
        lineup_file = get_latest_file(cfg.lineup_pool_dir, "lineup-pool-*.csv")
        projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv")

        print(f"Ranking: {os.path.basename(lineup_file)}")
        print(f"Using metrics from: {os.path.basename(projs_file)}")

        # 2. Load and merge
        df_lineups, df_players = load_data(lineup_file, projs_file, cfg)

        # 3. Rank
        weights = {
            "proj": proj_weight,
            "own": own_weight,
            "geo": geo_weight,
        }
        df_ranked = rank_lineups(df_lineups, df_players, weights)

        # 4. Save
        if not os.path.exists(cfg.ranked_lineup_dir):
            os.makedirs(cfg.ranked_lineup_dir)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(
            cfg.ranked_lineup_dir, f"ranked-lineups-{timestamp}.csv"
        )

        cols = [
            "Final_Rank",
            "Lineup_Score",
            "Total_Projection",
            "Total_Ownership",
            "Geomean_Ownership",
            "Proj_Rank",
            "Own_Rank",
            "Geo_Rank",
        ] + list(ROSTER_SLOTS)

        df_ranked[cols].to_csv(output_file, index=False)
        print(f"Successfully ranked {len(df_ranked)} lineups.")
        print(f"Saved to: {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


def main():
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Lineup Sorter & Ranker")
    parser.add_argument(
        "-pw",
        "--proj_weight",
        type=float,
        default=0.85,
        help="Weight for Projection Rank",
    )
    parser.add_argument(
        "-ow", "--own_weight", type=float, default=0.0, help="Weight for Ownership Rank"
    )
    parser.add_argument(
        "-gw", "--geo_weight", type=float, default=0.15, help="Weight for Geomean Rank"
    )
    args = parser.parse_args()

    cfg = load_config_from_env()

    run(
        cfg,
        proj_weight=args.proj_weight,
        own_weight=args.own_weight,
        geo_weight=args.geo_weight,
    )


if __name__ == "__main__":
    main()