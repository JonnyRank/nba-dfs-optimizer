import argparse
import os
import traceback
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from . import records
from .config import Config, ROSTER_SLOTS
from .utils import get_latest_file, merge_player_pool, parse_dk_entries

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_data(lineup_file: str, projs_file: str, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Loads lineups and player data (projections/ownership)."""
    df_lineups = pd.read_csv(lineup_file)
    df_projs = pd.read_csv(projs_file)
    df_players = parse_dk_entries(cfg.entries_path)
    df_merged = merge_player_pool(df_players, df_projs, how="inner", derive_time_game=True)
    return df_lineups, df_merged


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
    lineup_file: Optional[str] = None,
    projs_file: Optional[str] = None,
    num_lineups: Optional[int] = None,
    randomness: Optional[float] = None,
    min_unique: Optional[int] = None,
    base_seed: Optional[int] = None,
    slate: Optional[dict] = None,
    run_time: Optional[datetime] = None,
) -> str:
    """Rank the lineup pool and write its run record.

    The run record (``ranked-lineups-<...>.json``, same name as the CSV) is
    written after the CSV; a failed record write only warns.

    Args:
        cfg: Pipeline configuration.
        proj_weight: Weight applied to the projection rank.
        own_weight: Weight applied to the total ownership rank.
        geo_weight: Weight applied to the geomean ownership rank.
        lineup_file: Explicit path to a lineup-pool CSV. When omitted,
            the most recent file in ``cfg.lineup_pool_dir`` is used (standalone
            fallback behaviour).
        projs_file: Explicit path to a projections CSV. When omitted,
            the most recent file in ``cfg.projs_dir`` is used.
        num_lineups, randomness, min_unique, base_seed: Engine settings to
            record. When all are given (orchestrated run) ``params_source``
            is ``cli``; otherwise ``partial`` with unknowns as ``null``.
        slate: Slate facts from ``slate.load_or_write_slate``; gives the
            slate ID, the slate date for the filename and the lock.
        run_time: The run's instant, shared by every stage's filenames.

    Returns:
        Path to the written ranked-lineups CSV, or an empty string if the run
        failed before producing output.
    """
    print("Starting NBA DFS Sorter & Ranker...")

    try:
        # 1. Identify files — use explicit paths when provided, otherwise fall back
        #    to latest-file discovery (standalone / direct module invocation).
        if not lineup_file:
            lineup_file = get_latest_file(cfg.lineup_pool_dir, "lineup-pool-*.csv")
        if not projs_file:
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

        run_time = (run_time or datetime.now()).astimezone()
        slate_date = slate["slate_date"] if slate else run_time.strftime("%Y-%m-%d")
        type_part = "" if cfg.slate_type == "main" else f"{cfg.slate_type.capitalize()}-"
        timestamp = f"{type_part}{slate_date}_{run_time.strftime('%H%M%S')}"
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

        engine_params = {
            "num_lineups": num_lineups,
            "randomness": randomness,
            "min_unique": min_unique,
            "base_seed": base_seed,
        }
        try:
            write_run_record(
                cfg, output_file, lineup_file, projs_file, slate, run_time,
                lineups_written=len(df_lineups),
                weights=weights,
                engine_params=engine_params,
                params_source="cli" if None not in engine_params.values() else "partial",
            )
        except Exception as e:
            print(f"Warning: run record not written: {e}")
        return output_file

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return ""


def write_run_record(
    cfg: Config,
    ranked_file: str,
    lineup_file: Optional[str],
    projs_file: str,
    slate: Optional[dict],
    run_time: datetime,
    lineups_written: Optional[int],
    weights: Dict[str, float],
    engine_params: Dict[str, Optional[float]],
    params_source: str,
    code_version: Optional[str] = "auto",
) -> str:
    """Write the run record JSON next to *ranked_file* and return its path."""
    from .slate import lock_for_time

    slate_id = slate["slate_id"] if slate else None
    lock = None
    if slate:
        try:
            lock = lock_for_time(slate, run_time)
        except ValueError:
            lock = None
    df_projs = pd.read_csv(projs_file)
    payload = {
        "schema": records.SCHEMA_VERSION,
        "run_id": f"{slate_id}_{records.compact_ts(run_time)}",
        "slate_id": slate_id,
        "generated_at": records.iso_seconds(run_time),
        "lock": lock,
        "parent_run_id": None,
        "inputs": {
            "projections": {
                "file": os.path.basename(projs_file),
                "sha256": records.sha256_file(projs_file),
                "layout": records.projections_layout(df_projs),
                "blend_check": records.check_blend(df_projs, warn=False),
            },
            "entries": {
                "file": os.path.basename(cfg.entries_path),
                "sha256": records.sha256_file(cfg.entries_path),
            },
        },
        "pool_file": os.path.basename(lineup_file) if lineup_file else None,
        "ranked_file": os.path.basename(ranked_file),
        "params": {
            "num_lineups": engine_params.get("num_lineups"),
            "lineups_written": lineups_written,
            "randomness": engine_params.get("randomness"),
            "min_unique": engine_params.get("min_unique"),
            "min_salary": cfg.min_salary,
            "min_projection": cfg.min_projection,
            "min_games": cfg.min_games,
            "proj_weight": weights["proj"],
            "own_weight": weights["own"],
            "geo_weight": weights["geo"],
            "base_seed": engine_params.get("base_seed"),
        },
        "params_source": params_source,
        "code_version": records.git_code_version(REPO_ROOT) if code_version == "auto" else code_version,
    }
    path = records.run_record_path(ranked_file)
    records.write_json_atomic(path, payload)
    print(f"Run record: {os.path.basename(path)}")
    return path


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