"""The README's settings table (O-15 §3.17) lists every pipeline argument in GUI order.

A new or moved argument fails here until the README table is updated with it.
"""

import os
import re

from nba_optimizer import cli

from test_stages import FakeGooeyParser

README = os.path.join(os.path.dirname(__file__), os.pardir, "README.md")


def _readme_table_flags():
    with open(README, encoding="utf-8") as f:
        text = f.read()
    section = text.split("#### Settings", 1)[1].split("\n\n**", 1)[0]
    flags = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].startswith("`"):
            flags.append(re.findall(r"`(--[\w-]+)`", cells[1])[0])
    return flags


def test_readme_settings_table_matches_args():
    parser = FakeGooeyParser()
    cli.add_pipeline_args(parser, gui=True)
    long_flags = [next(o for o in a.option_strings if o.startswith("--"))
                  for a in parser._actions if a.dest != "help"]
    assert _readme_table_flags() == long_flags
