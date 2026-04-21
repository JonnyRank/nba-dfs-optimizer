import argparse
import os
import traceback
from datetime import datetime
from typing import List

import pandas as pd
import pulp

from .config import Config
from .utils import (
    extract_player_id,
    get_latest_file,
    is_player_locked,
    parse_game_time,
    read_ragged_csv,
)


def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
    """Loads player pool and projections."""
    with open(entries_file, "r") as f:
        lines = f.readlines()

    player_pool_start_idx = -1
    for i, line in enumerate(lines):
        if "Position,Name + ID,Name,ID" in line:
            player_pool_start_idx = i
            break

    if player_pool_start_idx == -1:
        raise ValueError("Could not find player pool section in DKEntries.csv")

    import io

    df_raw = pd.read_csv(io.StringIO("".join(lines[player_pool_start_idx:])))
    df_players = df_raw.dropna(subset=["ID"])
    df_players["ID"] = df_players["ID"].astype(str).str.split(".").str[0]

    df_projs = pd.read_csv(projs_file)
    df_projs["ID"] = df_projs["ID"].astype(str)

    df = pd.merge(df_players, df_projs, on="ID", how="left")
    df["Projection"] = pd.to_numeric(df["Projection"]).fillna(0)
    df["Salary"] = pd.to_numeric(df["Salary"])

    return df


