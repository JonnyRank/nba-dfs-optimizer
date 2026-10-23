import argparse
import concurrent.futures
import math
import multiprocessing
import os
import secrets
import time
import traceback
from datetime import datetime
from typing import List, Optional, Set, Tuple

import highspy
import numpy as np
import pandas as pd
import pulp

from .config import Config, ROSTER_SLOTS
from .overrides import apply_override_list
from .utils import get_latest_file, merge_player_pool, parse_dk_entries


# --- DATA LOADING ---


def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
    df_players = parse_dk_entries(entries_file)
    df_projs = pd.read_csv(projs_file)
    # derive_time_game=True adds StartTime and Game via the simple pre-lock split.
    # late_swapper.load_data instead calls _attach_game_column (derive_game_key)
    # to recover started games whose Game Info has become "In Progress".
    return merge_player_pool(df_players, df_projs, how="inner", derive_time_game=True)


# --- WORKER FUNCTION (MUST BE TOP-LEVEL) ---
def generate_single_lineup(
    df: pd.DataFrame, randomness: float, min_salary: int, salary_cap: int, roster_size: int, min_games: int
) -> Tuple[List[str], Set[int]]:
    try:
        np.random.seed()
        prob = pulp.LpProblem("NBA_DFS_Worker", pulp.LpMaximize)

        # Convert necessary columns to native Python dicts for instant lookup in loops
        salary_dict = df["Salary"].to_dict()
        pos_dict = df["Roster Position"].to_dict()

        if randomness > 0:
            std_dev = df["Projection"] * randomness
            sim_proj = pd.Series(
                np.random.normal(df["Projection"], std_dev), index=df.index
            )
        else:
            sim_proj = df["Projection"].to_dict()

        player_vars = pulp.LpVariable.dicts("player", df.index, cat=pulp.LpBinary)

        # Objective
        prob += pulp.lpSum([sim_proj[i] * player_vars[i] for i in df.index])

        # Constraints (Using salary_dict instead of df.loc)
        prob += (
            pulp.lpSum([salary_dict[i] * player_vars[i] for i in df.index])
            <= salary_cap
        )
        prob += (
            pulp.lpSum([salary_dict[i] * player_vars[i] for i in df.index])
            >= min_salary
        )
        prob += pulp.lpSum([player_vars[i] for i in df.index]) == roster_size

        # Positional
        slots = ROSTER_SLOTS
        slot_vars = pulp.LpVariable.dicts("slot", (df.index, slots), cat=pulp.LpBinary)

        for i in df.index:
            prob += pulp.lpSum([slot_vars[i][s] for s in slots]) == player_vars[i]
            pos_str = str(pos_dict[i])  # Using pos_dict instead of df.loc

            for s in slots:
                eligible = False
                if s == "UTIL":
                    eligible = True
                elif s == "G":
                    eligible = "PG" in pos_str or "SG" in pos_str
                elif s == "F":
                    eligible = "SF" in pos_str or "PF" in pos_str
                else:
                    eligible = s in pos_str

                if not eligible:
                    prob += slot_vars[i][s] == 0

        for s in slots:
            prob += pulp.lpSum([slot_vars[i][s] for i in df.index]) == 1

        # Min Games
        # The 'Game' column is now pre-processed in load_data.
        # game_vars[g] is an indicator for "game g is represented in the lineup".
        # The <= link forces the indicator to 0 unless at least one of that
        # game's players is selected, so requiring the indicators to sum to
        # >= min_games is a genuine "span at least min_games distinct games"
        # constraint. A one-directional >= link would leave the indicators free
        # to switch on for empty games, making the floor non-binding.
        games = [g for g in df["Game"].unique() if pd.notna(g) and g != ""]
        game_vars = pulp.LpVariable.dicts("game", games, cat=pulp.LpBinary)

        # Use pandas groupby to create a dictionary of {game: [list_of_indices]}
        # This completely avoids doing df[df['Game'] == game] inside the loop
        game_to_players = df.groupby("Game").groups

        for game in games:
            players_in_game = game_to_players[game]
            prob += game_vars[game] <= pulp.lpSum(
                [player_vars[i] for i in players_in_game]
            )

        prob += pulp.lpSum([game_vars[game] for game in games]) >= min_games

        # Solve
        solver = pulp.HiGHS(msg=False)
        prob.solve(solver)

        if pulp.LpStatus[prob.status] != "Optimal":
            return None, None

        lineup_names = []
        selected_indices = set()

        # Create name dictionary to avoid .loc during result extraction
        name_dict = df["Name + ID"].to_dict()
        for i in df.index:
            if pulp.value(player_vars[i]) > 0.5:
                lineup_names.append(name_dict[i])
                selected_indices.add(i)

        return lineup_names, selected_indices

    except Exception:
        traceback.print_exc()
        return None, None


