"""Shared fixtures for the 2026-10-20 opening-night files (nightly capture, O-0)."""

import json
import os
import shutil
from datetime import datetime

import pytest

OPENING_NIGHT_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "2026-10-20")


def set_mtime(path: str, iso: str) -> None:
    ts = datetime.fromisoformat(iso).timestamp()
    os.utime(path, (ts, ts))


@pytest.fixture
def opening_night(tmp_path):
    """A copy of the opening-night files with their original 10/20 modified times.

    git doesn't keep modified times, so they come from mtimes.json.
    """
    sweep = tmp_path / "Opening-Night"
    sweep.mkdir()
    with open(os.path.join(OPENING_NIGHT_DIR, "mtimes.json"), encoding="utf-8") as f:
        mtimes = json.load(f)["mtimes"]
    for name, iso in mtimes.items():
        dest = sweep / name
        shutil.copy(os.path.join(OPENING_NIGHT_DIR, name), dest)
        set_mtime(str(dest), iso)
    return sweep