def solve_late_swap_batch(
    df_pool: pd.DataFrame,
    current_lineup_ids: List[str],
    cfg: Config,
    num_to_generate: int,
) -> List[List[str]]:
    """Optimizes the remaining slots of a lineup and generates a batch of unique variations."""
    slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
    flex_scores = {
        "UTIL": 3,
        "G": 2,
        "F": 2,
        "PG": 1,
        "SG": 1,
        "SF": 1,
        "PF": 1,
        "C": 1,
    }

    locked_ids = set()
    lineup_map = {}
    filled_slots = [False] * len(slots)
    locked_salary_used = 0
    locked_games = set()

    # 1. Identify Locked Players and their slots
    for i, p_str in enumerate(current_lineup_ids):
        pid = extract_player_id(p_str)
        is_locked = False
        if pid:
            if is_player_locked(p_str):
                is_locked = True
            else:
                player_data = df_pool[df_pool["ID"] == pid]
                if not player_data.empty and is_player_locked(
                    player_data.iloc[0].get("Name + ID", "")
                ):
                    is_locked = True

        if is_locked:
            lineup_map[slots[i]] = p_str
            filled_slots[i] = True
            if pid:
                locked_ids.add(pid)
                player_data = df_pool[df_pool["ID"] == pid]
                if not player_data.empty:
                    locked_salary_used += player_data.iloc[0]["Salary"]
                    game = player_data.iloc[0]["Game Info"].split(" ")[0]
                    locked_games.add(game)

    # Fast path: If the lineup is completely locked, return it N times.
    num_to_fill = sum(1 for filled in filled_slots if not filled)
    if num_to_fill == 0:
        return [
            [lineup_map.get(s, "EMPTY") for s in slots] for _ in range(num_to_generate)
        ]

    # 2. Setup Solver Base
    prob = pulp.LpProblem("NBA_Late_Swap", pulp.LpMaximize)
    player_vars = pulp.LpVariable.dicts("player", df_pool.index, cat=pulp.LpBinary)

    # Convert DataFrame columns to dictionaries for O(1) lookup (optimization pattern from engine.py)
    projection_dict = df_pool["Projection"].to_dict()
    salary_dict = df_pool["Salary"].to_dict()
    pos_dict = df_pool["Roster Position"].to_dict()
    name_dict = df_pool["Name + ID"].to_dict()
    id_dict = df_pool["ID"].to_dict()

    base_obj = pulp.lpSum(
        [projection_dict[i] * player_vars[i] for i in df_pool.index]
    )

    available_slots = [slots[i] for i, filled in enumerate(filled_slots) if not filled]
    slot_vars = pulp.LpVariable.dicts(
        "slot", (df_pool.index, available_slots), cat=pulp.LpBinary
    )

    # Pre-compute time scores and store in dictionary for O(1) lookup
    incentive_terms = []
    if "StartTime" not in df_pool.columns:
        df_pool["StartTime"] = df_pool["Game Info"].apply(parse_game_time)
    min_time = df_pool["StartTime"].min()
    max_time = df_pool["StartTime"].max()
    time_range = (max_time - min_time).total_seconds() or 1.0

    # Convert StartTime to dict and compute time scores once
    start_time_dict = df_pool["StartTime"].to_dict()
    time_score_dict = {}
    for i in df_pool.index:
        time_score_dict[i] = (start_time_dict[i] - min_time).total_seconds() / time_range

    for i in df_pool.index:
        for s in available_slots:
            weight = time_score_dict[i] * flex_scores.get(s, 1) * 0.001
            incentive_terms.append(slot_vars[i][s] * weight)

    prob += base_obj + pulp.lpSum(incentive_terms)

    prob += (
        pulp.lpSum([salary_dict[i] * player_vars[i] for i in df_pool.index])
        <= cfg.salary_cap - locked_salary_used
    )
    adj_min_salary = max(0, cfg.min_salary - locked_salary_used)
    prob += (
        pulp.lpSum([salary_dict[i] * player_vars[i] for i in df_pool.index])
        >= adj_min_salary
    )
    prob += pulp.lpSum([player_vars[i] for i in df_pool.index]) == num_to_fill

    # Use name_dict to check locked players instead of df.loc
    for i in df_pool.index:
        if is_player_locked(name_dict[i]):
            prob += player_vars[i] == 0

    # Use pos_dict for position eligibility instead of df.loc
    for i in df_pool.index:
        prob += pulp.lpSum([slot_vars[i][s] for s in available_slots]) == player_vars[i]
        pos_str = str(pos_dict[i])
        for s in available_slots:
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

    for s in available_slots:
        prob += pulp.lpSum([slot_vars[i][s] for i in df_pool.index]) == 1

    df_pool["Game"] = df_pool["Game Info"].str.split(" ").str[0]
    games = df_pool["Game"].unique()
    game_vars = pulp.LpVariable.dicts("game", games, cat=pulp.LpBinary)

    for game in games:
        players_in_game = df_pool[df_pool["Game"] == game].index
        for i in players_in_game:
            prob += game_vars[game] >= player_vars[i] / 10.0

    adj_min_games = max(0, cfg.min_games - len(locked_games))
    prob += pulp.lpSum([game_vars[game] for game in games]) >= adj_min_games

    # 3. Iterative Batch Solving
    generated_lineups = []

    for iteration in range(num_to_generate):
        solver = pulp.HiGHS(msg=False)
        prob.solve(solver)

        if pulp.LpStatus[prob.status] != "Optimal":
            if iteration == 0:
                print(
                    f"Warning: Could not optimize lineup for base state. Status: {pulp.LpStatus[prob.status]}"
                )
                return [current_lineup_ids for _ in range(num_to_generate)]
            else:
                while len(generated_lineups) < num_to_generate:
                    generated_lineups.append(generated_lineups[-1])
                break

        current_lineup_map = lineup_map.copy()
        newly_drafted_indices = []

        # Use id_dict and name_dict for result extraction instead of df.loc
        for i in df_pool.index:
            if pulp.value(player_vars[i]) > 0.5:
                if id_dict[i] not in locked_ids:
                    newly_drafted_indices.append(i)
                for s in available_slots:
                    if pulp.value(slot_vars[i][s]) > 0.5:
                        current_lineup_map[s] = name_dict[i]

        generated_lineups.append([current_lineup_map.get(s, "EMPTY") for s in slots])

        if newly_drafted_indices:
            prob += pulp.lpSum([player_vars[i] for i in newly_drafted_indices]) <= (
                len(newly_drafted_indices) - 1
            )

    return generated_lineups


