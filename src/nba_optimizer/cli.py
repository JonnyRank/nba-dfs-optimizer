import argparse

from .orchestrator import run_pipeline
from .settings import STAGES
from .slate import SLATE_TYPES


def add_pipeline_args(parser) -> None:
    """Define the pipeline arguments once for the CLI and the Gooey GUI (O-13 §3.12).

    Works with argparse.ArgumentParser and GooeyParser. Repeatable arguments
    also accept a ';'-separated list, since a GUI text box holds one value.
    """
    parser.add_argument(
        "--late_swap",
        action="store_true",
        help="Run late swap re-optimization instead of full generation.",
    )
    parser.add_argument(
        "--from",
        dest="from_stage",
        choices=STAGES,
        default="generate",
        help="Stage to start at; earlier stages' latest outputs are reused (Default: generate)",
    )
    parser.add_argument(
        "--to",
        dest="to_stage",
        choices=STAGES,
        default="export",
        help="Stage to stop after (Default: export)",
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
        default=None,
        help="Weight for Projection Rank (Default: 0.8, or inherited on a --from run)",
    )
    parser.add_argument(
        "-ow",
        "--own_weight",
        type=float,
        default=None,
        help="Weight for Ownership Rank (Default: 0.0, or inherited on a --from run)",
    )
    parser.add_argument(
        "-gw",
        "--geo_weight",
        type=float,
        default=None,
        help="Weight for Geomean Rank (Default: 0.2, or inherited on a --from run)",
    )
    parser.add_argument(
        "--proj",
        action="append",
        default=None,
        help='Projection override "PLAYER=VALUE" (name or DK ID); repeat or separate with ";"',
    )
    parser.add_argument(
        "--own",
        action="append",
        default=None,
        help='Ownership override "PLAYER=VALUE"; repeat or separate with ";"',
    )
    parser.add_argument(
        "--max",
        dest="max_caps",
        action="append",
        default=None,
        help='Max exposure "PLAYER=PCT" (percent of entries); repeat or separate with ";"',
    )
    parser.add_argument(
        "--min",
        dest="min_caps",
        action="append",
        default=None,
        help='Min exposure "PLAYER=PCT" (percent of entries); repeat or separate with ";"',
    )
    parser.add_argument(
        "--max-all",
        dest="max_all",
        type=float,
        default=None,
        help="Max exposure PCT for every player (a player's own --max replaces it)",
    )
    parser.add_argument(
        "--clear-overrides",
        dest="clear_overrides",
        nargs="?",
        const="all",
        default=None,
        help='Drop inherited --proj/--own overrides: "all" or ";"-separated players',
    )
    parser.add_argument(
        "--clear-caps",
        dest="clear_caps",
        nargs="?",
        const="all",
        default=None,
        help='Drop inherited --max/--min caps: "all" (also --max-all) or ";"-separated players',
    )
    parser.add_argument(
        "--reset-settings",
        dest="reset_settings",
        action="store_true",
        help="Inherit nothing: weights, overrides and caps return to defaults",
    )
    parser.add_argument(
        "--pool",
        default=None,
        help="Lineup pool CSV for --from rank (Default: the latest run record's pool)",
    )
    parser.add_argument(
        "--ranked",
        default=None,
        help="Ranked lineups CSV for --from assemble (Default: the latest ranked file)",
    )
    parser.add_argument(
        "--assembled",
        default=None,
        help="Assembled lineups CSV for --from export (Default: the latest assembly)",
    )
    parser.add_argument(
        "--slate-dir",
        dest="slate_dir",
        default=None,
        help="Slate folder to work in, e.g. a past slate (uses its Pre-L0-DKEntries.csv)",
    )
    parser.add_argument(
        "-t",
        "--top_x",
        type=int,
        default=25,
        help="Display only top X exposed players (0 for all)",
    )
    parser.add_argument(
        "--slate-type",
        dest="slate_type",
        choices=SLATE_TYPES,
        default="main",
        help="Slate type used in the slate folder name (Default: main)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Base seed for the engine (Default: draw a fresh one, printed and recorded)",
    )


def pipeline_defaults() -> dict:
    """Each pipeline argument's default, keyed by dest."""
    parser = argparse.ArgumentParser()
    add_pipeline_args(parser)
    return vars(parser.parse_args([]))


def main():
    parser = argparse.ArgumentParser(
        description="NBA DFS Optimizer - Main Orchestrator"
    )
    add_pipeline_args(parser)
    run_pipeline(parser.parse_args())