# --- PERSISTENT MODEL (built once per worker process) ---


def _is_slot_eligible(pos_str: str, slot: str) -> bool:
    """DK slot eligibility; same rules as generate_single_lineup."""
    if slot == "UTIL":
        return True
    if slot == "G":
        return "PG" in pos_str or "SG" in pos_str
    if slot == "F":
        return "SF" in pos_str or "PF" in pos_str
    return slot in pos_str


class LineupModel:
    """The generate_single_lineup MIP, built once and re-solved per lineup.

    Only the objective coefficients change between solves, so the PuLP model
    build and PuLP->HiGHS transfer (~30% of per-lineup time) are paid once per
    worker instead of once per lineup. Columns 0..n-1 are the player binaries
    in positional (row) order of df.
    """

    def __init__(
        self, df: pd.DataFrame, min_salary: int, salary_cap: int, roster_size: int, min_games: int
    ):
        n = len(df)
        self.n_players = n
        pos_list = df["Roster Position"].astype(str).tolist()
        salary_arr = df["Salary"].to_numpy(dtype=float)
        game_list = df["Game"].tolist()

        # Slot columns exist only for eligible (player, slot) pairs, which is
        # equivalent to generate_single_lineup's "slot_vars[i][s] == 0" rows.
        slot_pairs = [
            (i, s) for i in range(n) for s in ROSTER_SLOTS if _is_slot_eligible(pos_list[i], s)
        ]
        games = [g for g in pd.unique(df["Game"]) if pd.notna(g) and g != ""]
        n_cols = n + len(slot_pairs) + len(games)

        # threads=1 below is rejected (run() returns kError) if HiGHS's
        # process-global scheduler was already started with more threads,
        # e.g. by an earlier PuLP HiGHS solve in this process. Reset it so
        # the model works regardless of what solved first.
        highspy.Highs.resetGlobalScheduler(True)
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        # One solver thread per worker; the process pool supplies the parallelism.
        # Other HiGHS solves in the same worker (slot_lineup_by_time's
        # pulp.HiGHS) must leave "threads" at its default 0, which reuses this
        # 1-thread scheduler; an explicit threads=N there makes HiGHS error.
        h.setOptionValue("threads", 1)
        h.addVars(n_cols, np.zeros(n_cols), np.ones(n_cols))
        h.changeColsIntegrality(
            n_cols,
            np.arange(n_cols, dtype=np.int32),
            np.array([highspy.HighsVarType.kInteger] * n_cols),
        )

        def add_row(lower, upper, cols, coefs):
            h.addRow(
                float(lower),
                float(upper),
                len(cols),
                np.asarray(cols, dtype=np.int32),
                np.asarray(coefs, dtype=float),
            )

        player_cols = list(range(n))
        add_row(min_salary, salary_cap, player_cols, salary_arr)
        add_row(roster_size, roster_size, player_cols, [1.0] * n)

        slot_cols_by_player = {i: [] for i in range(n)}
        slot_cols_by_slot = {s: [] for s in ROSTER_SLOTS}
        for k, (i, s) in enumerate(slot_pairs):
            slot_cols_by_player[i].append(n + k)
            slot_cols_by_slot[s].append(n + k)
        for i in range(n):
            cols = slot_cols_by_player[i]
            # sum_s slot[i][s] - player[i] == 0
            add_row(0, 0, cols + [i], [1.0] * len(cols) + [-1.0])
        for s in ROSTER_SLOTS:
            cols = slot_cols_by_slot[s]
            add_row(1, 1, cols, [1.0] * len(cols))

        # game[g] - sum(players in g) <= 0 ; sum(game) >= min_games
        inf = highspy.kHighsInf
        game_cols = []
        for g_idx, game in enumerate(games):
            col = n + len(slot_pairs) + g_idx
            game_cols.append(col)
            members = [i for i in range(n) if game_list[i] == game]
            add_row(-inf, 0, [col] + members, [1.0] + [-1.0] * len(members))
        add_row(min_games, inf, game_cols, [1.0] * len(game_cols))

        h.changeObjectiveSense(highspy.ObjSense.kMaximize)
        self._highs = h
        self._player_cols = np.arange(n, dtype=np.int32)

    def solve(self, projections) -> Optional[List[int]]:
        """Maximize sum(projections * player). Returns sorted row positions, or None if not optimal."""
        h = self._highs
        h.changeColsCost(self.n_players, self._player_cols, np.asarray(projections, dtype=float))
        run_status = h.run()
        if run_status == highspy.HighsStatus.kError:
            raise RuntimeError(f"HiGHS run failed: {h.getModelStatus()}")
        if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
            return None
        col_values = np.asarray(h.getSolution().col_value[: self.n_players])
        return np.flatnonzero(col_values > 0.5).tolist()


