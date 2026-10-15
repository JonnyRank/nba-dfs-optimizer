"""Characterization tests for lineup scoring in nba_optimizer.ranker.rank_lineups.

These lock down the current ranking semantics on a tiny hand-built player
pool, so a future change to rank_lineups cannot silently change which lineups
come out on top. Every expected number can be checked by hand from PLAYERS.
"""

import math

import pandas as pd
import pytest

from nba_optimizer.config import ROSTER_SLOTS
from nba_optimizer.ranker import rank_lineups

# (Name + ID, Projection, Own_Proj)
PLAYERS = [
    ("A1 (1)", 50, 30.0),
    ("A2 (2)", 45, 25.0),
    ("A3 (3)", 40, 20.0),
    ("A4 (4)", 35, 15.0),
    ("A5 (5)", 30, 10.0),
    ("A6 (6)", 25, 8.0),
    ("A7 (7)", 20, 5.0),
    ("A8 (8)", 15, 2.0),
    ("B1 (11)", 30, 1.0),
    ("B2 (12)", 30, 1.0),
    ("Z0 (20)", 10, 0.0),
]

# Projection 260, ownership 115.
LINEUP_1 = ["A1 (1)", "A2 (2)", "A3 (3)", "A4 (4)", "A5 (5)", "A6 (6)", "A7 (7)", "A8 (8)"]
# A5/A6 swapped for two 1%-owned B players: projection 265, ownership 99.
LINEUP_2 = ["A1 (1)", "A2 (2)", "A3 (3)", "A4 (4)", "B1 (11)", "B2 (12)", "A7 (7)", "A8 (8)"]
# Contains a 0%-owned player (Z0) and a player missing from the pool (Ghost):
# projection 230, ownership 105.
LINEUP_3 = ["A1 (1)", "A2 (2)", "A3 (3)", "A4 (4)", "A5 (5)", "Z0 (20)", "A7 (7)", "Ghost (99)"]

# ranker.run() defaults (proj_weight=0.85, own_weight=0.0, geo_weight=0.15).
DEFAULT_WEIGHTS = {"proj": 0.85, "own": 0.0, "geo": 0.15}


def _players() -> pd.DataFrame:
    return pd.DataFrame(PLAYERS, columns=["Name + ID", "Projection", "Own_Proj"])


def _lineups(*lineups) -> pd.DataFrame:
    return pd.DataFrame(list(lineups), columns=list(ROSTER_SLOTS))


def _geomean(values) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


def test_totals_sum_projection_and_ownership_across_all_slots():
    """Total_Projection and Total_Ownership are plain sums over all 8 slots."""
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_2), _players(), DEFAULT_WEIGHTS)
    df_by_id = df_ranked.set_index("Lineup_ID")

    assert df_by_id.loc[1, "Total_Projection"] == 260
    assert df_by_id.loc[1, "Total_Ownership"] == pytest.approx(115.0)
    assert df_by_id.loc[2, "Total_Projection"] == 265
    assert df_by_id.loc[2, "Total_Ownership"] == pytest.approx(99.0)


def test_missing_player_contributes_zero_projection_and_ownership():
    """A lineup player absent from the player pool counts as 0 projection and
    0 ownership instead of raising (e.g. a player dropped from projections)."""
    df_ranked = rank_lineups(_lineups(LINEUP_3), _players(), DEFAULT_WEIGHTS)
    row = df_ranked.iloc[0]

    assert row["Total_Projection"] == 230
    assert row["Total_Ownership"] == pytest.approx(105.0)


def test_geomean_ownership_floors_zero_and_missing_at_0_1():
    """Geomean_Ownership floors each player's ownership at 0.1 before the log,
    so a 0%-owned or missing player pulls the geomean down without making it
    zero or undefined."""
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_3), _players(), DEFAULT_WEIGHTS)
    df_by_id = df_ranked.set_index("Lineup_ID")

    assert df_by_id.loc[1, "Geomean_Ownership"] == pytest.approx(
        _geomean([30, 25, 20, 15, 10, 8, 5, 2])
    )
    # LINEUP_3 is the second input row here, so its Lineup_ID is 2.
    # Z0 (0%) and Ghost (missing) both become 0.1.
    assert df_by_id.loc[2, "Geomean_Ownership"] == pytest.approx(
        _geomean([30, 25, 20, 15, 10, 0.1, 5, 0.1])
    )


