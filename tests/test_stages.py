"""Stage control (O-13): --from/--to runs, inherited settings and resets.

Each test builds tonight's slate folder from the real 10/20 files: the
pre-lock DKEntries, the L0 projections, and the engine replaced by a stub
that writes the fixture's 100 lineups as the pool (no LP solves). Runs are
spaced a minute apart before lock 0 (14:00 CT), so every artifact gets its
own filename and the exporter writes L0 entry sets.
"""

import argparse
import os
import shutil
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from nba_optimizer import cli, engine, orchestrator, records
from nba_optimizer.config import Config, ROSTER_SLOTS
from nba_optimizer.settings import latest_record, resolve_settings

from conftest import make_twin

NIGHT_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "2026-10-20")
RANKED_FIXTURE = os.path.join(NIGHT_DIR, "ranked-lineups-2026-10-20_135723.csv")
PROJS_NAME = "NBA-Projs-2026-10-20_13-55-35.csv"
NIGHT_PROJS_NAME = "NBA-Projs-Night-2026-10-20_13-56-00.csv"
JAYSON_TATUM = 44451207
DYLAN_HARPER = 44451282
OG_ANUNOBY = 44451272
CT = ZoneInfo("America/Chicago")


class FakeGooeyParser(argparse.ArgumentParser):
    """Accepts gooey_options and widget= like GooeyParser and keeps them by dest (Gooey is never imported)."""

    def __init__(self):
        super().__init__()
        self.gooey_options = {}
        self.widgets = {}

    def add_argument(self, *args, gooey_options=None, widget=None, **kwargs):
        action = super().add_argument(*args, **kwargs)
        if gooey_options:
            self.gooey_options[action.dest] = gooey_options
        if widget:
            self.widgets[action.dest] = widget
        return action


def parse(argv, gui=False):
    parser = FakeGooeyParser() if gui else argparse.ArgumentParser()
    cli.add_pipeline_args(parser, gui=gui)
    return parser.parse_args(argv)


class Night:
    """Tonight's inputs plus a run() that advances the clock a minute per call.

    Alongside the main slate's files sits a night slate (O-15): the "night
    twin" of the same files (same games, every DK player ID + 10,000,000) in
    a projections-night folder and as the newer download DKEntries (1).csv.
    """

    def __init__(self, tmp_path, monkeypatch):
        self.projs_dir = tmp_path / "projections"
        self.projs_dir.mkdir()
        shutil.copy(os.path.join(NIGHT_DIR, "L0-NBA-Projs-2026-10-20_13-55-35.csv"), self.projs_dir / PROJS_NAME)
        self.night_projs_dir = tmp_path / "projections-night"
        self.night_projs_dir.mkdir()
        make_twin(os.path.join(NIGHT_DIR, "L0-NBA-Projs-2026-10-20_13-55-35.csv"),
                  self.night_projs_dir / NIGHT_PROJS_NAME)
        self.downloads = tmp_path / "downloads"
        self.downloads.mkdir()
        shutil.copy(os.path.join(NIGHT_DIR, "Pre-L0-DKEntries.csv"), self.downloads / "DKEntries.csv")
        self.twin_entries = make_twin(os.path.join(NIGHT_DIR, "Pre-L0-DKEntries.csv"),
                                      str(self.downloads / "DKEntries (1).csv"))
        self.twin_ranked = make_twin(RANKED_FIXTURE, str(tmp_path / "twin-ranked.csv"))
        self.cfg = Config(
            entries_path=str(self.downloads / "DKEntries.csv"),
            projs_dir=str(self.projs_dir),
            base_dir=str(tmp_path / "exports"),
            output_dir=str(self.downloads),
            data_root=str(tmp_path / "slates"),
            downloads_dir=str(self.downloads),     # never the developer's ~/Downloads
        )
        self.slate_dir = str(tmp_path / "slates" / "2026-10-20_classic_main")
        self.night_slate_dir = str(tmp_path / "slates" / "2026-10-20_classic_night")
        self.engine_calls = 0
        self.clock = datetime(2026, 10, 20, 13, 0, 0, tzinfo=CT)
        monkeypatch.setattr(orchestrator, "load_config_from_env", lambda: replace(self.cfg))
        monkeypatch.setattr(engine, "run", self._fake_engine)

    def _fake_engine(self, cfg, run_time=None, slate_date=None, projs_file=None, **kwargs):
        assert "min_unique" not in kwargs        # -u applies at assemble (O-14)
        self.engine_calls += 1
        if cfg.seed is None:
            cfg.seed = 12345
        os.makedirs(cfg.lineup_pool_dir, exist_ok=True)
        path = os.path.join(cfg.lineup_pool_dir, f"lineup-pool-{slate_date}_{run_time:%H%M%S}.csv")
        twin = projs_file and os.path.basename(projs_file).startswith("L0-NBA-Projs-Night-")
        pd.read_csv(self.twin_ranked if twin else RANKED_FIXTURE)[list(ROSTER_SLOTS)].to_csv(path, index=False)
        return path

    def run(self, *argv, gui=False):
        self.clock += timedelta(minutes=1)
        orchestrator.run_pipeline(parse(list(argv), gui=gui), run_time=self.clock, gui=gui)
        return self.clock

    def rank_record(self):
        return latest_record(self.slate_dir, "rank")

    def assembly_record(self):
        return latest_record(self.slate_dir, "assemble")

    def files(self, prefix):
        return sorted(n for n in os.listdir(self.slate_dir) if n.startswith(prefix))

    def write_projections(self, name, tatum):
        df = pd.read_csv(self.projs_dir / PROJS_NAME)
        df.loc[df["ID"] == JAYSON_TATUM, "Projection"] = tatum
        df.to_csv(self.projs_dir / name, index=False)


