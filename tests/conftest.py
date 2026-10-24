"""Shared fixtures for the 2026-10-20 opening-night files (nightly capture, O-0)."""

import json
import os
import re
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


TWIN_ID_OFFSET = 10_000_000
_DK_PLAYER_ID_RE = re.compile(r"\b4445\d{4}\b")


def make_twin(src: str, dest: str) -> str:
    """Write a "night twin" of a 10/20 file (O-15): every DK player ID (the 8-digit
    4445xxxx tokens) plus 10,000,000; contest and entry IDs untouched.

    The twin has the 10/20 games and times but its own player IDs, as an
    alternate slate does: DK IDs are per slate.
    """
    with open(src, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    text = _DK_PLAYER_ID_RE.sub(lambda m: str(int(m.group()) + TWIN_ID_OFFSET), text)
    with open(dest, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return dest
