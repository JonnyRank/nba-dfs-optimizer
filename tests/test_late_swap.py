"""Tests for late-swap game-key resolution, lock handling, and min_games.

These exercise the real DraftKings file format via fixtures in tests/fixtures/
(a swappable post-lock entries export, plus a matching projections file in the
team/opponent format) so the parsing quirks that plain synthetic fixtures miss
are actually covered:

  * (LOCKED) appears in the player-pool "Name + ID", not just the entry rows.
  * A started game's matchup is erased to "Game Info" == "In Progress", so the
    game identity has to come from the projections team/opponent pair.

The synthetic solver test isolates the min_games constraint itself.
"""

import glob
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from nba_optimizer import late_swapper
from nba_optimizer.config import Config, ROSTER_SLOTS
from nba_optimizer.utils import derive_game_key, extract_player_id, is_player_locked

FIXTURES = Path(__file__).parent / "fixtures"
SWAPPABLE_ENTRIES = FIXTURES / "swappable-DKEntries.csv"
PROJS_SAMPLE = FIXTURES / "NBA-Projs-sample.csv"

# IDs drawn from the fixtures (03-25 slate).
LUKA = "42398185"          # locked, "In Progress" (LAL vs IND)
BAM = "42398223"           # locked, matchup intact (MIA vs CLE)
WEMBY = "42398188"         # not locked, future game (SAS vs MEM)


# --- derive_game_key: the in-progress resolution unit ---


def test_derive_game_key_is_order_independent():
    """Both sides of a matchup collapse to the same canonical key."""
    assert derive_game_key("LAL", "IND", "In Progress") == "IND@LAL"
    assert derive_game_key("IND", "LAL", "In Progress") == "IND@LAL"


def test_derive_game_key_falls_back_to_game_info():
    """With no team/opponent, parse the matchup out of Game Info."""
    assert (
        derive_game_key(np.nan, np.nan, "SAS@MEM 03/25/2026 08:00PM ET") == "MEM@SAS"
    )


def test_derive_game_key_last_resort_is_team_alone():
    """An in-progress player missing from projections still yields its team."""
    assert derive_game_key("LAL", np.nan, "In Progress") == "LAL"


# --- real-fixture parsing: locks and game identity ---


def test_load_data_detects_locks_in_pool_and_resolves_in_progress_games():
    df_pool = late_swapper.load_data(str(PROJS_SAMPLE), str(SWAPPABLE_ENTRIES))
    by_id = df_pool.set_index("ID")

    # (LOCKED) is carried in the pool's own "Name + ID", not only the entries.
    assert is_player_locked(by_id.loc[LUKA, "Name + ID"])
    assert is_player_locked(by_id.loc[BAM, "Name + ID"])
    assert not is_player_locked(by_id.loc[WEMBY, "Name + ID"])

    # The previously-collapsing "In Progress" player now resolves to its real,
    # distinct game via the projections team/opponent pair -- the whole point.
    assert by_id.loc[LUKA, "Game Info"] == "In Progress"
    assert by_id.loc[LUKA, "Game"] == "IND@LAL"
    assert by_id.loc[BAM, "Game"] == "CLE@MIA"
    assert by_id.loc[WEMBY, "Game"] == "MEM@SAS"
    # Two in-progress locked players from different real games stay distinct
    # (the old Game-Info split bucketed both as "In").
    assert by_id.loc[LUKA, "Game"] != by_id.loc[BAM, "Game"]


# --- min_games is binding through the late-swap solver ---


def _single_game_dominant_pool() -> pd.DataFrame:
    """Pool whose projection-optimal 8 all sit in one game (GAMEA).

    GAMEA covers every roster slot at the highest projection; GAMEB offers
    slot-compatible but lower-projection substitutes. With no locked players,
    only the min_games floor can force the lineup off the all-GAMEA optimum.
    """
    rows = [
        # Name + ID, ID, Salary, Roster Position, Projection, Game Info, Game
        ("PGa (1)", "1", 6200, "PG", 40, "GAMEA", "GAMEA"),
        ("SGa (2)", "2", 6200, "SG", 40, "GAMEA", "GAMEA"),
        ("SFa (3)", "3", 6200, "SF", 40, "GAMEA", "GAMEA"),
        ("PFa (4)", "4", 6200, "PF", 40, "GAMEA", "GAMEA"),
        ("Ca (5)", "5", 6200, "C", 40, "GAMEA", "GAMEA"),
        ("Ga (6)", "6", 6200, "PG/SG", 40, "GAMEA", "GAMEA"),
        ("Fa (7)", "7", 6200, "SF/PF", 40, "GAMEA", "GAMEA"),
        ("Ua (8)", "8", 6200, "C", 40, "GAMEA", "GAMEA"),
        ("Ub (9)", "9", 6200, "C", 38, "GAMEB", "GAMEB"),
        ("Gb (10)", "10", 6200, "PG/SG", 38, "GAMEB", "GAMEB"),
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "Name + ID", "ID", "Salary", "Roster Position",
            "Projection", "Game Info", "Game",
        ],
    )
    df["StartTime"] = pd.Timestamp("2026-03-25 19:00")
    return df


