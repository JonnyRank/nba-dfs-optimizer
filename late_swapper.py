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

    df = pd.merge(df_players, df_projs, on="ID", how="inner")
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

    Args:
        df_pool: The full player pool with projections and 'IsLocked' status.
        current_lineup_ids: List of Player IDs currently in the lineup (from the CSV).
        min_salary: Minimum salary for the lineup.

    Returns:
        List[str]: The new optimal lineup (Name + ID strings).
    """
    # 1. Identify Locked Players in this specific lineup
    # We look for the "(LOCKED)" suffix in the lineup strings.

    locked_ids = set()

    # Regex to extract ID from "Name (ID)" or "Name (ID) (LOCKED)"
    def get_id(s):
        m = re.search(r"\((\d+)\)", str(s))
        return m.group(1) if m else None

    # Helper to check if string indicates lock
    def is_locked_str(s):
        return "(LOCKED)" in str(s).upper()

    for p_str in current_lineup_ids:
        pid = get_id(p_str)
        if pid:
            if is_locked_str(p_str):
                locked_ids.add(pid)

    # 2. Setup Solver
    prob = pulp.LpProblem("NBA_Late_Swap", pulp.LpMaximize)
    player_vars = pulp.LpVariable.dicts("player", df_pool.index, cat=pulp.LpBinary)

    # Objective
    prob += pulp.lpSum(
        [df_pool.loc[i, "Projection"] * player_vars[i] for i in df_pool.index]
    )

    # Standard Constraints
    prob += (
        pulp.lpSum([df_pool.loc[i, "Salary"] * player_vars[i] for i in df_pool.index])
        <= config.SALARY_CAP
    )
    prob += (
        pulp.lpSum([df_pool.loc[i, "Salary"] * player_vars[i] for i in df_pool.index])
        >= min_salary
    )
    prob += pulp.lpSum([player_vars[i] for i in df_pool.index]) == config.ROSTER_SIZE

    # Lock Constraints
    for pid in locked_ids:
        # Find index of this player
        indices = df_pool.index[df_pool["ID"] == pid].tolist()
        if indices:
            prob += player_vars[indices[0]] == 1

    # Positional Constraints
    slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
    slot_vars = pulp.LpVariable.dicts("slot", (df_pool.index, slots), cat=pulp.LpBinary)

    for i in df_pool.index:
        prob += pulp.lpSum([slot_vars[i][s] for s in slots]) == player_vars[i]
        pos_str = str(df_pool.loc[i, "Roster Position"])
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
        prob += pulp.lpSum([slot_vars[i][s] for i in df_pool.index]) == 1

    # Min Games (Only apply to the full lineup, locked + new)
    # The solver handles the full lineup, so this is just standard
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
        return current_lineup_ids  # Return original if failed

    # Extract
    lineup_map = {}
    for i in df_pool.index:
        if pulp.value(player_vars[i]) > 0.5:
            # We need to assign them to slots correctly
            # The solver has slot_vars
            for s in slots:
                if pulp.value(slot_vars[i][s]) > 0.5:
                    lineup_map[s] = df_pool.loc[i, "Name + ID"]

    return [lineup_map.get(s, "EMPTY") for s in slots]


def main():
    parser = argparse.ArgumentParser(description="NBA DFS Late Swap Tool")
    parser.add_argument("-ms", "--min_salary", type=int, default=49500, help="Min salary for a lineup")
    parser.add_argument("-mp", "--min_projection", type=float, default=10.0, help="Min projection for a player to be considered")
    args = parser.parse_args()

    print("Starting Late Swap Optimization...")

    try:
        projs_file = get_latest_projections()
        print(f"Using projections: {os.path.basename(projs_file)}")

        # Load Pool
        df_pool = load_data(projs_file, config.ENTRIES_PATH)
        df_pool = df_pool[df_pool["Projection"] >= args.min_projection]
        print(f"Player Pool Loaded: {len(df_pool)} players (after min projection filter).")

        # Load Current Entries
        # parsing correctly requires handling the mixed file structure
        # We can reuse the logic from exporter.py to read the whole thing
        df_entries = pd.read_csv(
            config.ENTRIES_PATH, dtype={"Entry ID": object, "Contest ID": object}
        )
        valid_entries = df_entries[df_entries["Entry ID"].notna()]
        print(f"Found {len(valid_entries)} entries to check for swap.")

        new_lineups = []
        slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]

        for idx, row in valid_entries.iterrows():
            # Get current players
            current_players = [row[s] for s in slots if pd.notna(row[s])]

            # Solve
            # Note: This runs sequentially. For 150 lineups, it might take 1-2 mins.
            # HiGHS is fast, so this is likely acceptable.
            new_lineup = solve_late_swap(df_pool, current_players, args.min_salary)

            # Store result (preserving original index is not needed since we iterate)
            # We construct a dict to update the main df later
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

        # Save
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(config.OUTPUT_DIR, f"late-swap-entries-{timestamp}.csv")
        df_entries.to_csv(output_file, index=False, na_rep="")

        # Append Player Pool (to keep file valid for DK?)
        # Actually, for "Edit Entry" uploads, DK usually just wants the Entry ID + Positions.
        # But keeping the full format is safer.
        # However, df_entries contains everything if we read the whole file.
        # The only issue is the "Player Pool" header row which might have been read as data.
        # If we read the WHOLE file into df_entries, the bottom part is preserved in the rows.

        print(f"Late Swap Complete. Saved to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
