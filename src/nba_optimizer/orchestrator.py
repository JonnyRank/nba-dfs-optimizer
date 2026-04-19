from . import engine, exporter, exposure_report, late_swapper, ranker


def run_pipeline(args):
    if args.late_swap:
        print("\n=== RUNNING LATE SWAP RE-OPTIMIZATION ===")
        late_swapper.run(min_salary=args.min_salary, min_projection=args.min_projection)
        print("\n===========================================")
        print("Late Swap Complete!")
        print("Check your exports/ folder for the 'late-swap-entries' file.")
        print("===========================================")
        return

    print("\n--- Phase 1: Generating Lineups ---")
    engine.run(
        num_lineups=args.num_lineups,
        randomness=args.randomness,
        min_unique=args.min_unique,
        min_salary=args.min_salary,
        min_projection=args.min_projection,
    )

    print("\n--- Phase 2: Ranking Lineups ---")
    ranker.run(
        proj_weight=args.proj_weight,
        own_weight=args.own_weight,
        geo_weight=args.geo_weight,
    )

    print("\n--- Phase 3: Exporting to DraftKings CSV ---")
    exporter.run()

    print("\n--- Phase 4: Generating Exposure Report ---")
    exposure_report.run(top_x=args.top_x)

    print("\n==================================================================")
    print("Optimization Pipeline Complete!")
    print("Check your exports folder for the 'upload-ready-DKEntries' file.")
    print("==================================================================")
