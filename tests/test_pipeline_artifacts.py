"""Tests for explicit artifact handoff between pipeline stages.

These verify that `ranker.run()`, `exporter.run()`, and
`exposure_report._resolve_entries_file()` all honour explicit file paths
passed by the orchestrator, without falling back to latest-file discovery.

Each test:
- writes a minimal synthetic CSV to a temporary directory, and
- confirms the stage returns the expected output path (for ranker / exporter)
  or resolves the expected input path (for exposure_report) when an explicit
  path is supplied.

No LP solving or multiprocessing is involved.
"""

import os
import shutil
import textwrap
from dataclasses import replace

import pandas as pd
import pytest

from nba_optimizer.config import Config, ROSTER_SLOTS

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# Eight real players from the unfilled-DKEntries.csv fixture, one per DK slot.
# Their IDs exist in that file; their Roster Positions make each slot assignment valid.
_LINEUP = [
    "Luka Doncic (42398185)",       # PG  — PG/G/UTIL
    "Anthony Edwards (42398202)",   # SG  — SG/G/UTIL
    "Jaylen Brown (42398210)",      # SF  — SG/SF/F/G/UTIL
    "Jalen Johnson (42398193)",     # PF  — PF/F/UTIL
    "Victor Wembanyama (42398188)", # C   — C/UTIL
    "Cade Cunningham (42398190)",   # G   — PG/G/UTIL
    "Julius Randle (42398237)",     # F   — PF/F/UTIL
    "Joel Embiid (42398208)",       # UTIL — C/UTIL
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path) -> Config:
    """Return a Config wired to subdirectories of tmp_path."""
    return Config(
        entries_path=str(tmp_path / "DKEntries.csv"),
        projs_dir=str(tmp_path / "projections"),
        base_dir=str(tmp_path / "exports"),
        output_dir=str(tmp_path / "exports"),
        lineup_pool_dir=str(tmp_path / "exports" / "lineup-pools"),
        ranked_lineup_dir=str(tmp_path / "exports" / "ranked-lineups"),
    )


