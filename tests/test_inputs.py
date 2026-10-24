"""Input resolution (O-15): the slate type picks the projections folder, and the
DKEntries must be the same slate as those projections.

The alternate slate is the "night twin" of 10/20 (conftest.make_twin): the
same games and times as the main slate, every DK player ID + 10,000,000.
"""

import os
import shutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nba_optimizer import inputs
from nba_optimizer.config import Config

from conftest import OPENING_NIGHT_DIR, make_twin, set_mtime

PRE_L0 = os.path.join(OPENING_NIGHT_DIR, "Pre-L0-DKEntries.csv")
L0_PROJS = os.path.join(OPENING_NIGHT_DIR, "L0-NBA-Projs-2026-10-20_13-55-35.csv")
RUN_TIME = datetime(2026, 10, 20, 13, 0, tzinfo=ZoneInfo("America/Chicago"))


@pytest.fixture
def twin(tmp_path):
    d = tmp_path / "twin"
    d.mkdir()
    return {
        "entries": make_twin(PRE_L0, str(d / "Pre-L0-DKEntries.csv")),
        "projs": make_twin(L0_PROJS, str(d / "NBA-Projs-Night-2026-10-20_13-56-00.csv")),
    }


def _mtime(path, when):
    set_mtime(str(path), when.isoformat())


def test_twin_ids_are_per_slate(twin):
    """The twin shares no player IDs with 10/20 and matches itself fully; contest IDs are untouched."""
    main_entries, main_projs = inputs.player_ids(PRE_L0), inputs.player_ids(L0_PROJS)
    twin_entries, twin_projs = inputs.player_ids(twin["entries"]), inputs.player_ids(twin["projs"])
    assert len(main_entries) == len(twin_entries) == 125
    assert inputs.id_match(twin_entries, main_projs) == 0.0
    assert inputs.id_match(main_entries, twin_projs) == 0.0
    assert inputs.id_match(main_entries, main_projs) == 1.0
    assert inputs.id_match(twin_entries, twin_projs) == 1.0
    with open(twin["entries"], encoding="utf-8") as f:
        text = f.read()
    assert "196456024" in text and "5303852548" in text


def test_projs_dir_for(tmp_path):
    """main uses NBA_PROJS_DIR; night the sibling projections-night unless NBA_PROJS_DIR_NIGHT is set."""
    main = tmp_path / "projections"
    main.mkdir()
    (tmp_path / "projections-night").mkdir()
    cfg = Config(projs_dir=str(main))
    assert inputs.projs_dir_for(cfg, "main") == str(main)
    assert inputs.projs_dir_for(cfg, "night") == str(tmp_path / "projections-night")

    elsewhere = tmp_path / "Drive" / "night-projs"
    elsewhere.mkdir(parents=True)
    cfg.projs_dir_overrides = {"night": str(elsewhere)}
    assert inputs.projs_dir_for(cfg, "night") == str(elsewhere)

    with pytest.raises(FileNotFoundError) as e:
        inputs.projs_dir_for(cfg, "turbo")
    assert str(tmp_path / "projections-turbo") in str(e.value)
    assert "NBA_PROJS_DIR_TURBO" in str(e.value)


def test_latest_projections_uses_name_time(tmp_path):
    """The macro's name timestamp wins over modified times (a Drive copy rewrites those)."""
    early, late = tmp_path / "NBA-Projs-2026-10-23_20-28-32.csv", tmp_path / "NBA-Projs-2026-10-23_20-49-17.csv"
    for path in (early, late):
        shutil.copy(L0_PROJS, path)
    _mtime(early, RUN_TIME + timedelta(hours=2))
    _mtime(late, RUN_TIME + timedelta(hours=1))
    assert inputs.latest_projections(str(tmp_path), "main") == str(late)

    # A name without a timestamp ranks by its modified time.
    untimed = tmp_path / "NBA-Projs-Template-26-27-WIP.csv"
    shutil.copy(L0_PROJS, untimed)
    _mtime(untimed, datetime(2026, 10, 23, 21, 0))
    assert inputs.latest_projections(str(tmp_path), "main") == str(untimed)


