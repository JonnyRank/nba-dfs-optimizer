from dataclasses import replace

from . import engine, exporter, exposure_report, late_swapper, ranker, simulator
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
    lineup_pool_file = engine.run(
        config,
        num_lineups=args.num_lineups,
        randomness=args.randomness,
        min_unique=args.min_unique,
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
    )
    if not ranked_file:
        print("Error: Lineup ranking failed. Aborting pipeline.")
        return

    if args.simulate:
        print("\n--- Phase 2.5: Simulating Lineups (Monte Carlo) ---")
        simulator.run(
            config,
            iterations=config.sim_iterations,
            seed=config.sim_seed,
        )

    print("\n--- Phase 3: Exporting to DraftKings CSV ---")
    export_file = exporter.run(
        config,
        ranked_file=ranked_file,
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