@pytest.fixture
def night(tmp_path, monkeypatch):
    return Night(tmp_path, monkeypatch)


def _weights(record):
    p = record["params"]
    return p["proj_weight"], p["own_weight"], p["geo_weight"]


def _overrides(record):
    return {(o["dk_id"], o["field"]): o["to"] for o in record["overrides"]}


def _caps(record):
    s = record["settings"]
    return ({c["dk_id"]: c["pct"] for c in s["max"]}, {c["dk_id"]: c["pct"] for c in s["min"]}, s["max_all"])


def _slot_rows(path, n=None):
    df = pd.read_csv(path)
    if "Entry ID" in df.columns:
        df = df[df["Entry ID"].notna()]
    return df[list(ROSTER_SLOTS)].head(n).values.tolist()


def test_full_run_unchanged(night):
    """A full run fills the 40 entries with ranks 1-40 of its ranked file, as before O-13."""
    night.run()
    ranked = os.path.join(night.slate_dir, night.files("ranked-lineups-")[0].replace(".json", ".csv"))
    export = os.path.join(night.slate_dir, night.files("upload-ready-DKEntries-")[0])

    assert _slot_rows(export) == _slot_rows(ranked, 40)
    assert night.engine_calls == 1
    assert _weights(night.rank_record()) == (0.8, 0.0, 0.2)
    assert night.assembly_record()["settings"] == {"max": [], "min": [], "max_all": None, "min_unique": 1}


def test_from_rank_skips_engine(night, monkeypatch):
    night.run("-pw", "0.7", "-gw", "0.3")
    first = night.rank_record()

    def boom(*args, **kwargs):
        raise AssertionError("engine ran")

    monkeypatch.setattr(engine, "run", boom)
    night.run("--from", "rank")
    second = night.rank_record()

    assert second["run_id"] != first["run_id"]
    assert second["parent_run_id"] == first["run_id"]
    assert second["pool_file"] == first["pool_file"]
    assert second["params"]["base_seed"] == 12345 and second["params_source"] == "cli"
    assert second["projections_rule"] == "parent"
    # Same 40 lineups, so the slate folder reuses the identical copy; Downloads has both.
    assert len([n for n in os.listdir(night.cfg.output_dir) if n.startswith("upload-ready-")]) == 2