def run(cfg: Config):
    print("Starting Late Swap Optimization...")

    try:
        projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv")
        print(f"Using projections: {os.path.basename(projs_file)}")

        df_entries, entry_cols = read_ragged_csv(cfg.entries_path)

        valid_mask = df_entries[entry_cols[0]].notna()
        valid_entries = df_entries[valid_mask]

        current_ids = set()
        slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
        for _, row in valid_entries.iterrows():
            for s in slots:
                val = row.get(s)
                if pd.notna(val):
                    pid = extract_player_id(val)
                    if pid:
                        current_ids.add(pid)

        df_pool = load_data(projs_file, cfg.entries_path)

        mask_proj = df_pool["Projection"] >= cfg.min_projection
        mask_current = df_pool["ID"].isin(current_ids)
        df_pool = df_pool[mask_proj | mask_current].copy()
        df_pool.reset_index(drop=True, inplace=True)

        print(f"Player Pool Loaded: {len(df_pool)} players.")
        print(f"Found {len(valid_entries)} valid entries.")

        base_states = {}
        for idx, row in valid_entries.iterrows():
            current_players = [row[s] for s in slots if s in row and pd.notna(row[s])]
            if len(current_players) < len(slots):
                print(
                    f"Warning: Entry {row[entry_cols[0]]} has an incomplete lineup. Skipping."
                )
                continue

            locked_signature = []
            for i, p_str in enumerate(current_players):
                pid = extract_player_id(p_str)
                is_locked = is_player_locked(p_str)
                if not is_locked and pid:
                    player_data = df_pool[df_pool["ID"] == pid]
                    if not player_data.empty and is_player_locked(
                        player_data.iloc[0].get("Name + ID", "")
                    ):
                        is_locked = True

                if is_locked and pid:
                    locked_signature.append((slots[i], pid))

            base_state_key = tuple(locked_signature)
            if base_state_key not in base_states:
                base_states[base_state_key] = []
            base_states[base_state_key].append((idx, current_players))

        print(
            f"Grouped entries into {len(base_states)} unique base states for batch processing."
        )

        new_lineups = []
        for i, (base_state_key, entries) in enumerate(base_states.items()):
            num_to_generate = len(entries)
            template_players = entries[0][1]

            batch_lineups = solve_late_swap_batch(
                df_pool, template_players, cfg, num_to_generate
            )

            for j, (idx, _) in enumerate(entries):
                entry_update = {s: batch_lineups[j][k] for k, s in enumerate(slots)}
                entry_update["index"] = idx
                new_lineups.append(entry_update)

            if (i + 1) % max(1, (len(base_states) // 10)) == 0:
                print(f"Processed {i + 1}/{len(base_states)} base states...")

        for update in new_lineups:
            idx = update.pop("index")
            for s, player in update.items():
                df_entries.at[idx, s] = player

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(
            cfg.output_dir, f"late-swap-entries-{timestamp}.csv"
        )

        required_cols = [
            "Entry ID",
            "Contest Name",
            "Contest ID",
            "Entry Fee",
            "PG",
            "SG",
            "SF",
            "PF",
            "C",
            "G",
            "F",
            "UTIL",
        ]

        df_output = df_entries[required_cols]
        df_output = df_output[df_output["Entry ID"].notna()]

        df_output.to_csv(output_file, index=False, na_rep="")

        print(f"Late Swap Complete. {len(new_lineups)} lineups updated.")
        print(f"Saved to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


def main():
    from dataclasses import replace
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Late Swap Tool")
    parser.add_argument(
        "-ms", "--min_salary", type=int, default=49500, help="Min salary for a lineup"
    )
    parser.add_argument(
        "-mp",
        "--min_projection",
        type=float,
        default=1.0,
        help="Min projection for a player",
    )
    args = parser.parse_args()

    cfg = load_config_from_env()
    cfg = replace(cfg, min_salary=args.min_salary, min_projection=args.min_projection)

    run(cfg)


if __name__ == "__main__":
    main()
