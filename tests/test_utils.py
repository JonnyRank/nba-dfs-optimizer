"""Deterministic tests for shared parsing helpers in nba_optimizer.utils.

These cover the small, pure-function behaviors that the rest of the
pipeline (engine, ranker, exporter, late_swapper) all rely on for parsing
DraftKings CSV exports.
"""

import io
import os
import textwrap
from datetime import datetime

import pandas as pd
import pytest

from nba_optimizer.utils import (
    extract_player_id,
    merge_player_pool,
    parse_dk_entries,
    parse_game_time,
    read_ragged_csv,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_extract_player_id_from_name_and_id_string():
    """A normal 'Name (ID)' string yields the numeric ID."""
    assert extract_player_id("LeBron James (12345)") == "12345"


def test_extract_player_id_handles_missing_value():
    """A null/missing player value returns None instead of raising."""
    assert extract_player_id(pd.NA) is None
    assert extract_player_id(None) is None


def test_extract_player_id_returns_none_without_id():
    """A string with no parenthesized ID returns None."""
    assert extract_player_id("LeBron James") is None


def test_parse_game_time_valid_dk_game_info():
    """A valid DK 'Game Info' string parses to the expected datetime."""
    result = parse_game_time("MIA@PHI 02/25/2026 07:00PM ET")
    assert result == datetime(2026, 2, 25, 19, 0)


def test_parse_game_time_invalid_falls_back_to_max():
    """An unparseable game-info string falls back to datetime.max."""
    assert parse_game_time("not a real game info string") == datetime.max


def test_read_ragged_csv_preserves_valid_columns_and_pads_ragged_rows():
    """read_ragged_csv keeps the real header columns and pads short/long rows."""
    csv_path = os.path.join(FIXTURES_DIR, "ragged_sample.csv")

    df_ragged, valid_cols = read_ragged_csv(csv_path, max_columns=6)

    # The original 4 header columns are reported back unchanged.
    assert valid_cols == ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]

    # The padded frame has 2 extra dummy columns appended.
    assert df_ragged.columns.tolist() == valid_cols + ["extra_0", "extra_1"]

    # The first row had no extra values, so the padding columns are NaN.
    assert pd.isna(df_ragged.loc[0, "extra_0"])
    assert pd.isna(df_ragged.loc[0, "extra_1"])

    # The second (ragged) row's extra values land in the padding columns.
    assert df_ragged.loc[1, "extra_0"] == "extra_value_a"
    assert df_ragged.loc[1, "extra_1"] == "extra_value_b"

    # Valid columns retain their original data for both rows. Entry ID is
    # read as a string (object dtype) to avoid losing precision on large IDs.
    assert df_ragged.loc[0, "Entry ID"] == "111"
    assert df_ragged.loc[1, "Entry ID"] == "333"


# ---------------------------------------------------------------------------
# Shared player-pool loader contract tests
# ---------------------------------------------------------------------------

_DKENTRIES_CONTENT = textwrap.dedent("""\
    Entry ID,Contest Name,Contest ID,Entry Fee,PG,SG,SF,PF,C,G,F,UTIL
    111111,Main Slate,999999,3,,,,,,,,
    Position,Name + ID,Name,ID,Roster Position,Salary,Game Info
    PG,Alice (1),Alice,1,PG,6200,AAA@BBB 01/01/2026 07:00PM ET
    SG,Bob (2),Bob,2,SG,5800,AAA@BBB 01/01/2026 07:00PM ET
""")

_PROJS_CONTENT = textwrap.dedent("""\
    ID,Name,Projection,Own_Proj,Team,Opponent
    1,Alice,42.0,25.0,AAA,BBB
""")


@pytest.fixture()
def dk_entries_file(tmp_path):
    p = tmp_path / "DKEntries.csv"
    p.write_text(_DKENTRIES_CONTENT, encoding="utf-8")
    return str(p)


@pytest.fixture()
def projs_df():
    return pd.read_csv(io.StringIO(_PROJS_CONTENT))


def test_parse_dk_entries_finds_player_pool_section(dk_entries_file):
    """parse_dk_entries returns only the player-pool rows with normalized IDs."""
    df = parse_dk_entries(dk_entries_file)
    assert list(df["ID"]) == ["1", "2"]
    assert "Name + ID" in df.columns


def test_parse_dk_entries_raises_on_missing_sentinel(tmp_path):
    """parse_dk_entries raises ValueError when no player-pool header is found."""
    bad = tmp_path / "bad.csv"
    bad.write_text("Entry ID,Contest Name\n111,Main\n")
    with pytest.raises(ValueError, match="Could not find player pool section"):
        parse_dk_entries(str(bad))


def test_merge_player_pool_inner_drops_unmatched_players(projs_df):
    """inner merge keeps only players present in both pool and projections."""
    df_players = pd.DataFrame([
        {"ID": "1", "Name + ID": "Alice (1)", "Roster Position": "PG",
         "Salary": "6200", "Game Info": "AAA@BBB 01/01/2026 07:00PM ET"},
        {"ID": "2", "Name + ID": "Bob (2)", "Roster Position": "SG",
         "Salary": "5800", "Game Info": "AAA@BBB 01/01/2026 07:00PM ET"},
    ])
    df = merge_player_pool(df_players, projs_df, how="inner")
    # Bob (ID=2) has no projection entry — inner merge excludes him
    assert len(df) == 1
    assert df.iloc[0]["ID"] == "1"
    assert df.iloc[0]["Projection"] == 42.0