def test_settings_inherit_typed_wins_reset(night):
    night.run("-pw", "0.7", "-ow", "0", "-gw", "0.3")
    night.run("--from", "rank", "--to", "rank", "-pw", "0.6")
    record = night.rank_record()
    assert _weights(record) == (0.6, 0.0, 0.3)
    assert record["inherited"] == ["own_weight", "geo_weight"]

    night.run("--from", "rank", "--to", "rank", "-pw", "0.6", "--reset-settings")
    record = night.rank_record()
    assert _weights(record) == (0.6, 0.0, 0.2)
    assert record["inherited"] == []

    night.run("--from", "rank", "--to", "rank", "-gw", "0.3")
    night.run("--to", "rank")
    assert _weights(night.rank_record()) == (0.8, 0.0, 0.2)
    assert night.rank_record()["inherited"] == []


def test_caps_inherited_by_next_assemble(night):
    night.run("--to", "rank")
    night.run("--from", "assemble", "--to", "assemble", "--max", "OG Anunoby=50")
    night.run("--from", "assemble", "--to", "assemble", "--min", "Karl-Anthony Towns=20")
    record = night.assembly_record()

    assert _caps(record) == ({OG_ANUNOBY: 50}, {44451218: 20}, None)
    assert record["inherited"] == ["max", "min_unique"]


def test_caps_cleared_by_reset(night):
    night.run("--to", "rank")
    night.run("--from", "assemble", "--to", "assemble", "--max", "OG Anunoby=50")
    night.run("--from", "assemble", "--to", "assemble", "--reset-settings")

    assert _caps(night.assembly_record()) == ({}, {}, None)
    assert night.assembly_record()["solve"]["worst_rank"] == 40


def test_override_carry_rule(night, capsys):
    """Option (c): an inherited override lasts until the export changes that player."""
    night.run("--to", "rank", "--proj", "Jayson Tatum=55")
    with_55 = pd.read_csv(os.path.join(night.slate_dir, night.rank_record()["ranked_file"]))

    night.run("--from", "rank", "--to", "rank")
    record = night.rank_record()
    assert _overrides(record) == {(JAYSON_TATUM, "Projection"): 55}
    assert "overrides" in record["inherited"]

    night.write_projections("NBA-Projs-2026-10-20_13-58-00.csv", tatum=52)
    capsys.readouterr()
    night.run("--from", "rank", "--to", "rank")
    assert "Jayson Tatum override 55 dropped: newest export now says 52" in capsys.readouterr().out
    record = night.rank_record()
    assert record["overrides"] == [] and record["projections_rule"] == "latest"

    with_52 = pd.read_csv(os.path.join(night.slate_dir, record["ranked_file"]))
    tatum = f"Jayson Tatum ({JAYSON_TATUM})"
    key = lambda df: {tuple(sorted(r[list(ROSTER_SLOTS)])): r["Total_Projection"] for _, r in df.iterrows()}
    before, after = key(with_55), key(with_52)
    diffs = {round(before[k] - after[k], 6) for k in before if tatum in k}
    assert diffs == {3.0}


def test_clear_overrides(night):
    night.run("--to", "rank", "--proj", "Jayson Tatum=55; Dylan Harper=40")
    night.run("--from", "rank", "--to", "rank", "--clear-overrides", "Jayson Tatum")
    assert _overrides(night.rank_record()) == {(DYLAN_HARPER, "Projection"): 40}

    night.run("--from", "rank", "--to", "rank", "--clear-overrides")
    assert night.rank_record()["overrides"] == []

    night.run("--from", "rank", "--to", "rank", "--proj", "Dylan Harper=40")
    night.run("--from", "rank", "--to", "rank", "--clear-overrides", "--proj", "Jayson Tatum=55")
    assert _overrides(night.rank_record()) == {(JAYSON_TATUM, "Projection"): 55}


def test_clear_caps(night):
    night.run("--to", "rank")
    night.run("--from", "assemble", "--to", "assemble",
              "--max", "Dylan Harper=100; OG Anunoby=50", "--max-all", "100")
    night.run("--from", "assemble", "--to", "assemble", "--clear-caps", "Dylan Harper")
    assert _caps(night.assembly_record()) == ({OG_ANUNOBY: 50}, {}, 100)

    night.run("--from", "assemble", "--to", "assemble", "--clear-caps")
    assert _caps(night.assembly_record()) == ({}, {}, None)


def test_reset_settings_clears_everything(night):
    night.run("-pw", "0.7", "-gw", "0.3", "--proj", "Jayson Tatum=55", "--max", "OG Anunoby=50")
    night.run("--from", "rank", "--to", "assemble", "--reset-settings")

    assert _weights(night.rank_record()) == (0.8, 0.0, 0.2)
    assert night.rank_record()["overrides"] == []
    assert _caps(night.assembly_record()) == ({}, {}, None)


