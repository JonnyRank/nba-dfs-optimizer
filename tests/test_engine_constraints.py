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


def _build_single_game_dominant_pool() -> pd.DataFrame:
    """Build a pool whose projection-optimal lineup fits inside one game.

    The 8 GAMEA players cover all 8 roster slots and are the highest-projection
    options (40 each), so the unconstrained optimum is an all-GAMEA lineup
    (total projection 320, spanning a single game). The GAMEB substitutes are
    slot-compatible but lower projection (38), so the *only* reason to include
    one is the min_games floor. This makes the test fail if that floor is not
    actually enforced -- the solver would otherwise return the one-game lineup.
    """
    data = [
        # Name + ID,   Salary, Roster Position, Projection, Game
        ("PGa (1)", 6200, "PG", 40, "GAMEA"),
        ("SGa (2)", 6200, "SG", 40, "GAMEA"),
        ("SFa (3)", 6200, "SF", 40, "GAMEA"),
        ("PFa (4)", 6200, "PF", 40, "GAMEA"),
        ("Ca (5)", 6200, "C", 40, "GAMEA"),
        ("Ga (6)", 6200, "PG/SG", 40, "GAMEA"),  # G slot
        ("Fa (7)", 6200, "SF/PF", 40, "GAMEA"),  # F slot
        ("Ua (8)", 6200, "C", 40, "GAMEA"),  # UTIL slot
        # GAMEB substitutes: same salary, slightly lower projection.
        ("Ub (9)", 6200, "C", 38, "GAMEB"),
        ("Gb (10)", 6200, "PG/SG", 38, "GAMEB"),
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
    df_pool = _build_pool()
    cfg = Config()

    lineup_names, selected_indices = generate_single_lineup(
        df_pool,
        randomness=0.0,
        min_salary=cfg.min_salary,
        salary_cap=cfg.salary_cap,
        roster_size=cfg.roster_size,
        min_games=cfg.min_games,
    )

    assert lineup_names is not None, "expected a feasible lineup for this pool"
    assert len(lineup_names) == cfg.roster_size
    assert len(selected_indices) == cfg.roster_size

    total_salary = df_pool.loc[list(selected_indices), "Salary"].sum()
    assert cfg.min_salary <= total_salary <= cfg.salary_cap


def test_lineup_respects_position_eligibility_and_min_games():
    """Every selected player can fill at least one DK slot, and the
    lineup spans at least min_games distinct games."""
    df_pool = _build_pool()
    cfg = Config()

    lineup_names, selected_indices = generate_single_lineup(
        df_pool,
        randomness=0.0,
        min_salary=cfg.min_salary,
        salary_cap=cfg.salary_cap,
        roster_size=cfg.roster_size,
        min_games=cfg.min_games,
    )

    assert lineup_names is not None, "expected a feasible lineup for this pool"

    df_selected = df_pool.loc[list(selected_indices)]

    # Every selected player is slot-eligible for at least one of the 8 slots.
    for pos_str in df_selected["Roster Position"]:
        assert any(_is_slot_eligible(pos_str, slot) for slot in ROSTER_SLOTS)

    # The lineup spans at least min_games distinct games.
    assert df_selected["Game"].nunique() >= cfg.min_games


def test_min_games_ignores_players_with_unknown_game():
    """A player with a missing (NaN) game key must not break the solve or
    count toward min_games. Without filtering NaN out of the games list, the
    groupby lookup raises KeyError and generate_single_lineup returns None."""
    df_pool = _build_single_game_dominant_pool()
    ghost = pd.DataFrame(
        [("Ghost (99)", 3000, "PG/SG", 5, float("nan"))],
        columns=["Name + ID", "Salary", "Roster Position", "Projection", "Game"],
    )
    df_pool = pd.concat([df_pool, ghost], ignore_index=True)
    cfg = Config()

    lineup_names, selected_indices = generate_single_lineup(
        df_pool,
        randomness=0.0,
        min_salary=cfg.min_salary,
        salary_cap=cfg.salary_cap,
        roster_size=cfg.roster_size,
        min_games=cfg.min_games,
    )

    assert lineup_names is not None, "a NaN game key must not break the solve"
    df_selected = df_pool.loc[list(selected_indices)]
    assert df_selected["Game"].dropna().nunique() >= cfg.min_games


def test_min_games_is_enforced_against_single_game_optimum():
    """min_games forces a second game even when the projection-optimal
    lineup would otherwise come entirely from one game.

    On the single-game-dominant pool the unconstrained optimum is 8 GAMEA
    players (projection 320, one game). With min_games=2 the solver must give
    up projection to bring in a GAMEB substitute. This is the regression guard
    for the game-indicator linking: if the floor is non-binding the solver
    returns the one-game lineup and this test fails.
    """
    df_pool = _build_single_game_dominant_pool()
    cfg = Config()
    assert cfg.min_games == 2, "test assumes the default two-game floor"

    lineup_names, selected_indices = generate_single_lineup(
        df_pool,
        randomness=0.0,
        min_salary=cfg.min_salary,
        salary_cap=cfg.salary_cap,
        roster_size=cfg.roster_size,
        min_games=cfg.min_games,
    )

    assert lineup_names is not None, "expected a feasible lineup for this pool"
    assert len(selected_indices) == cfg.roster_size

    df_selected = df_pool.loc[list(selected_indices)]
    assert df_selected["Game"].nunique() >= cfg.min_games
