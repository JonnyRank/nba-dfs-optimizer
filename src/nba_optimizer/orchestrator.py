import os
from dataclasses import replace
from datetime import datetime

import pandas as pd

from . import engine, exporter, exposure_report, late_swapper, ranker, records
from .config import load_config_from_env
from .slate import PRE_L0_ENTRIES, load_or_write_slate, lock_or_none
from .utils import get_latest_file


def prepare_slate_inputs(config, run_time):
    """Resolve tonight's slate and copy the run's inputs into its folder.

    Returns (config, slate, projs_file). With NBA_DATA_ROOT set, the
    returned config reads its DKEntries from the slate-folder copy and writes
    pools and ranked files to the slate folder; without it, config is
    unchanged and the slate is built in memory (or None).
    """
    slate, slate_dir = load_or_write_slate(config, config.entries_path)
    projs_file = get_latest_file(config.projs_dir, "NBA-Projs-*.csv")

    if slate_dir:
        # lock is None after the last lock: copies are named "Post-..." and
        # the exporter writes no entry set (see exporter.write_export_entry_set).
        lock = lock_or_none(slate, run_time)
        entries_name = PRE_L0_ENTRIES if lock == 0 else f"{records.lock_prefix(lock)}-DKEntries.csv"
        entries_copy = records.snapshot_input(config.entries_path, slate_dir, entries_name)
        projs_copy = records.snapshot_input(
            projs_file, slate_dir, records.projections_copy_name(projs_file, lock)
        )
        config = replace(
            config,
            entries_path=os.path.join(slate_dir, entries_copy),
            lineup_pool_dir=slate_dir,
            ranked_lineup_dir=slate_dir,
        )
        projs_file = os.path.join(slate_dir, projs_copy)

    records.check_blend(pd.read_csv(projs_file))
    return config, slate, projs_file


def run_pipeline(args):
    # Load base configuration from environment
    config = load_config_from_env()

    # Override configuration with CLI arguments
    config = replace(
        config,
        min_salary=args.min_salary,
        min_projection=args.min_projection,
        slate_type=getattr(args, "slate_type", "main"),
        seed=getattr(args, "seed", None),
    )

    if args.late_swap:
        print("\n=== RUNNING LATE SWAP RE-OPTIMIZATION ===")
        late_swapper.run(config)
        print("\n===========================================")
        print("Late Swap Complete!")
        print("Check your exports/ folder for the 'late-swap-entries' file.")
        print("===========================================")
        return

    # One instant supplies every stage's filenames, generated_at and the run ID.
    run_time = datetime.now().astimezone().replace(microsecond=0)
    try:
        config, slate, projs_file = prepare_slate_inputs(config, run_time)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}")
        return
    slate_date = slate["slate_date"] if slate else None

    print("\n--- Phase 1: Generating Lineups ---")
    lineup_pool_file = engine.run(
        config,
        num_lineups=args.num_lineups,
        randomness=args.randomness,
        min_unique=args.min_unique,
        projs_file=projs_file,
        run_time=run_time,
        slate_date=slate_date,
    )
    if not lineup_pool_file:
        print("Error: Lineup generation failed. Aborting pipeline.")
        return

    print("\n--- Phase 2: Ranking Lineups ---")
    ranked_file = ranker.run(
        config,
        proj_weight=args.proj_weight,
        own_weight=args.own_weight,
        geo_weight=args.geo_weight,
        lineup_file=lineup_pool_file,
        projs_file=projs_file,
        num_lineups=args.num_lineups,
        randomness=args.randomness,
        min_unique=args.min_unique,
        base_seed=config.seed,
        slate=slate,
        run_time=run_time,
    )
    if not ranked_file:
        print("Error: Lineup ranking failed. Aborting pipeline.")
        return

    print("\n--- Phase 3: Exporting to DraftKings CSV ---")
    export_file = exporter.run(
        config,
        ranked_file=ranked_file,
        run_time=run_time,
    )
    if not export_file:
        print("Error: Export failed. Aborting pipeline.")
        return

    print("\n--- Phase 4: Generating Exposure Report ---")
    exposure_report.run(
        config,
        top_x=args.top_x,
        entries_file=export_file,
    )

    print("\n=================================================================")
    print("Optimization Pipeline Complete!")
    print("Check your exports folder for the 'upload-ready-DKEntries' file.")
    print("=================================================================")