def test_from_export_uses_latest_assembly(night):
    night.run("--to", "rank")
    night.run("--from", "assemble", "--to", "assemble")
    night.run("--from", "assemble", "--to", "assemble", "--max", "OG Anunoby=50")
    latest = os.path.join(night.slate_dir, night.assembly_record()["assembled_file"])
    night.run("--from", "export")

    export = os.path.join(night.slate_dir, night.files("upload-ready-DKEntries-")[-1])
    assert _slot_rows(export) == _slot_rows(latest)
    entry_set = records.read_json(os.path.join(night.slate_dir, night.files("L0-entry-set-")[-1]))
    assert entry_set["assembly_id"] == night.assembly_record()["assembly_id"]


def test_from_after_to_errors(night, capsys):
    night.run("--from", "export", "--to", "rank")
    assert "--from export is after --to rank" in capsys.readouterr().out
    assert not os.path.exists(night.slate_dir)


def test_from_stage_without_prior_artifact_errors(night, capsys):
    night.run("--from", "assemble")
    out = capsys.readouterr().out
    assert "--from assemble: no ranked file found in" in out and night.slate_dir in out


def test_ignored_flag_warns(night, capsys):
    night.run("--to", "rank")
    capsys.readouterr()
    night.run("--from", "assemble", "--to", "assemble", "-pw", "0.5", "-u", "2")
    out = capsys.readouterr().out
    assert "Warning: -pw ignored" in out
    assert "-u ignored" not in out
    assert night.assembly_record()["settings"]["min_unique"] == 2

    night.run("--from", "rank", "--to", "rank", "-u", "2")
    assert "Warning: -u ignored: its stage doesn't run" in capsys.readouterr().out


GUI_BOXES = ("-pw", "0.8", "-ow", "0.0", "-gw", "0.2", "-u", "1")   # the pre-filled boxes as they start


def test_gui_weight_boxes_prefilled(night, capsys):
    """GUI weight boxes start at 0.8/0.0/0.2; a --from rank run uses what they show,
    a cleared box inherits, and untouched boxes raise no ignored-flag warning."""
    parser = FakeGooeyParser()
    cli.add_pipeline_args(parser, gui=True)
    assert {d: o["initial_value"] for d, o in parser.gooey_options.items() if "initial_value" in o} == {
        "proj_weight": "0.8", "own_weight": "0.0", "geo_weight": "0.2", "min_unique": "1"}
    night.run("-pw", "0.7", "-ow", "0.0", "-gw", "0.3", gui=True)
    night.run("--from", "rank", "--to", "rank", *GUI_BOXES, gui=True)
    assert _weights(night.rank_record()) == (0.8, 0.0, 0.2)
    night.run("-pw", "0.7", "-ow", "0.0", "-gw", "0.3", gui=True)
    night.run("--from", "rank", "--to", "rank", "-pw", "0.6", gui=True)    # -ow, -gw boxes cleared
    assert _weights(night.rank_record()) == (0.6, 0.0, 0.3)
    capsys.readouterr()
    night.run("--from", "assemble", "--to", "assemble", *GUI_BOXES, gui=True)
    assert "ignored" not in capsys.readouterr().out
    night.run("--from", "assemble", "--to", "assemble", "-pw", "0.6", "-ow", "0.0", "-gw", "0.2", gui=True)
    out = capsys.readouterr().out
    assert "Warning: -pw ignored" in out
    assert "-ow ignored" not in out and "-gw ignored" not in out


def _shared(path):
    """Most players any two of the file's lineups share."""
    sets = [set(r) for r in _slot_rows(path)]
    return max(len(a & b) for i, a in enumerate(sets) for b in sets[i + 1:])


