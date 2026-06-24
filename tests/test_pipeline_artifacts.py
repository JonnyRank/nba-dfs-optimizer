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