def _build_projs_csv(path: str) -> None:
    """Write a projections CSV for the 8 real players used in lineup pool fixtures.

    Uses IDs that exist in the unfilled-DKEntries.csv fixture. DK-owned columns
    (Salary, Position, Game Info, etc.) are omitted — merge_player_pool drops
    those from df_projs and uses the DKEntries values as authoritative.
    """
    players = [
        ("42398185", "Luka Doncic",           40.0, 20.0),
        ("42398202", "Anthony Edwards",        39.0, 18.0),
        ("42398210", "Jaylen Brown",           38.0, 15.0),
        ("42398193", "Jalen Johnson",          37.0, 14.0),
        ("42398188", "Victor Wembanyama",      36.0, 12.0),
        ("42398190", "Cade Cunningham",        35.0, 10.0),
        ("42398237", "Julius Randle",          34.0, 8.0),
        ("42398208", "Joel Embiid",            33.0, 6.0),
    ]
    df = pd.DataFrame(
        [{"ID": pid, "Name": name, "Projection": proj, "Own_Proj": own}
         for pid, name, proj, own in players]
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _build_dkentries_csv(path: str) -> None:
    """Copy the real unfilled DKEntries fixture to path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copy(os.path.join(FIXTURES_DIR, "unfilled-DKEntries.csv"), path)


def _build_lineup_pool_csv(path: str) -> None:
    """Write a two-lineup pool CSV using real player IDs from the DKEntries fixture."""
    slots = list(ROSTER_SLOTS)
    df = pd.DataFrame([_LINEUP, _LINEUP], columns=slots)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _build_ranked_lineups_csv(path: str) -> None:
    """Write a minimal ranked-lineups CSV using real player IDs from the DKEntries fixture."""
    slots = list(ROSTER_SLOTS)
    row = {
        "Final_Rank": 1,
        "Lineup_Score": 1.0,
        "Total_Projection": 292.0,
        "Total_Ownership": 103.0,
        "Geomean_Ownership": 12.0,
        "Proj_Rank": 1.0,
        "Own_Rank": 1.0,
        "Geo_Rank": 1.0,
    }
    for slot, player in zip(slots, _LINEUP):
        row[slot] = player
    df = pd.DataFrame([row])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _build_export_csv(path: str) -> None:
    """Write a minimal upload-ready export CSV for exposure_report tests."""
    slots = list(ROSTER_SLOTS)
    row = {"Entry ID": "5096367541",
           "Contest Name": "NBA $20K Four Point Play [20 Entry Max]",
           "Contest ID": "189162278", "Entry Fee": "$4"}
    for slot, player in zip(slots, _LINEUP):
        row[slot] = player
    df = pd.DataFrame([row])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRankerExplicitLineupFile:
    """ranker.run() honours an explicit lineup_file and projs_file."""

    def test_returns_output_path_when_explicit_files_given(self, tmp_path):
        """ranker.run() writes a ranked CSV and returns its path."""
        from nba_optimizer import ranker

        cfg = _make_config(tmp_path)

        # Create required directories
        os.makedirs(cfg.ranked_lineup_dir, exist_ok=True)
        os.makedirs(cfg.projs_dir, exist_ok=True)

        lineup_pool_path = str(tmp_path / "exports" / "lineup-pools" / "lineup-pool-2026-01-01_120000.csv")
        projs_path = str(tmp_path / "projections" / "NBA-Projs-2026-01-01.csv")

        _build_lineup_pool_csv(lineup_pool_path)
        _build_projs_csv(projs_path)
        # Write DKEntries for the engine.load_data call inside ranker
        _build_dkentries_csv(cfg.entries_path)

        result = ranker.run(
            cfg,
            lineup_file=lineup_pool_path,
            projs_file=projs_path,
        )

        # Result must be a non-empty path that actually exists.
        assert result, "ranker.run() returned empty string — expected an output path"
        assert os.path.isfile(result), f"Returned path does not exist: {result}"
        assert "ranked-lineups" in os.path.basename(result)

    def test_uses_explicit_lineup_file_not_latest(self, tmp_path):
        """ranker.run() reads the explicitly named file even when it is not the newest on disk.

        The stale file (0 rows) has the newest timestamp name and would be picked by
        get_latest_file(). The explicit file (2 rows) has an older timestamp. If the
        output has 2 rows, explicit binding won over latest-file discovery.
        """
        from nba_optimizer import ranker

        cfg = _make_config(tmp_path)
        os.makedirs(cfg.ranked_lineup_dir, exist_ok=True)
        os.makedirs(cfg.projs_dir, exist_ok=True)

        # Stale pool: 0 rows, NEWEST name — get_latest_file() would pick this.
        stale_path = str(tmp_path / "exports" / "lineup-pools" / "lineup-pool-2026-01-01_235959.csv")
        os.makedirs(os.path.dirname(stale_path), exist_ok=True)
        pd.DataFrame(columns=list(ROSTER_SLOTS)).to_csv(stale_path, index=False)

        # Explicit pool: 2 rows, OLDER name — only used if explicit binding works.
        explicit_path = str(tmp_path / "exports" / "lineup-pools" / "lineup-pool-2026-01-01_000000.csv")
        projs_path = str(tmp_path / "projections" / "NBA-Projs-2026-01-01.csv")

        _build_lineup_pool_csv(explicit_path)
        _build_projs_csv(projs_path)
        _build_dkentries_csv(cfg.entries_path)

        result = ranker.run(cfg, lineup_file=explicit_path, projs_file=projs_path)
        assert result and os.path.isfile(result)

        # 2 rows means the explicit (older) file was used, not the stale newest file.
        df_out = pd.read_csv(result)
        assert len(df_out) == 2


class TestExporterExplicitRankedFile:
    """exporter.run() honours an explicit ranked_file."""

    def test_returns_output_path_when_explicit_file_given(self, tmp_path):
        """exporter.run() writes an export CSV and returns its path."""
        from nba_optimizer import exporter

        cfg = _make_config(tmp_path)
        os.makedirs(cfg.output_dir, exist_ok=True)

        ranked_path = str(tmp_path / "exports" / "ranked-lineups" / "ranked-lineups-2026-01-01_120000.csv")
        _build_ranked_lineups_csv(ranked_path)
        _build_dkentries_csv(cfg.entries_path)

        result = exporter.run(cfg, ranked_file=ranked_path)

        assert result, "exporter.run() returned empty string — expected an output path"
        assert os.path.isfile(result), f"Returned path does not exist: {result}"
        assert "upload-ready-DKEntries" in os.path.basename(result)

    def test_uses_explicit_ranked_file_not_latest(self, tmp_path):
        """exporter.run() uses the passed ranked_file even when it is not the newest on disk.

        The stale file (0 lineups) has the newest timestamp name and would be picked by
        get_latest_file(). The explicit file (1 lineup) has an older timestamp. A filled
        entry slot in the output proves the explicit file was used.
        """
        from nba_optimizer import exporter

        cfg = _make_config(tmp_path)
        os.makedirs(cfg.ranked_lineup_dir, exist_ok=True)
        os.makedirs(cfg.output_dir, exist_ok=True)

        # Stale ranked file: 0 lineups, NEWEST name — get_latest_file() would pick this.
        stale_path = str(tmp_path / "exports" / "ranked-lineups" / "ranked-lineups-2026-01-01_235959.csv")
        cols = ["Final_Rank", "Lineup_Score", "Total_Projection",
                "Total_Ownership", "Geomean_Ownership", "Proj_Rank",
                "Own_Rank", "Geo_Rank"] + list(ROSTER_SLOTS)
        os.makedirs(os.path.dirname(stale_path), exist_ok=True)
        pd.DataFrame(columns=cols).to_csv(stale_path, index=False)

        # Explicit ranked file: 1 lineup, OLDER name — only used if explicit binding works.
        explicit_path = str(tmp_path / "exports" / "ranked-lineups" / "ranked-lineups-2026-01-01_000000.csv")
        _build_ranked_lineups_csv(explicit_path)
        _build_dkentries_csv(cfg.entries_path)

        result = exporter.run(cfg, ranked_file=explicit_path)
        assert result and os.path.isfile(result)

        # A filled entry slot proves the explicit (older, 1-lineup) file was used, not the stale newest.
        df_out = pd.read_csv(result)
        filled = df_out["Entry ID"].notna()
        assert df_out.loc[filled, ROSTER_SLOTS[0]].notna().any()


class TestExposureReportResolveEntriesFile:
    """exposure_report._resolve_entries_file() still honours explicit entries_file."""

    def test_returns_explicit_path_when_file_exists(self, tmp_path):
        """_resolve_entries_file returns the explicit path if the file is present."""
        from nba_optimizer.exposure_report import _resolve_entries_file

        cfg = _make_config(tmp_path)
        explicit_path = str(tmp_path / "exports" / "upload-ready-DKEntries-2026-01-01_120000.csv")
        _build_export_csv(explicit_path)

        resolved = _resolve_entries_file(cfg, entries_file=explicit_path)
        assert resolved == explicit_path

    def test_raises_when_explicit_path_not_found(self, tmp_path):
        """_resolve_entries_file raises FileNotFoundError for a missing explicit path."""
        from nba_optimizer.exposure_report import _resolve_entries_file

        cfg = _make_config(tmp_path)
        missing_path = str(tmp_path / "exports" / "nonexistent.csv")

        with pytest.raises(FileNotFoundError):
            _resolve_entries_file(cfg, entries_file=missing_path)

    def test_falls_back_to_latest_when_no_explicit_path(self, tmp_path):
        """_resolve_entries_file finds the newest export when no path is given."""
        from nba_optimizer.exposure_report import _resolve_entries_file

        cfg = _make_config(tmp_path)
        export_path = str(tmp_path / "exports" / "upload-ready-DKEntries-2026-01-01_120000.csv")
        _build_export_csv(export_path)

        resolved = _resolve_entries_file(cfg, entries_file=None)
        assert resolved == export_path


# ---------------------------------------------------------------------------
# Run records and entry sets (nightly capture, O-0) on the 2026-10-20 files
# ---------------------------------------------------------------------------

NIGHT_DIR = os.path.join(FIXTURES_DIR, "2026-10-20")


def _opening_night_run(tmp_path, run_time=None):
    """Slate folder for 10/20 plus a ranker run on a pool made from the ranked fixture's lineups.

    The default run instant is after midnight (00:30 on 10/21) so the
    filenames must take the slate date, not the run date.
    """
    from datetime import datetime
    from nba_optimizer import ranker
    from nba_optimizer.slate import load_or_write_slate

    cfg = Config(
        data_root=str(tmp_path / "slates"),
        projs_dir=str(tmp_path / "projections"),
        output_dir=str(tmp_path / "downloads"),
    )
    os.makedirs(cfg.output_dir)
    slate, slate_dir = load_or_write_slate(cfg, os.path.join(NIGHT_DIR, "Pre-L0-DKEntries.csv"))
    cfg = replace(
        cfg,
        entries_path=os.path.join(slate_dir, "Pre-L0-DKEntries.csv"),
        lineup_pool_dir=slate_dir,
        ranked_lineup_dir=slate_dir,
    )
    projs = os.path.join(slate_dir, "L0-NBA-Projs-2026-10-20_13-55-35.csv")
    shutil.copy(os.path.join(NIGHT_DIR, "L0-NBA-Projs-2026-10-20_13-55-35.csv"), projs)
    pool = os.path.join(slate_dir, "lineup-pool-2026-10-20_003000.csv")
    pd.read_csv(os.path.join(NIGHT_DIR, "ranked-lineups-2026-10-20_135723.csv"))[list(ROSTER_SLOTS)].to_csv(
        pool, index=False
    )
    run_time = run_time or datetime(2026, 10, 21, 0, 30, 0).astimezone()
    ranked = ranker.run(
        cfg, proj_weight=0.8, own_weight=0.0, geo_weight=0.2,
        lineup_file=pool, projs_file=projs,
        num_lineups=2500, randomness=0.25, base_seed=987654321,
        slate=slate, run_time=run_time,
    )
    return cfg, slate_dir, ranked, run_time


def test_ranker_writes_run_record(tmp_path):
    """The run record sits next to the ranked CSV with the same name and complete inputs/params."""
    from nba_optimizer import records

    _, slate_dir, ranked, run_time = _opening_night_run(tmp_path)

    assert os.path.basename(ranked) == "ranked-lineups-2026-10-20_003000.csv"
    record = records.read_json(ranked[:-4] + ".json")
    assert record["run_id"] == f"2026-10-20_classic_main_{run_time:%Y%m%dT%H%M%S}"
    assert record["slate_id"] == "2026-10-20_classic_main"
    assert record["ranked_file"] == os.path.basename(ranked)
    assert record["pool_file"] == "lineup-pool-2026-10-20_003000.csv"
    assert record["params_source"] == "cli"
    assert record["inputs"]["projections"]["file"] == "L0-NBA-Projs-2026-10-20_13-55-35.csv"
    assert record["inputs"]["projections"]["layout"] == "basic"
    assert record["inputs"]["entries"]["sha256"] == records.sha256_file(
        os.path.join(NIGHT_DIR, "Pre-L0-DKEntries.csv"))
    assert len(record["inputs"]["projections"]["sha256"]) == 64
    params = record["params"]
    # -u applies at assemble (O-14); the assembly record holds it.
    assert params["min_unique"] is None
    assert None not in {k: v for k, v in params.items() if k != "min_unique"}.values()
    assert isinstance(params["base_seed"], int) and params["base_seed"] == 987654321
    assert params["lineups_written"] == 100


def test_exporter_writes_L0_entry_set(tmp_path):
    """Rank i goes to entry i: 1-20 in the $4 contest, 21-40 in the $1 contest."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from nba_optimizer import exporter, records

    # 13:57:23 CT, three minutes before lock 0 (3:00 PM ET).
    pre_lock = datetime(2026, 10, 20, 13, 57, 23, tzinfo=ZoneInfo("America/Chicago")).astimezone()
    cfg, slate_dir, ranked, run_time = _opening_night_run(tmp_path, pre_lock)
    export = exporter.run(cfg, ranked_file=ranked, run_time=run_time)

    assert os.path.dirname(export) == cfg.output_dir
    assert os.path.isfile(os.path.join(slate_dir, os.path.basename(export)))
    entry_set = records.read_json(os.path.join(slate_dir, f"L0-entry-set-{run_time:%Y%m%dT%H%M%S}.json"))
    assert entry_set["source"] == "optimizer"
    assert entry_set["run_id"] == records.read_json(ranked[:-4] + ".json")["run_id"]

    entries = entry_set["entries"]
    assert len(entries) == 40
    assert [e["pre_lock_rank"] for e in entries] == list(range(1, 41))
    assert {e["contest_id"] for e in entries[:20]} == {196456024}
    assert {e["contest_id"] for e in entries[20:]} == {196456031}
    assert all(isinstance(pid, int) for e in entries for pid in e["lineup"].values())


def test_exporter_skips_entry_set_after_last_lock(tmp_path):
    """A run after the slate's last lock writes the upload file but no L0 entry set."""
    from datetime import datetime
    from nba_optimizer import exporter, records

    cfg, slate_dir, ranked, _ = _opening_night_run(tmp_path)
    run_record_path = ranked[:-4] + ".json"
    record = records.read_json(run_record_path)
    assert record["lock"] is None  # 00:30 on 10/21 is after the 9:30 PM ET lock
    export = exporter.run(cfg, ranked_file=ranked, run_time=datetime(2026, 10, 21, 0, 31).astimezone())

    assert os.path.isfile(export)
    assert not [n for n in os.listdir(slate_dir) if "-entry-set-" in n]


# ---------------------------------------------------------------------------
# Stage control (O-13): assemblies, entry sets and default weights
# ---------------------------------------------------------------------------


def test_export_entry_set_links_assembly(tmp_path):
    """Exporting an assembly: entry set carries assembly_id and run_id, ranks are Final_Rank, 20/20 split."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from nba_optimizer import assembler, exporter, records
    from nba_optimizer.assembler import AssembleSettings

    pre_lock = datetime(2026, 10, 20, 13, 57, 23, tzinfo=ZoneInfo("America/Chicago")).astimezone()
    cfg, slate_dir, ranked, run_time = _opening_night_run(tmp_path, pre_lock)
    # OG Anunoby (44451272) capped at 50%: the 40 are no longer ranks 1-40.
    assembled = assembler.run(cfg, ranked, AssembleSettings(n_entries=40, max={44451272: 50}), run_time=run_time)
    export = exporter.run(cfg, assembled_file=assembled, run_time=run_time)

    assembly = records.read_json(assembled[:-4] + ".json")
    entry_set = records.read_json(os.path.join(slate_dir, f"L0-entry-set-{run_time:%Y%m%dT%H%M%S}.json"))
    assert entry_set["assembly_id"] == assembly["assembly_id"]
    assert entry_set["run_id"] == records.read_json(ranked[:-4] + ".json")["run_id"] == assembly["run_id"]

    entries = entry_set["entries"]
    df_assembled = pd.read_csv(assembled)
    assert [e["pre_lock_rank"] for e in entries] == df_assembled["Final_Rank"].tolist()
    assert entries[-1]["pre_lock_rank"] > 40
    assert {e["contest_id"] for e in entries[:20]} == {196456024}
    assert {e["contest_id"] for e in entries[20:]} == {196456031}
    assert [e["entry_id"] for e in entries] == records.read_json(os.path.join(slate_dir, "slate.json"))["entry_ids"]
    assert os.path.isfile(export)


def test_export_after_lock_0_writes_no_entry_set(tmp_path, capsys):
    """Stages are pre-lock tools: an export between lock 0 and lock 1 writes the CSV only (§3.13)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from nba_optimizer import exporter

    pre_lock = datetime(2026, 10, 20, 13, 57, 23, tzinfo=ZoneInfo("America/Chicago")).astimezone()
    cfg, slate_dir, ranked, _ = _opening_night_run(tmp_path, pre_lock)
    after_l0 = datetime(2026, 10, 20, 15, 0, 0, tzinfo=ZoneInfo("America/Chicago")).astimezone()
    export = exporter.run(cfg, ranked_file=ranked, run_time=after_l0)

    assert os.path.isfile(export)
    assert not [n for n in os.listdir(slate_dir) if "-entry-set-" in n]
    assert "late swaps are captured by nba-dfs-capture finalize / record" in capsys.readouterr().out


def test_ranker_standalone_default_weights(tmp_path, monkeypatch):
    """python -m nba_optimizer.ranker ranks with the Config defaults 0.8/0/0.2."""
    import sys
    from nba_optimizer import ranker, records

    cfg = _make_config(tmp_path)
    _build_lineup_pool_csv(os.path.join(cfg.lineup_pool_dir, "lineup-pool-2026-01-01_120000.csv"))
    _build_projs_csv(os.path.join(cfg.projs_dir, "NBA-Projs-2026-01-01.csv"))
    _build_dkentries_csv(cfg.entries_path)
    monkeypatch.setattr("nba_optimizer.config.load_config_from_env", lambda: cfg)
    monkeypatch.setattr(sys, "argv", ["ranker"])

    ranker.main()

    [record] = [n for n in os.listdir(cfg.ranked_lineup_dir) if n.endswith(".json")]
    params = records.read_json(os.path.join(cfg.ranked_lineup_dir, record))["params"]
    assert (params["proj_weight"], params["own_weight"], params["geo_weight"]) == (0.8, 0.0, 0.2)


def test_exporter_without_assembly_skips_duplicate_lineups(tmp_path):
    """Exporting straight from a ranked file (no assembly) never uploads the same lineup twice:
    a copy of rank 1 at rank 2 is skipped, so the 40 entries are ranks 1, 3..41."""
    from nba_optimizer import exporter

    df = pd.read_csv(os.path.join(NIGHT_DIR, "ranked-lineups-2026-10-20_135723.csv"))
    df = pd.concat([df.iloc[[0]], df], ignore_index=True)
    df["Final_Rank"] = range(1, len(df) + 1)
    ranked = str(tmp_path / "ranked-lineups-2026-10-20_135723.csv")
    df.to_csv(ranked, index=False)
    cfg = Config(entries_path=os.path.join(NIGHT_DIR, "Pre-L0-DKEntries.csv"),
                 output_dir=str(tmp_path / "out"), base_dir=str(tmp_path / "exports"))
    os.makedirs(cfg.output_dir)

    export = exporter.run(cfg, ranked_file=ranked)
    df_out = pd.read_csv(export)
    rows = df_out[df_out["Entry ID"].notna()][list(ROSTER_SLOTS)].values.tolist()
    expected = df.iloc[[0] + list(range(2, 41))][list(ROSTER_SLOTS)].values.tolist()
    assert rows == expected