def test_min_unique_inherited_by_next_assemble(night, capsys):
    """-u carries forward like the caps; --reset-settings and a full run go back to 1."""
    night.run("--to", "rank")
    night.run("--from", "assemble", "--to", "assemble", "-u", "2")
    capsys.readouterr()
    # A non-binding cap that still sends the run through the solver.
    night.run("--from", "assemble", "--to", "assemble", "--max-all", "100")
    record = night.assembly_record()
    assert record["settings"]["min_unique"] == 2
    assert "min_unique" in record["inherited"]
    assert record["solve"]["method"] == "ilp"
    assert "min_unique = 2 (inherited from assembled-lineups-" in capsys.readouterr().out

    night.run("--from", "assemble", "--to", "assemble", "--reset-settings")
    assert night.assembly_record()["settings"]["min_unique"] == 1
    night.run("--from", "assemble", "--to", "assemble", "-u", "2")
    night.run("--to", "assemble")
    assert night.assembly_record()["settings"]["min_unique"] == 1


def test_clear_caps_keeps_min_unique(night):
    night.run("--to", "rank")
    night.run("--from", "assemble", "--to", "assemble", "-u", "2", "--max", "OG Anunoby=50")
    night.run("--from", "assemble", "--to", "assemble", "--clear-caps")
    record = night.assembly_record()
    assert _caps(record) == ({}, {}, None)
    assert record["settings"]["min_unique"] == 2 and "min_unique" in record["inherited"]


def test_gui_cleared_min_unique_box_inherits(night):
    """A -u box left as shown is sent as typed; only a cleared box inherits."""
    night.run("-u", "2", gui=True)
    night.run("--from", "assemble", "--to", "assemble", *GUI_BOXES[:6], gui=True)    # -u box cleared
    assert night.assembly_record()["settings"]["min_unique"] == 2
    night.run("--from", "assemble", "--to", "assemble", *GUI_BOXES, gui=True)        # -u box as shown
    assert night.assembly_record()["settings"]["min_unique"] == 1


def test_bad_min_unique_fails_before_generate(night, capsys):
    night.run("-u", "9")
    assert "0-8" in capsys.readouterr().out
    assert night.engine_calls == 0
    assert night.files("lineup-pool-") == []


def test_full_run_min_unique_applies_at_assemble(night):
    """The pool keeps all 100 lineups; -u 3 leaves 41 survivors and the 40 entries share <= 5 players."""
    night.run("-u", "3")
    pool = os.path.join(night.slate_dir, night.files("lineup-pool-")[0])
    assert len(pd.read_csv(pool)) == 100
    record = night.assembly_record()
    assert record["settings"]["min_unique"] == 3
    assert record["min_unique_removed"] == 59
    export = os.path.join(night.slate_dir, night.files("upload-ready-DKEntries-")[0])
    assert len(_slot_rows(export)) == 40
    assert _shared(export) <= 5


def test_effective_settings_block_names_sources(night, capsys):
    night.run("--to", "rank", "-gw", "0.3")
    capsys.readouterr()
    night.run("--from", "rank", "--to", "rank", "-pw", "0.6")
    out = capsys.readouterr().out
    assert "Effective settings:" in out
    assert "proj_weight = 0.6 (typed)" in out
    assert "geo_weight = 0.3 (inherited from ranked-lineups-2026-10-20_130100.json)" in out


def test_semicolon_lists():
    from nba_optimizer.utils import parse_dk_entries

    df_players = parse_dk_entries(os.path.join(NIGHT_DIR, "Pre-L0-DKEntries.csv"))
    cfg = Config()
    one = parse(["--from", "assemble", "--max", "Dylan Harper=80; Karl-Anthony Towns=20"])
    two = parse(["--from", "assemble", "--max", "Dylan Harper=80", "--max", "Karl-Anthony Towns=20"])
    caps = [resolve_settings(a, cfg, None, ["assemble"], df_players, 40).caps for a in (one, two)]
    assert caps[0].max == caps[1].max == {DYLAN_HARPER: 80, 44451218: 20}


def test_gui_and_cli_share_args():
    """The GUI's parser gets every pipeline option (Gooey is never imported)."""
    dests = []
    for _ in range(2):
        parser = argparse.ArgumentParser()
        cli.add_pipeline_args(parser)
        dests.append({a.dest for a in parser._actions} - {"help"})
    assert dests[0] == dests[1]
    assert {"from_stage", "to_stage", "proj", "own", "max_caps", "min_caps", "max_all",
            "clear_overrides", "clear_caps", "reset_settings", "pool", "ranked", "assembled",
            "slate_dir", "no_slate_folder"} <= dests[0]


