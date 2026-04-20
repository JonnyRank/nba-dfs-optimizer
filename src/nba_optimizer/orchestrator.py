from dataclasses import replace

from . import engine, exporter, exposure_report, late_swapper, ranker
from .config import load_config_from_env


def run_pipeline(args):
    # Load base configuration from environment
    config = load_config_from_env()

    # Override configuration with CLI arguments
    config = replace(
        config,
        min_salary=args.min_salary,
        min_projection=args.min_projection,
    )

    if args.late_swap:
        print("\n=== RUNNING LATE SWAP RE-OPTIMIZATION ===")
        late_swapper.run(config)
        print("\n===========================================")
        print("Late Swap Complete!")
        print("Check your exports/ folder for the 'late-swap-entries' file.")
        print("===========================================")
        return

    print("\n--- Phase 1: Generating Lineups ---")
    engine.run(
        config,
        num_lineups=args.num_lineups,
        randomness=args.randomness,
        min_unique=args.min_unique,
    )

    print("\n--- Phase 2: Ranking Lineups ---")
    ranker.run(
        config,
        proj_weight=args.proj_weight,
        own_weight=args.own_weight,
        geo_weight=args.geo_weight,
    )

    print("\n--- Phase 3: Exporting to DraftKings CSV ---")
    exporter.run(config)

    print("\n--- Phase 4: Generating Exposure Report ---")
    exposure_report.run(config, top_x=args.top_x)

    print("\n==================================================================")
    print("Optimization Pipeline Complete!")
    print("Check your exports folder for the 'upload-ready-DKEntries' file.")
    print("==================================================================")