# Columns a worker needs: model build (Salary, Roster Position, Game,
# Projection) and slot_lineup_by_time (Name + ID, Roster Position, StartTime).
WORKER_COLUMNS = ["Name + ID", "Roster Position", "Salary", "Projection", "Game", "StartTime"]

# Per-process state, populated once by _init_worker. Lives in each spawned
# worker; the parent process never reads it.
_WORKER_STATE = {}


def new_seed() -> int:
    """A fresh random 63-bit base seed."""
    return secrets.randbits(63)


def lineup_rng(base_seed: int, j: int) -> np.random.Generator:
    """RNG for lineup j: depends only on (base_seed, j), never on which worker draws it."""
    return np.random.default_rng(np.random.SeedSequence(base_seed, spawn_key=(j,)))


def _init_worker(
    df_pool: pd.DataFrame,
    randomness: float,
    min_salary: int,
    salary_cap: int,
    roster_size: int,
    min_games: int,
    base_seed: Optional[int] = None,
) -> None:
    """ProcessPoolExecutor initializer: receive the pool once, build the model once."""
    _WORKER_STATE["df_pool"] = df_pool
    _WORKER_STATE["names"] = df_pool["Name + ID"].tolist()
    _WORKER_STATE["projection"] = df_pool["Projection"].to_numpy(dtype=float)
    _WORKER_STATE["randomness"] = randomness
    _WORKER_STATE["base_seed"] = new_seed() if base_seed is None else base_seed
    _WORKER_STATE["model"] = LineupModel(df_pool, min_salary, salary_cap, roster_size, min_games)


def _generate_batch(j0: int, j1: int) -> List[Tuple[int, Tuple[int, ...], List[str]]]:
    """Solve and slot lineups j0..j1-1. Returns (j, row positions, slotted names) per lineup."""
    state = _WORKER_STATE
    results = []
    for j in range(j0, j1):
        try:
            projection = state["projection"]
            if state["randomness"] > 0:
                rng = lineup_rng(state["base_seed"], j)
                sim_proj = rng.normal(projection, projection * state["randomness"])
            else:
                sim_proj = projection
            positions = state["model"].solve(sim_proj)
            if positions is None:
                continue
            names = [state["names"][p] for p in positions]
            slotted = slot_lineup_by_time(names, state["df_pool"])
            results.append((j, tuple(positions), slotted))
        except RuntimeError:
            # LineupModel.solve raises RuntimeError when HiGHS itself errors
            # (misconfigured solver). Every later lineup would fail the same
            # way, so fail the whole batch once instead of per lineup.
            raise
        except Exception:
            traceback.print_exc()
    return results