def test_bad_cap_value_fails_before_generate(night, capsys):
    """An out-of-range percentage is rejected before the engine runs; nothing is generated."""
    night.run("--max-all", "600")
    assert "0-100" in capsys.readouterr().out
    assert night.engine_calls == 0
    assert night.files("lineup-pool-") == []


def test_clear_caps_by_name_for_player_not_in_pool(tmp_path):
    """An inherited cap on a player missing from tonight's pool can still be cleared by name."""
    from nba_optimizer.utils import parse_dk_entries

    records.write_json_atomic(str(tmp_path / "assembled-lineups-2026-10-20_130000.json"), {
        "generated_at": "2026-10-20T13:00:00-05:00",
        "settings": {"max": [{"dk_id": 999, "name": "Ghost Player", "pct": 50, "count": 20},
                             {"dk_id": OG_ANUNOBY, "name": "OG Anunoby", "pct": 50, "count": 20}],
                     "min": [], "max_all": None},
    })
    df_players = parse_dk_entries(os.path.join(NIGHT_DIR, "Pre-L0-DKEntries.csv"))
    args = parse(["--from", "assemble", "--clear-caps", "Ghost Player"])
    caps = resolve_settings(args, Config(), str(tmp_path), ["assemble"], df_players, 40).caps
    assert caps.max == {OG_ANUNOBY: 50}


def test_past_slate_uses_parent_projections(night, capsys):
    """R2: once the last lock has passed, --from rank uses the parent run's projections copy,
    not the newer export in NBA_PROJS_DIR (which belongs to another slate)."""
    night.run("--to", "rank")
    parent = night.rank_record()
    parent_projs = parent["inputs"]["projections"]["file"]
    night.write_projections("NBA-Projs-2026-10-21_16-00-00.csv", tatum=52)

    night.clock = datetime(2026, 10, 21, 0, 30, tzinfo=CT)  # after the 9:30 PM ET lock
    capsys.readouterr()
    night.run("--from", "rank", "--to", "rank", "--proj", "Jayson Tatum=55")

    out = capsys.readouterr().out
    assert f"past slate: using {parent_projs} from the parent run" in out
    assert "has changed since the parent run" not in out
    record = night.rank_record()
    assert record["parent_run_id"] == parent["run_id"]
    assert record["inputs"]["projections"]["file"] == parent_projs
    assert record["projections_rule"] == "parent"
    # Typed overrides still apply on top; "from" is the parent file's value, not the newer export's 52.
    [o] = record["overrides"]
    assert o["to"] == 55 and o["from"] == pytest.approx(50.5594555)
    assert not [n for n in os.listdir(night.slate_dir) if "2026-10-21_16-00-00" in n]


def test_rank_fails_on_missing_projections(night, capsys):
    """R2: projections covering only part of the pool fail the rank with the count and first 5 names."""
    night.run("--to", "rank")
    before = night.files("ranked-lineups-")

    df = pd.read_csv(night.projs_dir / PROJS_NAME)
    pool_ids = {int(c.rsplit("(", 1)[1][:-1])
                for c in pd.read_csv(RANKED_FIXTURE)[list(ROSTER_SLOTS)].values.ravel()}
    dropped = sorted(pool_ids)[:6]
    df[~df["ID"].isin(dropped)].to_csv(night.projs_dir / "NBA-Projs-2026-10-20_13-58-00.csv", index=False)
    capsys.readouterr()
    night.run("--from", "rank", "--to", "rank")

    out = capsys.readouterr().out
    assert "projections missing for 6 player(s) in the pool, first 5:" in out
    assert "Lineup ranking failed" in out
    assert night.files("ranked-lineups-") == before


