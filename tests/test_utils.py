"""Deterministic tests for shared parsing helpers in nba_optimizer.utils.

These cover the small, pure-function behaviors that the rest of the
pipeline (engine, ranker, exporter, late_swapper) all rely on for parsing
DraftKings CSV exports.
"""

import os
from datetime import datetime

import pandas as pd

from nba_optimizer.utils import extract_player_id, parse_game_time, read_ragged_csv

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

    df, valid_cols = read_ragged_csv(csv_path, max_columns=6)

    # The original 4 header columns are reported back unchanged.
    assert valid_cols == ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]

    # The padded frame has 2 extra dummy columns appended.
    assert df.columns.tolist() == valid_cols + ["extra_0", "extra_1"]

    # The first row had no extra values, so the padding columns are NaN.
    assert pd.isna(df.loc[0, "extra_0"])
    assert pd.isna(df.loc[0, "extra_1"])

    # The second (ragged) row's extra values land in the padding columns.
    assert df.loc[1, "extra_0"] == "extra_value_a"
    assert df.loc[1, "extra_1"] == "extra_value_b"

    # Valid columns retain their original data for both rows. Entry ID is
    # read as a string (object dtype) to avoid losing precision on large IDs.
    assert df.loc[0, "Entry ID"] == "111"
    assert df.loc[1, "Entry ID"] == "333"
