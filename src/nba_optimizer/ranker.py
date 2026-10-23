import argparse
import os
import traceback
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import records
from .config import Config, ROSTER_SLOTS
from .overrides import apply_override_list
from .utils import get_latest_file, merge_player_pool, parse_dk_entries

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_data(lineup_file: str, projs_file: str, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Loads lineups and player data (projections/ownership)."""
    df_lineups = pd.read_csv(lineup_file)
    df_projs = pd.read_csv(projs_file)
    df_players = parse_dk_entries(cfg.entries_path)
    df_merged = merge_player_pool(df_players, df_projs, how="inner", derive_time_game=True)
    return df_lineups, df_merged


def effective_player_table(cfg: Config, ranked_file: str) -> Optional[pd.DataFrame]:
    """The merged player pool a ranked file was scored on: its run record's
    projections file with its recorded overrides applied. None if unknown.
    """
    path = records.run_record_path(ranked_file)
    if not os.path.isfile(path):
        return None
    record = records.read_json(path)
    projs_name = record.get("inputs", {}).get("projections", {}).get("file")
    if not projs_name:
        return None
    candidates = [os.path.join(os.path.dirname(os.path.abspath(ranked_file)), projs_name),
                  os.path.join(cfg.projs_dir, projs_name)]
    projs_file = next((c for c in candidates if os.path.isfile(c)), None)
    if not projs_file:
        return None
    df_players = merge_player_pool(
        parse_dk_entries(cfg.entries_path), pd.read_csv(projs_file), how="inner"
    )
    df_players, _ = apply_override_list(df_players, record.get("overrides") or [])
    return df_players


def warn_overrides_not_in_pool(df_lineups: pd.DataFrame, df_players: pd.DataFrame, applied: List[dict]) -> None:
    """Warn for each overridden player the existing pool doesn't contain (O-13 §6.4)."""
    in_pool = set(pd.unique(df_lineups[list(ROSTER_SLOTS)].values.ravel()))
    name_ids = df_players.set_index(df_players["ID"].astype(str))["Name + ID"]
    for o in applied:
        if name_ids.get(str(o["dk_id"])) not in in_pool:
            print(
                f"Warning: {o['name']} isn't in this pool (filtered out at generation); "
                "run the full pipeline to include this player"
            )


def check_projection_coverage(df_lineups: pd.DataFrame, df_players: pd.DataFrame) -> None:
    """Raise if any player in the lineups has no projection (R2).

    rank_lineups scores a missing player as 0, so a projections file from
    another slate would otherwise give a meaningless ranking.
    """
    in_pool = pd.unique(df_lineups[list(ROSTER_SLOTS)].values.ravel())
    projected = set(df_players["Name + ID"])
    missing = [p for p in in_pool if pd.notna(p) and p not in projected]
    if missing:
        raise ValueError(
            f"projections missing for {len(missing)} player(s) in the pool, first 5: {missing[:5]} "
            "(set a scratched player's projection to 0 rather than deleting the row)"
        )


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
    proj_weight: Optional[float] = None,
    own_weight: Optional[float] = None,
    geo_weight: Optional[float] = None,
    lineup_file: Optional[str] = None,
    projs_file: Optional[str] = None,
    num_lineups: Optional[int] = None,
    randomness: Optional[float] = None,
    base_seed: Optional[int] = None,
    slate: Optional[dict] = None,
    run_time: Optional[datetime] = None,
    overrides: Optional[List[dict]] = None,
    parent_record: Optional[dict] = None,
    inherited: Optional[List[str]] = None,
) -> str:
    """Rank the lineup pool and write its run record.

    The run record (``ranked-lineups-<...>.json``, same name as the CSV) is
    written after the CSV; a failed record write only warns.

    Args:
        cfg: Pipeline configuration.
        proj_weight, own_weight, geo_weight: Weights applied to the projection,
            total ownership and geomean ownership ranks; None uses the
            ``cfg`` default.
        lineup_file: Explicit path to a lineup-pool CSV. When omitted,
            the most recent file in ``cfg.lineup_pool_dir`` is used (standalone
            fallback behaviour).
        projs_file: Explicit path to a projections CSV. When omitted,
            the most recent file in ``cfg.projs_dir`` is used.
        num_lineups, randomness, base_seed: Engine settings to
            record. When all are given (orchestrated run) ``params_source``
            is ``cli``; otherwise ``partial`` with unknowns as ``null``.
            ``params.min_unique`` is recorded as ``null``: -u applies at
            assemble (O-14), and the assembly record holds it.
        slate: Slate facts from ``slate.load_or_write_slate``; gives the
            slate ID, the slate date for the filename and the lock.
        run_time: The run's instant, shared by every stage's filenames.
        overrides: Resolved ``{dk_id, name, field, to}`` projection/ownership
            overrides, applied right after the player-pool merge.
        parent_record: The latest run record on the pool, for a re-rank
            (``--from rank``): its engine params are copied and
            ``parent_run_id`` names the run that generated the pool.
        inherited: Setting names taken from the previous run (recorded as is).

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
        df_players, applied = apply_override_list(df_players, overrides or [])
        for o in applied:
            print(f"Override: {o['name']} {o['field']} {o['from']:g} -> {o['to']:g}")
        if parent_record is not None:
            warn_overrides_not_in_pool(df_lineups, df_players, applied)
        check_projection_coverage(df_lineups, df_players)

        # 3. Rank
        weights = {
            "proj": cfg.proj_weight if proj_weight is None else proj_weight,
            "own": cfg.own_weight if own_weight is None else own_weight,
            "geo": cfg.geo_weight if geo_weight is None else geo_weight,
        }
        df_ranked = rank_lineups(df_lineups, df_players, weights)

        # 4. Save
        if not os.path.exists(cfg.ranked_lineup_dir):
            os.makedirs(cfg.ranked_lineup_dir)

        run_time = (run_time or datetime.now()).astimezone()
        slate_date = slate["slate_date"] if slate else run_time.strftime("%Y-%m-%d")
        slate_type = slate["slate_type"] if slate else cfg.slate_type
        type_part = "" if slate_type == "main" else f"{slate_type.capitalize()}-"
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
            "base_seed": base_seed,
        }
        params_source = "cli" if None not in engine_params.values() else "partial"
        if parent_record is not None:
            # The pool's engine settings are the parent run's (O-13 §3.10).
            engine_params = dict(parent_record.get("params") or {})
            params_source = parent_record.get("params_source") or "partial"
        try:
            write_run_record(
                cfg, output_file, lineup_file, projs_file, slate, run_time,
                lineups_written=len(df_lineups),
                weights=weights,
                engine_params=engine_params,
                params_source=params_source,
                parent_record=parent_record,
                overrides=applied,
                inherited=inherited,
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
    parent_record: Optional[dict] = None,
    overrides: Optional[List[dict]] = None,
    inherited: Optional[List[str]] = None,
) -> str:
    """Write the run record JSON next to *ranked_file* and return its path."""
    from .slate import lock_or_none

    slate_id = slate["slate_id"] if slate else None
    lock = lock_or_none(slate, run_time) if slate else None
    df_projs = pd.read_csv(projs_file)
    projs_sha = records.sha256_file(projs_file)
    parent_run_id = None
    projections_rule = "latest"
    if parent_record is not None:
        # A re-rank's parent is the run that generated the pool.
        parent_run_id = parent_record.get("parent_run_id") or parent_record.get("run_id")
        parent_sha = parent_record.get("inputs", {}).get("projections", {}).get("sha256")
        projections_rule = "parent" if parent_sha == projs_sha else "latest"
    payload = {
        "schema": records.SCHEMA_VERSION,
        "run_id": f"{slate_id}_{records.compact_ts(run_time)}" if slate_id else records.compact_ts(run_time),
        "slate_id": slate_id,
        "generated_at": records.iso_seconds(run_time),
        "lock": lock,
        "parent_run_id": parent_run_id,
        "inputs": {
            "projections": {
                "file": os.path.basename(projs_file),
                "sha256": projs_sha,
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
        "overrides": list(overrides or []),
        "inherited": list(inherited or []),
        "projections_rule": projections_rule,
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
        "-pw", "--proj_weight", type=float, default=None, help="Weight for Projection Rank (Default: 0.8)"
    )
    parser.add_argument(
        "-ow", "--own_weight", type=float, default=None, help="Weight for Ownership Rank (Default: 0.0)"
    )
    parser.add_argument(
        "-gw", "--geo_weight", type=float, default=None, help="Weight for Geomean Rank (Default: 0.2)"
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