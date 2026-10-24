import argparse

from .config import Config, downloads_dir_from_env
from .orchestrator import run_pipeline
from .settings import STAGES
from .slate import SLATE_TYPES

WEIGHT_DESTS = ("proj_weight", "own_weight", "geo_weight")
# GUI boxes that start filled with their Config default.
PREFILLED_DESTS = WEIGHT_DESTS + ("min_unique",)


def add_pipeline_args(parser, gui: bool = False) -> None:
    """Define the pipeline arguments once for the CLI and the Gooey GUI (O-13 §3.12).

    Works with argparse.ArgumentParser and GooeyParser. Repeatable arguments
    also accept a ';'-separated list, since a GUI text box holds one value.
    With *gui* (a GooeyParser) the weight and -u boxes are pre-filled with
    their defaults and a --from run uses what they show. The argparse default
    stays None, so a cleared box (left off the command) still inherits.
    """
    if gui:
        weight_help = "on a --from rank run, clear the box to inherit the last rank's"
        unique_help = "; on a --from run, clear the box to inherit the last assembly's"
    else:
        weight_help = "or inherited on a --from run"
        unique_help = ", or inherited on a --from run"

    if gui:
        entries_help = "DKEntries file. Leave blank to use the newest matching download"
        entries_widget = {
            "widget": "FileChooser",
            "gooey_options": {"default_dir": downloads_dir_from_env(), "wildcard": "CSV files (*.csv)|*.csv"},
        }
    else:
        entries_help = (
            "DKEntries file (Default: the newest DKEntries*.csv download from the last 24 h "
            "whose players match the slate type's projections)"
        )
        entries_widget = {}

    def prefill(name):
        # A string, so the box shows 0.0 rather than treating it as empty.
        return {"gooey_options": {"initial_value": str(getattr(Config, name))}} if gui else {}

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
        default=None,
        help=f"Min unique players between exported lineups (Default: {Config.min_unique}{unique_help})",
        **prefill("min_unique"),
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
        help=f"Weight for Projection Rank (Default: {Config.proj_weight}, {weight_help})",
        **prefill("proj_weight"),
    )
    parser.add_argument(
        "-ow",
        "--own_weight",
        type=float,
        default=None,
        help=f"Weight for Ownership Rank (Default: {Config.own_weight}, {weight_help})",
        **prefill("own_weight"),
    )
    parser.add_argument(
        "-gw",
        "--geo_weight",
        type=float,
        default=None,
        help=f"Weight for Geomean Rank (Default: {Config.geo_weight}, {weight_help})",
        **prefill("geo_weight"),
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
        help="Slate type: picks the projections folder and names the slate folder (Default: main)",
    )
    parser.add_argument(
        "--entries",
        dest="entries",
        default=None,
        help=entries_help,
        **entries_widget,
    )
    parser.add_argument(
        "--no-slate-folder",
        dest="no_slate_folder",
        action="store_true",
        help="This run only: ignore NBA_DATA_ROOT and use the legacy exports layout (for experiments)",
    )
    parser.add_argument(
        "--slate-dir",
        dest="slate_dir",
        default=None,
        help="Slate folder to work in, e.g. a past slate (uses its Pre-L0-DKEntries.csv)",
    )
    parser.add_argument(
        "--max",
        dest="max_caps",
        action="append",
        default=None,
        help='Max exposure "PLAYER=PCT" (percent of entries); repeat or separate with ";"',
    )
    parser.add_argument(
        "--max-all",
        dest="max_all",
        type=float,
        default=None,
        help="Max exposure PCT for every player (a player's own --max replaces it; --min doesn't)",
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
        "--min",
        dest="min_caps",
        action="append",
        default=None,
        help='Min exposure "PLAYER=PCT" (percent of entries); repeat or separate with ";"',
    )
    parser.add_argument(
        "--clear-overrides",
        dest="clear_overrides",
        nargs="?",
        const="all",
        default=None,
        help='Drop inherited --proj/--own overrides: "all" (type it in the GUI) or ";"-separated players',
    )
    parser.add_argument(
        "--clear-caps",
        dest="clear_caps",
        nargs="?",
        const="all",
        default=None,
        help='Drop inherited --max/--min caps: "all" (type it in the GUI; also drops --max-all) or ";"-separated players',
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
        help="Lineup pool CSV for --from rank (Default: the latest run record's pool; settings still inherit from the latest run)",
    )
    parser.add_argument(
        "--ranked",
        default=None,
        help="Ranked lineups CSV for --from assemble (Default: the latest ranked file; caps still inherit from the latest assembly)",
    )
    parser.add_argument(
        "--assembled",
        default=None,
        help="Assembled lineups CSV for --from export (Default: the latest assembly)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Base seed for the engine (Default: draw a fresh one, printed and recorded)",
    )

def pipeline_defaults(gui: bool = False) -> dict:
    """Each pipeline argument's default, keyed by dest.

    With *gui* the pre-filled boxes (weights, -u) take the values they start
    with, so an untouched box doesn't count as typed for the ignored-flag warnings.
    """
    parser = argparse.ArgumentParser()
    add_pipeline_args(parser)
    defaults = vars(parser.parse_args([]))
    if gui:
        defaults.update({name: getattr(Config, name) for name in PREFILLED_DESTS})
    return defaults


def main():
    parser = argparse.ArgumentParser(
        description="NBA DFS Optimizer - Main Orchestrator"
    )
    add_pipeline_args(parser)
    run_pipeline(parser.parse_args())
