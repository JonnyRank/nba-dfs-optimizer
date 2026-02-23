import pandas as pd
import pulp
import argparse
import os
import glob
import traceback
import re
from datetime import datetime
from typing import List
import config


def get_latest_projections() -> str:
    files = glob.glob(os.path.join(config.PROJS_DIR, "NBA-Projs-*.csv"))
    if not files:
        raise FileNotFoundError(f"No projection files found in {config.PROJS_DIR}")
    return max(files, key=os.path.basename)


def is_player_locked(player_series: pd.Series) -> bool:
    """
    Determines if a player is locked based on the (LOCKED) string in Name + ID.
    """
    name_id = str(player_series.get("Name + ID", ""))
    return "(LOCKED)" in name_id.upper()


def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
    """Loads player pool and projections."""
    # We load the player pool from the bottom of the entries file
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

    # Read the player pool section
    # We join everything from the header down
    df_raw = pd.read_csv(io.StringIO("".join(lines[player_pool_start_idx:])))

    df_players = df_raw.dropna(subset=["ID"])
    df_players["ID"] = df_players["ID"].astype(str).str.split(".").str[0]

    df_projs = pd.read_csv(projs_file)
    df_projs["ID"] = df_projs["ID"].astype(str)

    df = pd.merge(df_players, df_projs, on="ID", how="left")
    df["Projection"] = pd.to_numeric(df["Projection"]).fillna(0)
    df["Salary"] = pd.to_numeric(df["Salary"])

    return df


def parse_entries(entries_file: str) -> pd.DataFrame:
    """Parses the existing lineups from the top of the file using a memory-efficient approach."""
    header_df = pd.read_csv(entries_file, nrows=0)
    valid_cols = header_df.columns.tolist()
    
    # Standardize to 25 columns max
    extra_count = max(0, 25 - len(valid_cols))
    all_cols = valid_cols + [f"extra_{i}" for i in range(extra_count)]

    df = pd.read_csv(
        entries_file, 
        header=None, 
        names=all_cols, 
        engine="python", 
        skiprows=1,
        dtype={"Entry ID": object, "Contest ID": object}
    )

    return df


def solve_late_swap(df_pool: pd.DataFrame, current_lineup_ids: List[str], min_salary: int) -> List[str]:
    """
    Optimizes the remaining slots of a lineup given a set of already locked players.
    """
    slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
    locked_ids = set()
    lineup_map = {}
    
    # Track which slots are already filled by missing/locked players
    filled_slots = [False] * len(slots)

    def get_id(s):
        m = re.search(r"\((\d+)\)", str(s))
        return m.group(1) if m else None

    def is_locked_str(s):
        return "(LOCKED)" in str(s).upper()

    # 1. Identify Locked Players and their slots
    for i, p_str in enumerate(current_lineup_ids):
        pid = get_id(p_str)
        is_locked = False
        if pid:
            if is_locked_str(p_str):
                is_locked = True
            else:
                player_data = df_pool[df_pool["ID"] == pid]
                if not player_data.empty and is_player_locked(player_data.iloc[0]):
                    is_locked = True
        
        if is_locked:
            if pid:
                locked_ids.add(pid)
            
            # Check if this locked player is in our pool
            if pid and not df_pool[df_pool["ID"] == pid].empty:
                # We'll let the solver handle this via constraints to allow slot flexibility
                # for OTHER locked players if they aren't in their "ideal" slot yet?
                # Actually, for late swap, we usually keep them in their slot unless 
                # we are doing the "flexible slotting" optimization.
                # For now, let's let the solver handle it.
                pass
            else:
                # Missing from pool but locked: we MUST keep them in this exact slot
                lineup_map[slots[i]] = p_str
                filled_slots[i] = True

    # 2. Setup Solver
    prob = pulp.LpProblem("NBA_Late_Swap", pulp.LpMaximize)
    player_vars = pulp.LpVariable.dicts("player", df_pool.index, cat=pulp.LpBinary)

    # Objective
    prob += pulp.lpSum(
        [df_pool.loc[i, "Projection"] * player_vars[i] for i in df_pool.index]
    )

    # Standard Constraints
    # Salary Cap: Total must be <= 50000. 
    # For missing players, we don't know salary, so we assume 0 for now (best effort).
    # In a real scenario, they should be in df_pool if load_data is fixed.
    prob += (
        pulp.lpSum([df_pool.loc[i, "Salary"] * player_vars[i] for i in df_pool.index])
        <= config.SALARY_CAP
    )
    prob += (
        pulp.lpSum([df_pool.loc[i, "Salary"] * player_vars[i] for i in df_pool.index])
        >= min_salary
    )
    
    # Roster Size: Solver fills the REMAINING slots
    num_to_fill = sum(1 for filled in filled_slots if not filled)
    prob += pulp.lpSum([player_vars[i] for i in df_pool.index]) == num_to_fill

    # Lock Constraints for players IN the pool
    for pid in locked_ids:
        indices = df_pool.index[df_pool["ID"] == pid].tolist()
        if indices:
            prob += player_vars[indices[0]] == 1

    # Positional Constraints
    # Only for slots that are NOT already filled
    available_slots = [slots[i] for i, filled in enumerate(filled_slots) if not filled]
    slot_vars = pulp.LpVariable.dicts("slot", (df_pool.index, available_slots), cat=pulp.LpBinary)

    for i in df_pool.index:
        prob += pulp.lpSum([slot_vars[i][s] for s in available_slots]) == player_vars[i]
        pos_str = str(df_pool.loc[i, "Roster Position"])
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

    # Min Games
    df_pool["Game"] = df_pool["Game Info"].str.split(" ").str[0]
    games = df_pool["Game"].unique()
    game_vars = pulp.LpVariable.dicts("game", games, cat=pulp.LpBinary)

    for game in games:
        players_in_game = df_pool[df_pool["Game"] == game].index
        for i in players_in_game:
            prob += game_vars[game] >= player_vars[i] / 10.0

    prob += pulp.lpSum([game_vars[game] for game in games]) >= config.MIN_GAMES

    # Solve
    solver = pulp.HiGHS(msg=False)
    prob.solve(solver)

    if pulp.LpStatus[prob.status] != "Optimal":
        print(f"Warning: Could not optimize lineup with locked IDs: {locked_ids}")
        return current_lineup_ids

    # Extract
    for i in df_pool.index:
        if pulp.value(player_vars[i]) > 0.5:
            for s in available_slots:
                if pulp.value(slot_vars[i][s]) > 0.5:
                    lineup_map[s] = df_pool.loc[i, "Name + ID"]

    return [lineup_map.get(s, "EMPTY") for s in slots]