def test_no_slate_folder_writes_legacy_layout(night, capsys):
    """R3: with NBA_DATA_ROOT set, --no-slate-folder writes everything to the legacy dirs
    and leaves the slates folder untouched, for full runs and --from runs."""
    night.run("--to", "assemble", "--no-slate-folder")
    night.run("--from", "rank", "--to", "assemble", "--no-slate-folder", "-pw", "0.6")

    assert not os.path.exists(night.cfg.data_root)
    pools = os.listdir(os.path.join(night.cfg.base_dir, "lineup-pools"))
    ranked_dir = os.path.join(night.cfg.base_dir, "ranked-lineups")
    ranked = sorted(os.listdir(ranked_dir))
    assert len(pools) == 1 and pools[0].startswith("lineup-pool-2026-10-20_")
    assert len([n for n in ranked if n.startswith("ranked-lineups-") and n.endswith(".json")]) == 2
    assert len([n for n in ranked if n.startswith("assembled-lineups-") and n.endswith(".json")]) == 2
    rerank = latest_record(ranked_dir, "rank")
    assert rerank["parent_run_id"] and rerank["params"]["proj_weight"] == 0.6

    capsys.readouterr()
    night.run("--no-slate-folder", "--slate-dir", night.slate_dir)
    assert "--no-slate-folder can't be combined with --slate-dir" in capsys.readouterr().out
    assert not os.path.exists(night.cfg.data_root)


def test_past_slate_warns_when_parent_projections_changed(night, capsys):
    """R2: a parent projections file edited in place since the parent run (sha mismatch) warns."""
    night.run("--to", "rank")
    parent_projs = night.rank_record()["inputs"]["projections"]["file"]
    path = os.path.join(night.slate_dir, parent_projs)
    df = pd.read_csv(path)
    df.loc[df["ID"] == JAYSON_TATUM, "Projection"] = 52
    df.to_csv(path, index=False)

    night.clock = datetime(2026, 10, 21, 0, 30, tzinfo=CT)
    capsys.readouterr()
    night.run("--from", "rank", "--to", "rank")
    assert f"Warning: {parent_projs} has changed since the parent run" in capsys.readouterr().out


def test_past_slate_full_run_uses_latest_l0_copy(night, capsys):
    """A full run on a finished slate uses the folder's newest L0 projections copy:
    not the newer export in NBA_PROJS_DIR (another slate's) and not the later L1/L2 copies,
    which carry news from after lock 0."""
    night.run("--to", "rank")
    src = os.path.join(night.slate_dir, "L0-NBA-Projs-2026-10-20_13-55-35.csv")
    copies = {"L0-NBA-Projs-2026-10-20_13-59-41.csv": "2026-10-20T13:59:41-05:00",
              "L2-NBA-Projs-2026-10-20_20-28-20.csv": "2026-10-20T20:28:20-05:00"}
    os.utime(src, (datetime.fromisoformat("2026-10-20T13:55:35-05:00").timestamp(),) * 2)
    for name, iso in copies.items():
        shutil.copy(src, os.path.join(night.slate_dir, name))
        ts = datetime.fromisoformat(iso).timestamp()
        os.utime(os.path.join(night.slate_dir, name), (ts, ts))
    night.write_projections("NBA-Projs-2026-10-21_16-00-00.csv", tatum=52)

    night.clock = datetime(2026, 10, 21, 0, 30, tzinfo=CT)  # after the 9:30 PM ET lock
    capsys.readouterr()
    night.run("--to", "rank")

    out = capsys.readouterr().out
    assert "past slate: using L0-NBA-Projs-2026-10-20_13-59-41.csv, the slate's last L0 projections" in out
    record = night.rank_record()
    assert record["inputs"]["projections"]["file"] == "L0-NBA-Projs-2026-10-20_13-59-41.csv"
    assert record["parent_run_id"] is None
    assert not [n for n in os.listdir(night.slate_dir) if "2026-10-21_16-00-00" in n]


def test_latest_l0_copy_uses_export_time_in_name(tmp_path):
    """A folder copied without modified times still picks the later export by its name."""
    for name, iso in (("L0-NBA-Projs-2026-10-20_13-59-41.csv", "2026-10-21T09:00:00-05:00"),
                      ("L0-NBA-Projs-2026-10-20_13-55-35.csv", "2026-10-21T09:05:00-05:00")):
        (tmp_path / name).write_text("ID,Projection,Own_Proj\n")
        ts = datetime.fromisoformat(iso).timestamp()
        os.utime(tmp_path / name, (ts, ts))
    assert os.path.basename(orchestrator.latest_l0_projections(str(tmp_path))) == "L0-NBA-Projs-2026-10-20_13-59-41.csv"