def slot_lineup_by_time(lineup_names: List[str], df: pd.DataFrame) -> List[str]:
    players = df[df["Name + ID"].isin(lineup_names)].copy()
    if len(players) != 8:
        return ["ERROR"] * 8

    slot_weights = {
        "PG": 1,
        "SG": 1,
        "SF": 1,
        "PF": 1,
        "C": 1,
        "G": 10,
        "F": 10,
        "UTIL": 100,
    }
    slots = ROSTER_SLOTS

    start_times = pd.to_datetime(players["StartTime"], errors="coerce")
    min_time = start_times.min()
    players["TimeScore"] = (start_times - min_time).dt.total_seconds() / 60.0
    players["TimeScore"] = players["TimeScore"].fillna(0)

    # --- NEW: Convert to dictionaries for O(1) lookup ---
    time_score_dict = players["TimeScore"].to_dict()
    pos_dict = players["Roster Position"].to_dict()
    name_dict = players["Name + ID"].to_dict()

    prob = pulp.LpProblem("Slotting", pulp.LpMaximize)
    slot_vars = pulp.LpVariable.dicts("slot", (players.index, slots), cat=pulp.LpBinary)

    # Use time_score_dict instead of players.loc
    prob += pulp.lpSum(
        [
            slot_vars[i][s] * time_score_dict[i] * slot_weights[s]
            for i in players.index
            for s in slots
        ]
    )

    for i in players.index:
        prob += pulp.lpSum([slot_vars[i][s] for s in slots]) == 1

        # Use pos_dict instead of players.loc
        pos_str = str(pos_dict[i])

        for s in slots:
            eligible = False
            if s == "UTIL":
                eligible = True
            elif s == "G":
                eligible = "PG" in pos_str or "SG" in pos_str
            elif s == "F":
                eligible = "SF" in pos_str or "PF" in pos_str
            else:
                eligible = s in pos_str

            if not eligible:
                prob += slot_vars[i][s] == 0

    for s in slots:
        prob += pulp.lpSum([slot_vars[i][s] for i in players.index]) == 1

    prob.solve(pulp.HiGHS(msg=False))

    final_lineup = {}
    for i in players.index:
        for s in slots:
            if pulp.value(slot_vars[i][s]) > 0.5:
                # Use name_dict instead of players.loc
                final_lineup[s] = name_dict[i]

    return [final_lineup.get(s, "EMPTY") for s in slots]