def test_merge_player_pool_left_raises_for_unmatched_player(projs_df):
    """left merge raises ValueError when a pool player has no projection entry."""
    df_players = pd.DataFrame([
        {"ID": "1", "Name + ID": "Alice (1)", "Roster Position": "PG",
         "Salary": "6200", "Game Info": "AAA@BBB 01/01/2026 07:00PM ET"},
        {"ID": "2", "Name + ID": "Bob (2)", "Roster Position": "SG",
         "Salary": "5800", "Game Info": "AAA@BBB 01/01/2026 07:00PM ET"},
    ])
    with pytest.raises(ValueError, match="Missing projections"):
        merge_player_pool(df_players, projs_df, how="left")


def test_merge_player_pool_salary_is_numeric(projs_df):
    """merge_player_pool casts Salary to a numeric type."""
    df_players = pd.DataFrame([
        {"ID": "1", "Name + ID": "Alice (1)", "Roster Position": "PG",
         "Salary": "6200", "Game Info": "AAA@BBB 01/01/2026 07:00PM ET"},
    ])
    df = merge_player_pool(df_players, projs_df, how="inner")
    assert pd.api.types.is_numeric_dtype(df["Salary"])


def test_engine_style_output_has_start_time_and_game_columns(dk_entries_file, projs_df):
    """Engine-style load (inner + derive_time_game=True) produces StartTime and Game columns."""
    df_players = parse_dk_entries(dk_entries_file)
    df = merge_player_pool(df_players, projs_df, how="inner", derive_time_game=True)

    assert "StartTime" in df.columns
    assert "Game" in df.columns
    assert df.iloc[0]["Game"] == "AAA@BBB"
    assert df.iloc[0]["StartTime"] == datetime(2026, 1, 1, 19, 0)


def test_late_swap_style_output_has_game_column(dk_entries_file):
    """Late-swap-style load (left + derive_game_key) produces a Game column.

    When projections lack Team/Opponent columns (the old 3-column format),
    derive_game_key falls back to Game Info to build the canonical game key.
    Both players here have projections (a missing projection now raises ValueError),
    but neither has Team/Opponent in the projections file, so the fallback path runs.
    """
    from nba_optimizer.utils import derive_game_key

    df_players = parse_dk_entries(dk_entries_file)
    df_projs_minimal = pd.read_csv(io.StringIO(textwrap.dedent("""\
        ID,Name,Projection,Own_Proj
        1,Alice,42.0,25.0
        2,Bob,35.0,18.0
    """)))
    df = merge_player_pool(df_players, df_projs_minimal, how="left")

    n = len(df)
    team_series = df["Team"] if "Team" in df.columns else pd.Series([None] * n, index=df.index)
    opp_series = df["Opponent"] if "Opponent" in df.columns else pd.Series([None] * n, index=df.index)
    gi_series = df["Game Info"] if "Game Info" in df.columns else pd.Series([""] * n, index=df.index)
    df["Game"] = [derive_game_key(t, o, gi) for t, o, gi in zip(team_series, opp_series, gi_series)]

    assert "Game" in df.columns
    # Team/Opponent not in projs → derive_game_key extracts "AAA@BBB" from Game Info
    alice = df[df["ID"] == "1"].iloc[0]
    assert alice["Game"] == "AAA@BBB"
    bob = df[df["ID"] == "2"].iloc[0]
    assert bob["Game"] == "AAA@BBB"


def test_parse_dk_entries_parses_real_dkentries_format():
    """parse_dk_entries correctly parses the real side-by-side DKEntries format.

    The real DK file has entry rows and player-pool columns side-by-side in the
    same rows (different column ranges), not stacked vertically. The sentinel scan
    must find the player-pool header wherever it appears within a line, not just
    at the start of a line.
    """
    real_path = os.path.join(FIXTURES_DIR, "unfilled-DKEntries.csv")
    df = parse_dk_entries(real_path)
    assert len(df) > 100
    assert "Name + ID" in df.columns
    assert "ID" in df.columns
    assert "Roster Position" in df.columns
    assert "Salary" in df.columns
    assert "Game Info" in df.columns
    assert df["ID"].notna().all()
    assert df["ID"].str.match(r"^\d+$").all()


def test_merge_player_pool_normalizes_float_projs_ids(dk_entries_file):
    """merge_player_pool strips '.0' from projs IDs when pandas reads them as float.

    When a projections CSV has any NaN in the ID column, pandas upcasts the
    whole column to float64. astype(str) then gives '12345.0'. Without the
    str.split('.').str[0] normalization, the merge silently produces zero rows.

    Uses parse_dk_entries to get the real object-dtype ID column that
    production code passes to merge_player_pool.
    """
    df_players = parse_dk_entries(dk_entries_file)
    # Simulate float64 IDs (what pandas produces when the ID column has any NaN)
    df_projs_float = pd.read_csv(io.StringIO(textwrap.dedent("""\
        ID,Projection,Own_Proj,Team,Opponent
        ,50.0,10.0,ZZZ,YYY
        1.0,42.0,25.0,AAA,BBB
    """)))
    df = merge_player_pool(df_players, df_projs_float, how="inner")
    assert len(df) == 1, "float ID in projs should still match after normalization"
    assert df.iloc[0]["Projection"] == 42.0