def test_solve_batch_enforces_min_games():
    """With every slot open and no locks, the all-one-game optimum must be
    rejected in favour of a >= min_games lineup."""
    df_pool = _single_game_dominant_pool()
    cfg = replace(Config(), min_salary=49000, salary_cap=50000, min_games=2)

    # A non-locked 8-man template -> all slots are re-optimized from the pool.
    template = [name for name in df_pool["Name + ID"].tolist()[:8]]

    lineups = late_swapper.solve_late_swap_batch(df_pool, template, cfg, num_to_generate=1)

    assert len(lineups) == 1
    picked = [p for p in lineups[0] if p not in ("EMPTY", "ERROR")]
    assert len(picked) == len(ROSTER_SLOTS)
    games = {df_pool.set_index("Name + ID").loc[p, "Game"] for p in picked}
    assert len(games) >= cfg.min_games


# --- end-to-end on real fixtures: locks preserved, min_games satisfied ---


def test_run_preserves_locks_and_min_games(tmp_path):
    projs_dir = tmp_path / "projections"
    projs_dir.mkdir()
    # run() locates projections via the NBA-Projs-*.csv glob.
    pd.read_csv(PROJS_SAMPLE).to_csv(projs_dir / "NBA-Projs-2026-03-25.csv", index=False)

    # The fixture pool is trimmed, so drop the salary floor to keep the open
    # slots fillable -- otherwise most base states fall back to the unchanged
    # input lineup and the swap path is never exercised.
    cfg = Config(
        entries_path=str(SWAPPABLE_ENTRIES),
        projs_dir=str(projs_dir),
        base_dir=str(tmp_path),
        output_dir=str(tmp_path),
        min_salary=0,
    )
    late_swapper.run(cfg)

    out_path = sorted(glob.glob(str(tmp_path / "late-swap-entries-*.csv")))[-1]
    df_out = pd.read_csv(out_path, dtype=str)
    df_in = pd.read_csv(SWAPPABLE_ENTRIES, dtype=str, skiprows=0)

    slots = list(ROSTER_SLOTS)

    # Game key per player ID, derived from the full projections feed (covers
    # every entry player, unlike the trimmed DKEntries pool section).
    df_projs = pd.read_csv(PROJS_SAMPLE)
    df_projs["ID"] = df_projs["ID"].astype(str)
    game_by_id = {
        row["ID"]: derive_game_key(row["Team"], row["Opponent"])
        for _, row in df_projs.iterrows()
    }

    # Pool IDs that are locked (per the pool's own Name + ID tag).
    df_pool = late_swapper.load_data(str(PROJS_SAMPLE), str(SWAPPABLE_ENTRIES))
    locked_pool_ids = {
        extract_player_id(n)
        for n in df_pool["Name + ID"]
        if is_player_locked(n)
    }

    in_by_entry = {r["Entry ID"]: r for _, r in df_in.iterrows() if pd.notna(r.get("Entry ID"))}
    out_by_entry = {r["Entry ID"]: r for _, r in df_out.iterrows() if pd.notna(r.get("Entry ID"))}

    assert out_by_entry, "expected late-swap output rows"

    for eid, orow in out_by_entry.items():
        irow = in_by_entry[eid]

        in_locked = {
            s: extract_player_id(irow[s])
            for s in slots
            if is_player_locked(str(irow[s]))
        }
        out_ids = {s: extract_player_id(str(orow[s])) for s in slots}

        # REQ1: every locked player stays in its exact slot.
        for s, pid in in_locked.items():
            assert out_ids[s] == pid, f"locked player moved in entry {eid}, slot {s}"

        # REQ2: no locked player appears where it was not already locked.
        in_locked_pairs = {(s, pid) for s, pid in in_locked.items()}
        for s in slots:
            pid = out_ids[s]
            if pid in locked_pool_ids:
                assert (s, pid) in in_locked_pairs, (
                    f"locked player {pid} inserted into entry {eid}, slot {s}"
                )

        # Lineup is complete and free of duplicates.
        ids = [out_ids[s] for s in slots]
        assert all(ids) and len(set(ids)) == len(ids)

        # min_games: the final lineup spans at least cfg.min_games real games.
        final_games = {game_by_id.get(pid) for pid in ids}
        final_games.discard(None)
        assert len(final_games) >= Config().min_games
