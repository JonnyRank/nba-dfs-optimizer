"""Deterministic tests for the core LP constraints in
nba_optimizer.engine.generate_single_lineup.

These exercise the worker function directly against a tiny synthetic player
pool (randomness=0.0) so the solve is reproducible. The pool is constructed
so that exactly one combination of 8 players satisfies the salary, roster
size, positional, and min-games constraints simultaneously -- the two cheap
bench players exist only to give the solver alternatives that it must reject
because including either of them breaks the salary-floor or roster-size
constraint.
"""

import pandas as pd

from nba_optimizer.config import ROSTER_SLOTS, Config
from nba_optimizer.engine import generate_single_lineup


def _build_pool() -> pd.DataFrame:
    """Build a small synthetic player pool spanning two games.

    The first 8 rows are priced at 6200 (total 49600, inside the default
    49500-50000 salary band) and cover all 8 roster slots exactly once.
    The last 2 rows are cheap bench players that the solver must leave on
    the bench: swapping either of them in would require dropping one of
    the 8 slot-covering players, which breaks positional eligibility.
    """
    data = [
        # Name + ID,   Salary, Roster Position, Projection, Game
        ("PG1 (1)", 6200, "PG", 40, "GAMEA"),
        ("SG1 (2)", 6200, "SG", 40, "GAMEA"),
        ("SF1 (3)", 6200, "SF", 40, "GAMEA"),
        ("PF1 (4)", 6200, "PF", 40, "GAMEA"),
        ("C1 (5)", 6200, "C", 40, "GAMEA"),
        ("G1 (6)", 6200, "PG/SG", 38, "GAMEB"),
        ("F1 (7)", 6200, "SF/PF", 38, "GAMEB"),
        ("U1 (8)", 6200, "C", 38, "GAMEB"),
        ("PG2 (9)", 3000, "PG", 10, "GAMEB"),
        ("SG2 (10)", 3000, "SG", 10, "GAMEB"),
    ]
    return pd.DataFrame(
        data, columns=["Name + ID", "Salary", "Roster Position", "Projection", "Game"]
    )


def _is_slot_eligible(pos_str: str, slot: str) -> bool:
    """Mirror the slot-eligibility rules from generate_single_lineup."""
    if slot == "UTIL":
        return True
    if slot == "G":
        return "PG" in pos_str or "SG" in pos_str
    if slot == "F":
        return "SF" in pos_str or "PF" in pos_str
    return slot in pos_str


def test_lineup_size_and_salary_bounds():
    """A solved lineup has exactly roster_size players within the salary band."""
    df = _build_pool()
    cfg = Config()

    lineup_names, selected_indices = generate_single_lineup(
        df,
        randomness=0.0,
        min_salary=cfg.min_salary,
        salary_cap=cfg.salary_cap,
        roster_size=cfg.roster_size,
        min_games=cfg.min_games,
    )

    assert lineup_names is not None, "expected a feasible lineup for this pool"
    assert len(lineup_names) == cfg.roster_size
    assert len(selected_indices) == cfg.roster_size

    total_salary = df.loc[list(selected_indices), "Salary"].sum()
    assert cfg.min_salary <= total_salary <= cfg.salary_cap


def test_lineup_respects_position_eligibility_and_min_games():
    """Every selected player can fill at least one DK slot, and the
    lineup spans at least min_games distinct games."""
    df = _build_pool()
    cfg = Config()

    lineup_names, selected_indices = generate_single_lineup(
        df,
        randomness=0.0,
        min_salary=cfg.min_salary,
        salary_cap=cfg.salary_cap,
        roster_size=cfg.roster_size,
        min_games=cfg.min_games,
    )

    assert lineup_names is not None, "expected a feasible lineup for this pool"

    selected = df.loc[list(selected_indices)]

    # Every selected player is slot-eligible for at least one of the 8 slots.
    for pos_str in selected["Roster Position"]:
        assert any(_is_slot_eligible(pos_str, slot) for slot in ROSTER_SLOTS)

    # The lineup spans at least min_games distinct games.
    assert selected["Game"].nunique() >= cfg.min_games
