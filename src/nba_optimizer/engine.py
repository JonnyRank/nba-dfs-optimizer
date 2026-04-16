import argparse
import concurrent.futures
import glob
import itertools
import multiprocessing
import os
import re
import time
import traceback
from datetime import datetime
from typing import List, Set, Tuple

import numpy as np
import pandas as pd
import pulp

import src.nba_optimizer.config as config


# --- DATA LOADING ---
def get_latest_projections() -> str:
    files = glob.glob(os.path.join(config.PROJS_DIR, "NBA-Projs-*.csv"))
    if not files:
        raise FileNotFoundError(f"No projection files found in {config.PROJS_DIR}")
    return max(files, key=os.path.basename)


def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
    df_raw = pd.read_csv(entries_file, skiprows=7)

    pos_col_idx = -1
    for i, col in enumerate(df_raw.columns):
        if "Position" in str(col):
            pos_col_idx = i
            break

    if pos_col_idx == -1:
        raise ValueError("Could not find 'Position' column in DKEntries.csv")

    df_players = df_raw.iloc[:, pos_col_idx:].dropna(subset=["ID"])
    df_players["ID"] = df_players["ID"].astype(str).str.split(".").str[0]

    df_projs = pd.read_csv(projs_file)
    df_projs["ID"] = df_projs["ID"].astype(str)

    df = pd.merge(df_players, df_projs, on="ID", how="inner")

    def parse_time(game_info):
        match = re.search(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}[APM]+)", game_info)
        if match:
            return datetime.strptime(match.group(1), "%m/%d/%Y %I:%M%p")
        return datetime.max

    df["StartTime"] = df["Game Info"].apply(parse_time)
    df["Salary"] = pd.to_numeric(df["Salary"])

    df["Game"] = df["Game Info"].str.split(" ").str[0]
    return df