def test_default_weights_rank_order():
    """With the run() default weights, the score is 0.85*Proj_Rank +
    0.15*Geo_Rank (lower is better) and Final_Rank follows the score.

    Proj_Rank: L2 (265) 1, L1 (260) 2, L3 (230) 3.
    Geo_Rank (lowest geomean is best): L3 1, L2 2, L1 3.
    Scores: L2 1.15, L1 2.15, L3 2.70.
    """
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_2, LINEUP_3), _players(), DEFAULT_WEIGHTS)
    df_by_id = df_ranked.set_index("Lineup_ID")

    assert df_by_id["Proj_Rank"].to_dict() == {1: 2.0, 2: 1.0, 3: 3.0}
    assert df_by_id["Own_Rank"].to_dict() == {1: 3.0, 2: 1.0, 3: 2.0}
    assert df_by_id["Geo_Rank"].to_dict() == {1: 3.0, 2: 2.0, 3: 1.0}
    assert df_by_id.loc[2, "Lineup_Score"] == pytest.approx(1.15)
    assert df_by_id.loc[1, "Lineup_Score"] == pytest.approx(2.15)
    assert df_by_id.loc[3, "Lineup_Score"] == pytest.approx(2.70)
    assert df_ranked["Lineup_ID"].tolist() == [2, 1, 3]
    assert df_ranked["Final_Rank"].tolist() == [1, 2, 3]


def test_ownership_only_weights_rank_by_lowest_total_ownership():
    """Weights are honored: with only own_weight set, the lineup with the
    lowest Total_Ownership ranks first (L2 99, L3 105, L1 115)."""
    weights = {"proj": 0.0, "own": 1.0, "geo": 0.0}
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_2, LINEUP_3), _players(), weights)

    assert df_ranked["Lineup_ID"].tolist() == [2, 3, 1]
    assert df_ranked["Final_Rank"].tolist() == [1, 2, 3]


def test_missing_weight_keys_default_to_one():
    """A weight key left out of the weights dict counts at full weight (1.0),
    not 0: with only {"proj": 1.0}, own and geo ranks still add to the score.

    Scores (Proj_Rank + Own_Rank + Geo_Rank): L1 2+3+3=8, L2 1+1+2=4, L3 3+2+1=6.
    """
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_2, LINEUP_3), _players(), {"proj": 1.0})

    assert df_ranked.set_index("Lineup_ID")["Lineup_Score"].to_dict() == {1: 8.0, 2: 4.0, 3: 6.0}


def test_tied_metrics_share_average_rank():
    """Lineups with identical metrics get the average of the tied ranks
    (pandas rank method='average'), e.g. two-way tie for first = 1.5.

    Row order among tied Lineup_Score values is deliberately not asserted:
    rank_lineups sorts with the default (unstable) quicksort, so it is not
    guaranteed."""
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_1), _players(), DEFAULT_WEIGHTS)

    assert df_ranked["Proj_Rank"].tolist() == [1.5, 1.5]
    assert df_ranked["Own_Rank"].tolist() == [1.5, 1.5]
    assert df_ranked["Geo_Rank"].tolist() == [1.5, 1.5]


def test_output_keeps_slot_columns_and_lineup_ids():
    """Each ranked row carries its original 8 slot assignments, and Lineup_ID
    is the 1-based position of the lineup in the input pool."""
    lineups = [LINEUP_1, LINEUP_2, LINEUP_3]
    df_ranked = rank_lineups(_lineups(*lineups), _players(), DEFAULT_WEIGHTS)

    assert sorted(df_ranked["Lineup_ID"].tolist()) == [1, 2, 3]
    for _, row in df_ranked.iterrows():
        assert [row[s] for s in ROSTER_SLOTS] == lineups[row["Lineup_ID"] - 1]
