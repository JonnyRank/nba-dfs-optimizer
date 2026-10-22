import sys

from gooey import Gooey, GooeyParser

from .cli import add_pipeline_args
from .orchestrator import run_pipeline


@Gooey(
    program_name="Jonny's NBA DFS Optimizer",
    default_size=(600, 800),
    progress_regex=r"Lineups generated: (\d+)%",
    target=f'"{sys.executable}" -u -m nba_optimizer.gui',
    show_success_modal=False,
    show_stop_warning=False,
    terminal_font_family='Courier New',
)
def main():
    parser = GooeyParser(description="NBA DFS Optimizer - Main Orchestrator")
    add_pipeline_args(parser, gui=True)
    run_pipeline(parser.parse_args())


if __name__ == "__main__":
    main()