# --- WORKER FUNCTION (MUST BE TOP-LEVEL) ---
def generate_single_lineup(
    df: pd.DataFrame, randomness: float, min_salary: int
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
            <= config.SALARY_CAP
        )
        prob += (
            pulp.lpSum([salary_dict[i] * player_vars[i] for i in df.index])
            >= min_salary
        )
        prob += pulp.lpSum([player_vars[i] for i in df.index]) == config.ROSTER_SIZE

        # Positional
        slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
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
        # The 'Game' column is now pre-processed in load_data
        games = df["Game"].unique()
        game_vars = pulp.LpVariable.dicts("game", games, cat=pulp.LpBinary)

        # Use pandas groupby to create a dictionary of {game: [list_of_indices]}
        # This completely avoids doing df[df['Game'] == game] inside the loop
        game_to_players = df.groupby("Game").groups

        for game in games:
            players_in_game = game_to_players[game]
            for i in players_in_game:
                prob += game_vars[game] >= player_vars[i] / 10.0

        prob += pulp.lpSum([game_vars[game] for game in games]) >= config.MIN_GAMES

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
    slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]

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
    num_lineups: int = 2500,
    randomness: float = 0.25,
    min_unique: int = 1,
    min_salary: int = 49500,
    min_projection: float = 10.0,
):
    print("Starting NBA DFS Optimizer (Parallel Mode)...")
    print(
        f"Settings: {num_lineups} lineups, {randomness * 100:.0f}% randomness, {min_unique} min unique, {min_projection} min proj"
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
        projs_file = get_latest_projections()
        print(f"Using projections: {os.path.basename(projs_file)}")

        df = load_data(projs_file, config.ENTRIES_PATH)
        df = df[df["Projection"] >= min_projection]
        print(f"Loaded {len(df)} players with proj >= {min_projection}")

        # DEPRECATED - randomness of 0.25 renders duplicates mathematically improbable
        # Strategy: Generate more than needed to account for duplicates/overlap
        # target_lineups = num_lineups
        # oversample_factor = 1 if min_unique > 1 else 1.25
        # target_lineups = int(target_lineups * oversample_factor)

        target_lineups = num_lineups

        print(
            f"Spinning up pool with {multiprocessing.cpu_count()} cores to generate ~{target_lineups} candidates..."
        )

        candidates = []

        # Start the timer
        start_time = time.perf_counter()

        with concurrent.futures.ProcessPoolExecutor() as executor:
            # We must pass df, randomness, and min_salary to each worker
            # Since df is static, it gets pickled once (or shared via COW on Linux, but picked on Windows)
            futures = [
                executor.submit(
                    generate_single_lineup, df, randomness, min_salary
                )
                for _ in range(target_lineups)
            ]

            # Calculate the iteration interval for 20% chunks once, outside the loop
            interval = max(1, target_lineups // 5)

            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                try:
                    names, indices = future.result()
                    if names and indices:
                        candidates.append((names, indices))

                    # Only do the math and print when hitting the interval or the final task
                    if (i + 1) % interval == 0 or (i + 1) == target_lineups:
                        percentage = int(((i + 1) / target_lineups) * 100)
                        print(f"Lineups generated: {percentage}%")

                except Exception as exc:
                    print(f"Worker generated exception: {exc}")

        # Stop the timer and calculate the duration
        end_time = time.perf_counter()
        execution_time = end_time - start_time

        print(
            f"Total candidates generated: {len(candidates)}; Total solver time: {execution_time:.2f} seconds"
        )
        # print(f"Total solver time: {execution_time:.2f} seconds")

        # Filter for Uniqueness / Min Unique
        valid_raw_names = []
        selected_indices_list = []
        duplicates_removed = 0

        print("Filtering candidates for uniqueness, then slotting by start time...")
        for names, indices in candidates:
            if len(valid_raw_names) >= target_lineups:
                break

            is_valid = True
            for prev_indices in selected_indices_list:
                overlap = len(indices.intersection(prev_indices))
                if overlap > (config.ROSTER_SIZE - min_unique):
                    is_valid = False
                    duplicates_removed += 1
                    break

            if is_valid:
                valid_raw_names.append(names)
                selected_indices_list.append(indices)

        # DEPRECATED as part of oversampling removal
        # excess_discarded = len(candidates) - len(valid_raw_names) - duplicates_removed

        print(f"Duplicates removed (min_unique constraint): {duplicates_removed}")
        # DEPRECATED as part of oversampling removal
        # print(f"Excess candidates discarded unread: {excess_discarded}")

        # Parallelize the slotting process
        # print("Slotting final lineups by start time...")
        final_lineups = []

        with concurrent.futures.ProcessPoolExecutor() as executor:
            # map() executes in parallel but yields results in the original order
            results = executor.map(
                slot_lineup_by_time,
                valid_raw_names,
                itertools.repeat(df, len(valid_raw_names)),
            )

            for slotted in results:
                final_lineups.append(slotted)

        print(f"Final valid lineups slotted and selected: {len(final_lineups)}")

        # Save
        if not os.path.exists(config.LINEUP_POOL_DIR):
            os.makedirs(config.LINEUP_POOL_DIR)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(
            config.LINEUP_POOL_DIR, f"lineup-pool-{timestamp}.csv"
        )
        out_df = pd.DataFrame(
            final_lineups, columns=["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
        )
        out_df.to_csv(output_file, index=False)
        print(f"Saved {len(final_lineups)} lineups to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="NBA DFS Optimization Engine (Parallel)")
    parser.add_argument("-n", "--num_lineups", type=int, default=2500, help="Number of lineups to generate (Default: 2500)")
    parser.add_argument("-r", "--randomness", type=float, default=0.25, help="Randomness factor 0.0-1.0 (Default: 0.25)")
    parser.add_argument("-u", "--min_unique", type=int, default=1, help="Min unique players between lineups (Default: 1)")
    parser.add_argument("-ms", "--min_salary", type=int, default=49500, help="Min salary for a lineup (Default: 49500)")
    parser.add_argument("-mp", "--min_projection", type=float, default=10.0, help="Min projection for a player to be considered (Default: 10.0)")
    args = parser.parse_args()

    run(
        num_lineups=args.num_lineups,
        randomness=args.randomness,
        min_unique=args.min_unique,
        min_salary=args.min_salary,
        min_projection=args.min_projection,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Good practice for Windows
    main()