# --- Alternate slates (O-15) ---


def _tree_state(folder):
    return {n: os.path.getmtime(os.path.join(folder, n)) for n in sorted(os.listdir(folder))}


def test_night_slate_full_run(night, capsys):
    """--slate-type night with DKEntries blank: the night projections and the night download
    (auto-picked past the main one), its own slate folder and upload file, main untouched."""
    night.run()
    main_before = _tree_state(night.slate_dir)
    capsys.readouterr()

    night.run("--slate-type", "night")

    out = capsys.readouterr().out
    assert "Slate type: night\n" in out
    assert f"Projections: {NIGHT_PROJS_NAME} (newest in projections-night)\n" in out
    assert "DKEntries: DKEntries (1).csv (auto: newest matching download; 125 of 125 players)\n" in out
    assert os.path.isdir(night.night_slate_dir)
    with open(os.path.join(night.night_slate_dir, "Pre-L0-DKEntries.csv"), encoding="utf-8") as a, \
            open(night.twin_entries, encoding="utf-8") as b:
        assert a.read() == b.read()
    assert [n for n in os.listdir(night.downloads) if n.startswith("upload-ready-DKEntries-Night-2026-10-20_")]
    assert _tree_state(night.slate_dir) == main_before


def test_main_run_ignores_night_files(night, capsys):
    """A night export saved in the main folder under a newer name is skipped, not used for main."""
    night.run("--slate-type", "night")
    shutil.copy(night.night_projs_dir / NIGHT_PROJS_NAME, night.projs_dir / "NBA-Projs-Night-2026-10-20_14-30-00.csv")
    capsys.readouterr()

    night.run()

    out = capsys.readouterr().out
    assert ("Warning: skipping NBA-Projs-Night-2026-10-20_14-30-00.csv in the main projections folder "
            "(named for night)") in out
    assert f"Projections: {PROJS_NAME} (newest in projections)" in out
    assert night.rank_record()["inputs"]["projections"]["file"] == "L0-NBA-Projs-2026-10-20_13-55-35.csv"


def test_wrong_slate_type_fails_clean(night, capsys):
    """The night DKEntries chosen with slate type main fails before any slate folder is written."""
    night.run("--entries", night.twin_entries)
    assert "matches 0 of 125 players in DKEntries (1).csv" in capsys.readouterr().out
    assert not os.path.exists(night.cfg.data_root)
    assert night.engine_calls == 0


def test_entries_ignored_with_slate_dir(night, capsys):
    """--slate-dir works from the folder's own Pre-L0-DKEntries; --entries and a different --slate-type warn."""
    night.run("--to", "rank")
    capsys.readouterr()
    night.run("--from", "assemble", "--to", "assemble", "--slate-dir", night.slate_dir,
              "--entries", night.twin_entries, "--slate-type", "night")
    out = capsys.readouterr().out
    assert "Warning: --entries ignored: --slate-dir uses the folder's Pre-L0-DKEntries.csv." in out
    assert "Warning: --slate-type night ignored: 2026-10-20_classic_main is a main slate." in out
    assert "Error" not in out


GUI_ORDER = [
    "late_swap", "from_stage", "to_stage", "num_lineups", "randomness", "min_unique", "min_salary",
    "min_projection", "proj_weight", "own_weight", "geo_weight",
    "top_x", "slate_type", "entries", "no_slate_folder", "slate_dir", "max_caps", "max_all",
    "proj", "own", "min_caps", "clear_overrides", "clear_caps", "reset_settings", "pool", "ranked",
    "assembled", "seed",
]


def gui_dests():
    parser = FakeGooeyParser()
    cli.add_pipeline_args(parser, gui=True)
    return [a.dest for a in parser._actions if a.dest != "help"]


def test_gui_arg_order():
    """Jonny's GUI order (O-15 §3.14): top_x, slate type and the DKEntries chooser right after the weights."""
    assert gui_dests() == GUI_ORDER


def test_entries_is_file_chooser():
    """DKEntries is a file chooser in the GUI (a plain path on the CLI)."""
    parser = FakeGooeyParser()
    cli.add_pipeline_args(parser, gui=True)
    assert parser.widgets == {"entries": "FileChooser"}
    assert "default_dir" in parser.gooey_options["entries"]
