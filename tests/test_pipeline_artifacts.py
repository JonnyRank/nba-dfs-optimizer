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
import textwrap
from dataclasses import replace

import pandas as pd
import pytest

from nba_optimizer.config import Config, ROSTER_SLOTS


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
    """Write a minimal projections CSV with the columns ranker/engine expects.

    Note: do NOT include 'Game Info' here — that column comes from the DKEntries
    player pool section. Including it would cause pandas to suffix-rename it in
    the merge (Game Info_x / Game Info_y) and break engine.load_data.
    """
    df = pd.DataFrame(
        [
            {"ID": "1", "Name": "PG1", "Projection": 40.0, "Own_Proj": 20.0},
            {"ID": "2", "Name": "SG1", "Projection": 39.0, "Own_Proj": 18.0},
            {"ID": "3", "Name": "SF1", "Projection": 38.0, "Own_Proj": 15.0},
            {"ID": "4", "Name": "PF1", "Projection": 37.0, "Own_Proj": 14.0},
            {"ID": "5", "Name": "C1",  "Projection": 36.0, "Own_Proj": 12.0},
            {"ID": "6", "Name": "G1",  "Projection": 35.0, "Own_Proj": 10.0},
            {"ID": "7", "Name": "F1",  "Projection": 34.0, "Own_Proj": 8.0},
            {"ID": "8", "Name": "U1",  "Projection": 33.0, "Own_Proj": 6.0},
        ]
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _build_dkentries_csv(path: str) -> None:
    """Write a DKEntries CSV that works for both exporter and the shared loader.

    The real DraftKings DKEntries.csv has two sections:
    - Row 0: entry header (Entry ID, Contest Name, ..., roster slots)
    - Rows 1-N: filled entry rows
    - Rows N+1+: player-pool section beginning with a header that contains
      "Position,Name + ID,Name,ID" (the sentinel ``parse_dk_entries`` searches for)

    ``exporter`` uses ``read_ragged_csv`` which reads row 0 as the header.
    ``parse_dk_entries`` (used by engine, late_swapper, and ranker) scans for
    the sentinel line and reads from there onward.
    """
    slots = list(ROSTER_SLOTS)
    slot_header = ",".join(slots)
    empty_slots = ",".join([""] * len(slots))

    # Player pool header must contain "Position,Name + ID,Name,ID" exactly so
    # that parse_dk_entries can locate the section.  The real DK format is:
    # Position, Name + ID, Name, ID, Roster Position, Salary, Game Info, ...
    player_rows = "\n".join([
        "PG,PG1 (1),PG1,1,PG,6200,GAMEA@GAMEB 01/01/2026 07:00PM ET",
        "SG,SG1 (2),SG1,2,SG,6200,GAMEA@GAMEB 01/01/2026 07:00PM ET",
        "SF,SF1 (3),SF1,3,SF,6200,GAMEA@GAMEB 01/01/2026 07:00PM ET",
        "PF,PF1 (4),PF1,4,PF,6200,GAMEA@GAMEB 01/01/2026 07:00PM ET",
        "C,C1 (5),C1,5,C,6200,GAMEA@GAMEB 01/01/2026 07:00PM ET",
        "PG,G1 (6),G1,6,PG/SG,6200,GAMEC@GAMED 01/01/2026 09:00PM ET",
        "SF,F1 (7),F1,7,SF/PF,6200,GAMEC@GAMED 01/01/2026 09:00PM ET",
        "C,U1 (8),U1,8,C,6200,GAMEC@GAMED 01/01/2026 09:00PM ET",
    ])

    content = (
        f"Entry ID,Contest Name,Contest ID,Entry Fee,{slot_header}\n"
        f"111111,Main Slate,999999,3,{empty_slots}\n"
        f"222222,Main Slate,999999,3,{empty_slots}\n"
        + "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info\n"
        + player_rows + "\n"
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _build_lineup_pool_csv(path: str) -> None:
    """Write a two-lineup pool CSV in the format engine produces."""
    slots = list(ROSTER_SLOTS)
    rows = [
        ["PG1 (1)", "SG1 (2)", "SF1 (3)", "PF1 (4)", "C1 (5)", "G1 (6)", "F1 (7)", "U1 (8)"],
        ["PG1 (1)", "SG1 (2)", "SF1 (3)", "PF1 (4)", "C1 (5)", "G1 (6)", "F1 (7)", "U1 (8)"],
    ]
    df = pd.DataFrame(rows, columns=slots)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _build_ranked_lineups_csv(path: str) -> None:
    """Write a minimal ranked-lineups CSV in the format ranker produces."""
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
    for i, slot in enumerate(slots):
        row[slot] = f"Player{i + 1} ({i + 1})"
    df = pd.DataFrame([row])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _build_export_csv(path: str) -> None:
    """Write a minimal upload-ready export CSV for exposure_report tests."""
    slots = list(ROSTER_SLOTS)
    players = [f"Player{i + 1} ({i + 1})" for i in range(len(slots))]
    row = {"Entry ID": "111111", "Contest Name": "Main Slate",
           "Contest ID": "999999", "Entry Fee": "3"}
    for slot, player in zip(slots, players):
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
