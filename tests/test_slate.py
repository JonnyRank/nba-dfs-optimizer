"""Slate facts and lock numbering, built from the real 2026-10-20 DKEntries."""

import os
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nba_optimizer.config import Config
from nba_optimizer.records import read_json
from nba_optimizer.slate import build_slate, load_or_write_slate, lock_for_time, team_game_lock
from nba_optimizer.utils import parse_dk_entries

from conftest import OPENING_NIGHT_DIR, make_twin

PRE_L0 = os.path.join(OPENING_NIGHT_DIR, "Pre-L0-DKEntries.csv")
CT = ZoneInfo("America/Chicago")


def test_build_slate_opening_night():
    """Three locks (3:00, 7:00, 9:30 PM ET), two 20-entry contests, 125 players split 41/42/42."""
    slate = build_slate(PRE_L0, "main")

    assert slate["slate_id"] == "2026-10-20_classic_main"
    assert [lk["start"] for lk in slate["locks"]] == [
        "2026-10-20T15:00:00-04:00",
        "2026-10-20T19:00:00-04:00",
        "2026-10-20T21:30:00-04:00",
    ]
    assert [lk["games"] for lk in slate["locks"]] == [["BOS@DET"], ["PHI@NYK"], ["OKC@SAS"]]
    assert [(c["contest_id"], c["n_entries"]) for c in slate["contests"]] == [(196456024, 20), (196456031, 20)]
    assert [c["entry_fee"] for c in slate["contests"]] == [4.0, 1.0]
    assert len(slate["entry_ids"]) == 40

    assert slate["n_players"] == 125
    team_lock = team_game_lock(slate)
    per_lock = Counter(team_lock[t] for t in parse_dk_entries(PRE_L0)["TeamAbbrev"])
    assert [per_lock[k] for k in range(3)] == [41, 42, 42]


def test_build_slate_rejects_postlock_file():
    """Slate facts can't come from a download where games show In Progress/Final."""
    with pytest.raises(ValueError, match="pre-lock DKEntries"):
        build_slate(os.path.join(OPENING_NIGHT_DIR, "Post-L2-DKEntries.csv"), "main")


def test_lock_for_time():
    """A time maps to the first lock that hasn't started yet (files are stamped in CT)."""
    slate = build_slate(PRE_L0, "main")
    assert lock_for_time(slate, datetime(2026, 10, 20, 13, 57, tzinfo=CT)) == 0
    assert lock_for_time(slate, datetime(2026, 10, 20, 17, 59, 24, tzinfo=CT)) == 1
    assert lock_for_time(slate, datetime(2026, 10, 20, 20, 29, 50, tzinfo=CT)) == 2
    with pytest.raises(ValueError):
        lock_for_time(slate, datetime(2026, 10, 20, 21, 48, tzinfo=CT))


def test_slate_json_written_once(tmp_path):
    """The first run writes slate.json and copies Pre-L0; a later post-lock run reuses it."""
    cfg = Config(data_root=str(tmp_path))
    slate, slate_dir = load_or_write_slate(cfg, PRE_L0)
    assert slate_dir == os.path.join(str(tmp_path), "2026-10-20_classic_main")
    assert slate["source_file"] == "Pre-L0-DKEntries.csv"
    assert os.path.isfile(os.path.join(slate_dir, "Pre-L0-DKEntries.csv"))
    written = read_json(os.path.join(slate_dir, "slate.json"))

    again, again_dir = load_or_write_slate(cfg, os.path.join(OPENING_NIGHT_DIR, "Post-L0-DKEntries.csv"))
    assert again_dir == slate_dir
    assert again == written
    assert read_json(os.path.join(slate_dir, "slate.json")) == written


def test_first_run_needs_prelock_file(tmp_path):
    """Without slate.json, a post-lock DKEntries can't start the night."""
    cfg = Config(data_root=str(tmp_path))
    with pytest.raises(ValueError, match="first run of the night needs a pre-lock DKEntries"):
        load_or_write_slate(cfg, os.path.join(OPENING_NIGHT_DIR, "Post-L2-DKEntries.csv"))


def test_find_slate_dir_prefers_finished_slate_over_unlocked_one(tmp_path):
    """Next morning, after tonight's pre-lock run made its folder, finalize still finds last night's."""
    import json
    from nba_optimizer.slate import find_slate_dir

    def make(slate_id, starts):
        d = tmp_path / slate_id
        d.mkdir()
        (d / "slate.json").write_text(json.dumps({"locks": [{"lock": k, "start": s} for k, s in enumerate(starts)]}))
        return str(d)

    last_night = make("2026-10-20_classic_main", ["2026-10-20T15:00:00-04:00", "2026-10-20T21:30:00-04:00"])
    tonight = make("2026-10-21_classic_main", ["2026-10-21T19:00:00-04:00", "2026-10-21T22:00:00-04:00"])
    cfg = Config(data_root=str(tmp_path))

    noon = datetime(2026, 10, 21, 12, 0, tzinfo=CT)
    assert find_slate_dir(cfg, noon) == last_night
    after_tonights_lock0 = datetime(2026, 10, 21, 18, 30, tzinfo=CT)
    assert find_slate_dir(cfg, after_tonights_lock0) == tonight


def _folder_state(folder):
    return {n: os.path.getmtime(os.path.join(folder, n)) for n in sorted(os.listdir(folder))}


def test_folder_guard_existing_folder(tmp_path):
    """O-15: the main DKEntries can't run in an existing night folder built from the night twin;
    the folder's files are left as they were."""
    twin = make_twin(PRE_L0, str(tmp_path / "DKEntries-Night.csv"))
    cfg = Config(data_root=str(tmp_path / "slates"), slate_type="night")
    _, night_dir = load_or_write_slate(cfg, twin)
    assert os.path.basename(night_dir) == "2026-10-20_classic_night"
    before = _folder_state(night_dir)

    with pytest.raises(ValueError, match="match only 0 of 125 players in 2026-10-20_classic_night's"):
        load_or_write_slate(cfg, PRE_L0)
    assert _folder_state(night_dir) == before


def test_folder_guard_sibling(tmp_path):
    """Creating a night folder from the main slate's DKEntries names the main folder and creates nothing."""
    slates = tmp_path / "slates"
    load_or_write_slate(Config(data_root=str(slates)), PRE_L0)

    with pytest.raises(ValueError, match=r"these DKEntries are 2026-10-20_classic_main's \(125 of 125 players\); "
                                         "set the slate type to main or choose the night DKEntries"):
        load_or_write_slate(Config(data_root=str(slates), slate_type="night"), PRE_L0)
    assert not os.path.exists(slates / "2026-10-20_classic_night")