def parse_entries_robust(entries_file: str):
    """Parses the existing lineups from the top of the file using a robust approach."""
    header_df = pd.read_csv(entries_file, nrows=0)
    valid_cols = header_df.columns.tolist()
    
    # Standardize to 25 columns max to handle ragged rows (like the player pool)
    extra_count = max(0, 25 - len(valid_cols))
    all_cols = valid_cols + [f"extra_{i}" for i in range(extra_count)]

    df = pd.read_csv(
        entries_file, 
        header=None, 
        names=all_cols, 
        engine="python", 
        skiprows=1,
        dtype={"Entry ID": object, "Contest ID": object}
    )

    return df, valid_cols


def main():
    parser = argparse.ArgumentParser(description="NBA DFS Late Swap Tool")
    parser.add_argument("-ms", "--min_salary", type=int, default=49500, help="Min salary for a lineup")
    parser.add_argument("-mp", "--min_projection", type=float, default=1.0, help="Min projection for a player to be considered")
    args = parser.parse_args()

    print("Starting Late Swap Optimization...")

    try:
        projs_file = get_latest_projections()
        print(f"Using projections: {os.path.basename(projs_file)}")

        # Load Pool
        df_pool = load_data(projs_file, config.ENTRIES_PATH)
        df_pool = df_pool[df_pool["Projection"] >= args.min_projection]
        print(f"Player Pool Loaded: {len(df_pool)} players.")

        # Load Current Entries
        df_entries, entry_cols = parse_entries_robust(config.ENTRIES_PATH)
        
        # Valid entries have an Entry ID
        # Entry ID is usually the first column
        valid_mask = df_entries[all_cols[0]].notna() if 'all_cols' in locals() else df_entries.iloc[:, 0].notna()
        # Let's be more precise with the mask
        valid_mask = df_entries[entry_cols[0]].notna()
        
        valid_entries = df_entries[valid_mask]
        print(f"Found {len(valid_entries)} entries to check for swap.")

        new_lineups = []
        slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]

        for idx, row in valid_entries.iterrows():
            # Get current players
            current_players = [row[s] for s in slots if s in row and pd.notna(row[s])]

            if len(current_players) < len(slots):
                print(f"Warning: Entry {row[entry_cols[0]]} has incomplete lineup. Skipping.")
                continue

            # Solve
            new_lineup = solve_late_swap(df_pool, current_players, args.min_salary)

            # Store result
            entry_update = {s: new_lineup[i] for i, s in enumerate(slots)}
            entry_update["index"] = idx
            new_lineups.append(entry_update)

            if len(new_lineups) % 10 == 0:
                print(f"Swapped {len(new_lineups)}/{len(valid_entries)} lineups...")

        # Update DataFrame
        for update in new_lineups:
            idx = update.pop("index")
            for s, player in update.items():
                df_entries.at[idx, s] = player

        # Save ONLY the entries section for upload compatibility
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(config.OUTPUT_DIR, f"late-swap-entries-{timestamp}.csv")
        
        # We only output the valid entry columns and rows
        df_output = df_entries[entry_cols]
        df_output = df_output[df_output[entry_cols[0]].notna()]
        
        df_output.to_csv(output_file, index=False, na_rep="")

        print(f"Late Swap Complete. {len(new_lineups)} lineups updated.")
        print(f"Saved to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