def run(
    cfg: Config,
    num_lineups: int = 2500,
    randomness: float = 0.25,
    projs_file: Optional[str] = None,
    run_time: Optional[datetime] = None,
    slate_date: Optional[str] = None,
    overrides: Optional[List[dict]] = None,
) -> str:
    """Run the lineup generation engine.

    Uses ``cfg.seed`` as the base seed; when it is ``None`` a fresh seed is
    drawn, printed and written back to ``cfg.seed`` so later stages can
    record it. The same seed and inputs give the same pool regardless of
    worker count or completion order.

    Args:
        projs_file: Explicit projections CSV; defaults to the latest in cfg.projs_dir.
        run_time: The run's instant, shared by every stage's filenames.
        slate_date: ``YYYY-MM-DD`` used in the pool filename (defaults to run_time's date).
        overrides: Resolved projection/ownership overrides (O-13), applied
            right after the player-pool merge.

    Returns:
        Path to the written lineup-pool CSV, or an empty string if the run
        failed before producing output.
    """
    print("Starting NBA DFS Optimizer (Parallel Mode)...")
    print(
        f"Settings: {num_lineups} lineups, {randomness * 100:.0f}% randomness, {cfg.min_projection} min proj"
    )

    # Check if randomness is 0
    if randomness <= 0:
        print(
            "WARNING: Randomness is 0. Parallel workers will likely generate identical lineups."
        )
        print(
            "Using sequential Iterative Exclusion logic instead? No, this script is now Parallel-only."
        )
        print("Please enable randomness (>0) for parallel mode efficiency.")

    try:
        if cfg.seed is None:
            cfg.seed = new_seed()
        print(f"Seed: {cfg.seed}")

        if not projs_file:
            projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv")
        print(f"Using projections: {os.path.basename(projs_file)}")

        df = load_data(projs_file, cfg.entries_path)
        df, _ = apply_override_list(df, overrides or [])
        df = df[df["Projection"] >= cfg.min_projection]
        print(f"Loaded {len(df)} players with proj >= {cfg.min_projection}")

        target_lineups = num_lineups

        # Windows caps ProcessPoolExecutor at 61 workers.
        num_workers = min(61, multiprocessing.cpu_count())
        print(
            f"Spinning up pool with {num_workers} cores to generate ~{target_lineups} candidates..."
        )

        # Positional index so LineupModel's column order == row label.
        df_pool = df[WORKER_COLUMNS].reset_index(drop=True)

        # Spawned workers inherit this env at "import numpy"; without it each
        # worker's OpenBLAS reserves per-thread buffers (~700 MB commit per
        # worker vs ~90 MB). Workers do no BLAS work. Only affects "spawn"
        # (Windows) and "forkserver" starts; under "fork" numpy is already
        # imported. It stays set for the rest of this run's process, which is
        # harmless: later stages start no child processes, and this process's
        # own BLAS was configured at its numpy import. The GUI launches each
        # run as a fresh process, so it does not carry over between runs.
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

        # Small batches amortize task overhead while keeping ~4 batches per
        # worker for load balancing and progress reporting.
        batch_size = max(1, min(25, math.ceil(target_lineups / (num_workers * 4))))
        # Lineup index ranges [j0, j1); each lineup's noise depends only on its j.
        batch_ranges = [
            (j0, min(j0 + batch_size, target_lineups)) for j0 in range(0, target_lineups, batch_size)
        ]

        candidates = []

        # Start the timer
        start_time = time.perf_counter()

        with concurrent.futures.ProcessPoolExecutor(
            max_workers=num_workers,
            initializer=_init_worker,
            initargs=(
                df_pool, randomness, cfg.min_salary, cfg.salary_cap, cfg.roster_size, cfg.min_games, cfg.seed,
            ),
        ) as executor:
            future_size_map = {executor.submit(_generate_batch, j0, j1): j1 - j0 for j0, j1 in batch_ranges}
            completed = 0
            last_bucket = 0
            for future in concurrent.futures.as_completed(future_size_map):
                try:
                    candidates.extend(future.result())
                except Exception as exc:
                    print(f"Worker generated exception: {exc}")
                completed += future_size_map[future]
                # Report in 20% steps; bucket 5 (100%) is reached exactly once.
                bucket = completed * 5 // target_lineups
                if bucket > last_bucket:
                    print(f"Lineups generated: {bucket * 20}%")
                    last_bucket = bucket

        # Stop the timer and calculate the duration
        end_time = time.perf_counter()
        execution_time = end_time - start_time

        print(
            f"Total candidates generated: {len(candidates)}; Total generation time: {execution_time:.2f} seconds"
        )

        if not candidates:
            print("Error: no lineups were generated; aborting.")
            return ""

        # Completion order varies run to run; write in lineup-index order so
        # the same seed reproduces the same pool.
        candidates.sort(key=lambda c: c[0])

        # Every solved lineup goes into the pool (lineups arrive already
        # slotted); -u/--min_unique is applied at assemble (O-14).
        final_lineups = [slotted for _, _, slotted in candidates]
        duplicates = len(candidates) - len({frozenset(positions) for _, positions, _ in candidates})
        print(f"Exact duplicates kept in pool: {duplicates} (-u applies at assemble)")

        # Save
        if not os.path.exists(cfg.lineup_pool_dir):
            os.makedirs(cfg.lineup_pool_dir)

        run_time = run_time or datetime.now()
        timestamp = f"{slate_date or run_time.strftime('%Y-%m-%d')}_{run_time.strftime('%H%M%S')}"
        output_file = os.path.join(
            cfg.lineup_pool_dir, f"lineup-pool-{timestamp}.csv"
        )
        out_df = pd.DataFrame(
            final_lineups, columns=ROSTER_SLOTS
        )
        out_df.to_csv(output_file, index=False)
        print(f"Saved {len(final_lineups)} lineups to {output_file}")
        return output_file

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return ""


def main():
    from dataclasses import replace
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Optimization Engine (Parallel)")
    parser.add_argument("-n", "--num_lineups", type=int, default=2500, help="Number of lineups to generate (Default: 2500)")
    parser.add_argument("-r", "--randomness", type=float, default=0.25, help="Randomness factor 0.0-1.0 (Default: 0.25)")
    parser.add_argument("-ms", "--min_salary", type=int, default=49500, help="Min salary for a lineup (Default: 49500)")
    parser.add_argument("-mp", "--min_projection", type=float, default=10.0, help="Min projection for a player to be considered (Default: 10.0)")
    parser.add_argument("--seed", type=int, default=None, help="Base seed (Default: draw a fresh one)")
    args = parser.parse_args()

    cfg = load_config_from_env()
    cfg = replace(cfg, min_salary=args.min_salary, min_projection=args.min_projection, seed=args.seed)

    run(
        cfg,
        num_lineups=args.num_lineups,
        randomness=args.randomness,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Good practice for Windows
    main()