def test_latest_projections_skips_other_type(tmp_path, capsys):
    """A newer-named night export in the main folder is skipped with a warning, not used."""
    main = tmp_path / "NBA-Projs-2026-10-23_20-28-32.csv"
    shutil.copy(L0_PROJS, main)
    shutil.copy(L0_PROJS, tmp_path / "NBA-Projs-Night-2026-10-23_20-49-17.csv")
    assert inputs.latest_projections(str(tmp_path), "main") == str(main)
    assert ("Warning: skipping NBA-Projs-Night-2026-10-23_20-49-17.csv in the main projections folder "
            "(named for night)") in capsys.readouterr().out

    # Several strays give one summary line, not one warning each.
    shutil.copy(L0_PROJS, tmp_path / "NBA-Projs-Night-2026-10-22_20-10-00.csv")
    inputs.latest_projections(str(tmp_path), "main")
    out = capsys.readouterr().out
    assert out.count("Warning:") == 1
    assert ("skipping 2 files named for night in the main projections folder "
            "(newest NBA-Projs-Night-2026-10-23_20-49-17.csv)") in out


def test_latest_projections_empty_folder(tmp_path):
    with pytest.raises(FileNotFoundError, match="no NBA-Projs-\\*.csv for night in"):
        inputs.latest_projections(str(tmp_path), "night")


def _downloads(tmp_path, twin):
    """Downloads holding the main DKEntries as DKEntries.csv (newer) and the twin as DKEntries (1).csv."""
    d = tmp_path / "downloads"
    d.mkdir()
    shutil.copy(PRE_L0, d / "DKEntries.csv")
    shutil.copy(twin["entries"], d / "DKEntries (1).csv")
    _mtime(d / "DKEntries (1).csv", RUN_TIME - timedelta(hours=2))
    _mtime(d / "DKEntries.csv", RUN_TIME - timedelta(hours=1))
    return d


def test_pick_entries_newest_matching(tmp_path, twin):
    """Download order doesn't matter: a newer download for the other slate fails the match and is skipped."""
    d = _downloads(tmp_path, twin)
    cfg = Config(downloads_dir=str(d), entries_path="")
    assert inputs.pick_entries(cfg, twin["projs"], RUN_TIME) == str(d / "DKEntries (1).csv")
    assert inputs.pick_entries(cfg, L0_PROJS, RUN_TIME) == str(d / "DKEntries.csv")


def test_pick_entries_ignores_old_downloads(tmp_path, twin):
    """A matching download from more than 24 h before the run is yesterday's, not tonight's."""
    d = _downloads(tmp_path, twin)
    _mtime(d / "DKEntries (1).csv", RUN_TIME - timedelta(hours=25))
    cfg = Config(downloads_dir=str(d), entries_path="", slate_type="night")
    with pytest.raises(FileNotFoundError, match="no DKEntries downloaded in the last 24 h matches "
                                                "NBA-Projs-Night-2026-10-20_13-56-00.csv; download the night"):
        inputs.pick_entries(cfg, twin["projs"], RUN_TIME)


def test_chosen_entries_must_match(tmp_path, twin):
    """A chosen DKEntries for the other slate fails with the counts, before anything is written."""
    night_dir = tmp_path / "projections-night"
    night_dir.mkdir()
    shutil.copy(twin["projs"], night_dir)
    cfg = Config(projs_dir=str(tmp_path / "projections"), downloads_dir=str(tmp_path))
    with pytest.raises(ValueError, match="NBA-Projs-Night-2026-10-20_13-56-00.csv matches 0 of 125 players in "
                                         "Pre-L0-DKEntries.csv; export tonight's night projections"):
        inputs.resolve_inputs(cfg, "night", PRE_L0, RUN_TIME)

    chosen = inputs.resolve_inputs(cfg, "night", twin["entries"], RUN_TIME)
    assert (chosen.entries_how, chosen.match, chosen.n_players) == ("chosen", 1.0, 125)


def test_chosen_file_must_be_dkentries(tmp_path):
    """A projections file chosen as the DKEntries is named for what it isn't."""
    (tmp_path / "projections").mkdir()
    shutil.copy(L0_PROJS, tmp_path / "projections" / "NBA-Projs-2026-10-20_13-55-35.csv")
    cfg = Config(projs_dir=str(tmp_path / "projections"), downloads_dir=str(tmp_path))
    with pytest.raises(ValueError, match="L0-NBA-Projs-2026-10-20_13-55-35.csv isn't a DKEntries download"):
        inputs.resolve_inputs(cfg, "main", L0_PROJS, RUN_TIME)
