from gooey import Gooey, GooeyParser

from . import engine, exporter, exposure_report, late_swapper, ranker


@Gooey(
    program_name="Jonny's NBA DFS Optimizer",
    default_size=(600, 700),
    progress_regex=r"Lineups generated: (\d+)%"
)
def main():
    parser = GooeyParser(description="NBA DFS Optimizer - Main Orchestrator")

    parser.add_argument("--late_swap", action="store_true", help="Run late swap re-optimization instead of full generation.")
    parser.add_argument("-n", "--num_lineups", type=int, default=2500, help="Number of lineups to generate (Default: 2500)")
    parser.add_argument("-r", "--randomness", type=float, default=0.25, help="Randomness factor 0.0-1.0 (Default: 0.25)")
    parser.add_argument("-u", "--min_unique", type=int, default=1, help="Min unique players between lineups (Default: 1)")
    parser.add_argument("-ms", "--min_salary", type=int, default=49500, help="Min salary for a lineup (Default: 49500)")
    parser.add_argument("-mp", "--min_projection", type=float, default=10.0, help="Min projection for a player to be considered (Default: 10.0)")
    parser.add_argument("-pw", "--proj_weight", type=float, default=0.8, help="Weight for Projection Rank (Default: 0.8)")
    parser.add_argument("-ow", "--own_weight", type=float, default=0.0, help="Weight for Ownership Rank (Default: 0.0)")
    parser.add_argument("-gw", "--geo_weight", type=float, default=0.2, help="Weight for Geomean Rank (Default: 0.2)")
    parser.add_argument("-t", "--top_x", type=int, default=0, help="Display only top X exposed players (0 for all)")

    args = parser.parse_args()

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
    print("Check your exports folder for the 'upload_ready_DKEntries' file.")
    print("==================================================================")
