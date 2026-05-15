import argparse

from .orchestrator import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="NBA DFS Optimizer - Main Orchestrator"
    )

    parser.add_argument(
        "--late_swap",
        action="store_true",
        help="Run late swap re-optimization instead of full generation.",
    )
    parser.add_argument(
        "-n",
        "--num_lineups",
        type=int,
        default=2500,
        help="Number of lineups to generate (Default: 2500)",
    )
    parser.add_argument(
        "-r",
        "--randomness",
        type=float,
        default=0.25,
        help="Randomness factor 0.0-1.0 (Default: 0.25)",
    )
    parser.add_argument(
        "-u",
        "--min_unique",
        type=int,
        default=1,
        help="Min unique players between lineups (Default: 1)",
    )
    parser.add_argument(
        "-ms",
        "--min_salary",
        type=int,
        default=49500,
        help="Min salary for a lineup (Default: 49500)",
    )
    parser.add_argument(
        "-mp",
        "--min_projection",
        type=float,
        default=10.0,
        help="Min projection for a player to be considered (Default: 10.0)",
    )
    parser.add_argument(
        "-pw",
        "--proj_weight",
        type=float,
        default=0.8,
        help="Weight for Projection Rank (Default: 0.8)",
    )
    parser.add_argument(
        "-ow",
        "--own_weight",
        type=float,
        default=0.0,
        help="Weight for Ownership Rank (Default: 0.0)",
    )
    parser.add_argument(
        "-gw",
        "--geo_weight",
        type=float,
        default=0.2,
        help="Weight for Geomean Rank (Default: 0.2)",
    )
    parser.add_argument(
        "-t",
        "--top_x",
        type=int,
        default=25,
        help="Display only top X exposed players (0 for all)",
    )

    run_pipeline(parser.parse_args())
