import pandas as pd
import numpy as np
import pulp
import glob
import os
import re
import traceback
import argparse
from datetime import datetime
from typing import List, Set, Tuple
import concurrent.futures
import multiprocessing

# --- CONFIGURATION ---
ENTRIES_PATH = r"C:\Users\jrank\Downloads\DKEntries.csv"
PROJS_DIR = r"G:\My Drive\Documents\CSV-Exports"
OUTPUT_DIR = r"G:\My Drive\Documents\CSV-Exports\lineup-pools"

SALARY_CAP = 50000
ROSTER_SIZE = 8
MIN_GAMES = 2

# --- DATA LOADING ---
def get_latest_projections() -> str:
    files = glob.glob(os.path.join(PROJS_DIR, "NBA-Projs-*.csv"))
    if not files:
        raise FileNotFoundError(f"No projection files found in {PROJS_DIR}")
    return max(files, key=os.path.basename)

def load_data(projs_file: str, entries_file: str) -> pd.DataFrame:
    df_raw = pd.read_csv(entries_file, skiprows=7)
    
    pos_col_idx = -1
    for i, col in enumerate(df_raw.columns):
        if 'Position' in str(col):
            pos_col_idx = i
            break
            
    if pos_col_idx == -1:
        raise ValueError("Could not find 'Position' column in DKEntries.csv")
        
    df_players = df_raw.iloc[:, pos_col_idx:].dropna(subset=['ID'])
    df_players['ID'] = df_players['ID'].astype(str).str.split('.').str[0]
    
    df_projs = pd.read_csv(projs_file)
    df_projs['ID'] = df_projs['ID'].astype(str)
    
    df = pd.merge(df_players, df_projs, on='ID', how='inner')
    
    def parse_time(game_info):
        match = re.search(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2}[APM]+)', game_info)
        if match:
            return datetime.strptime(match.group(1), '%m/%d/%Y %I:%M%p')
        return datetime.max

    df['StartTime'] = df['Game Info'].apply(parse_time)
    df['Salary'] = pd.to_numeric(df['Salary'])
    
    return df

# --- WORKER FUNCTION (MUST BE TOP-LEVEL) ---
def generate_single_lineup(df: pd.DataFrame, randomness: float) -> Tuple[List[str], Set[int]]:
    """
    Worker function to generate one lineup with simulated projections.
    Independent of other lineups (no exclusion constraints).
    """
    try:
        # Re-seed numpy in each process to ensuring true randomness
        np.random.seed()
        
        prob = pulp.LpProblem("NBA_DFS_Worker", pulp.LpMaximize)
        
        # Apply Randomness
        if randomness > 0:
            # We use a copy to avoid modifying the shared dataframe (though MP usually pickles it)
            sim_proj = df['Projection'] * (1 + np.random.uniform(-randomness, randomness, len(df)))
        else:
            sim_proj = df['Projection']
        
        # Decision Variables
        player_vars = pulp.LpVariable.dicts("player", df.index, cat=pulp.LpBinary)
        
        # Objective
        prob += pulp.lpSum([sim_proj[i] * player_vars[i] for i in df.index])
        
        # Constraints
        prob += pulp.lpSum([df.loc[i, 'Salary'] * player_vars[i] for i in df.index]) <= SALARY_CAP
        prob += pulp.lpSum([player_vars[i] for i in df.index]) == ROSTER_SIZE
        
        # Positional
        slots = ['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UTIL']
        slot_vars = pulp.LpVariable.dicts("slot", (df.index, slots), cat=pulp.LpBinary)
        
        for i in df.index:
            prob += pulp.lpSum([slot_vars[i][s] for s in slots]) == player_vars[i]
            pos_str = str(df.loc[i, 'Roster Position'])
            for s in slots:
                eligible = False
                if s == 'UTIL':
                    eligible = True
                elif s == 'G':
                    eligible = 'PG' in pos_str or 'SG' in pos_str
                elif s == 'F':
                    eligible = 'SF' in pos_str or 'PF' in pos_str
                else:
                    eligible = s in pos_str
                
                if not eligible:
                    prob += slot_vars[i][s] == 0
                    
        for s in slots:
            prob += pulp.lpSum([slot_vars[i][s] for i in df.index]) == 1

        # Min Games
        df['Game'] = df['Game Info'].str.split(' ').str[0]
        games = df['Game'].unique()
        game_vars = pulp.LpVariable.dicts("game", games, cat=pulp.LpBinary)
        
        for game in games:
            players_in_game = df[df['Game'] == game].index
            for i in players_in_game:
                prob += game_vars[game] >= player_vars[i] / 10.0
                
        prob += pulp.lpSum([game_vars[game] for game in games]) >= MIN_GAMES

        # Solve
        solver = pulp.HiGHS(msg=False)
        prob.solve(solver)
        
        if pulp.LpStatus[prob.status] != 'Optimal':
            return None, None
            
        lineup_names = []
        selected_indices = set()
        for i in df.index:
            if pulp.value(player_vars[i]) > 0.5:
                lineup_names.append(df.loc[i, 'Name + ID'])
                selected_indices.add(i)
                
        return lineup_names, selected_indices
        
    except Exception:
        # In MP, printing tracebacks can be messy, but let's try
        traceback.print_exc()
        return None, None

def slot_lineup_by_time(lineup_names: List[str], df: pd.DataFrame) -> List[str]:
    # This is fast enough to run sequentially or in the worker.
    # Let's keep it sequential post-processing to keep worker simple.
    players = df[df['Name + ID'].isin(lineup_names)].copy()
    if len(players) != 8:
        return ["ERROR"] * 8

    slot_weights = {'PG': 1, 'SG': 1, 'SF': 1, 'PF': 1, 'C': 1, 'G': 10, 'F': 10, 'UTIL': 100}
    slots = ['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UTIL']
    
    prob = pulp.LpProblem("Slotting", pulp.LpMaximize)
    slot_vars = pulp.LpVariable.dicts("slot", (players.index, slots), cat=pulp.LpBinary)
    
    min_time = players['StartTime'].min()
    players['TimeScore'] = (players['StartTime'] - min_time).dt.total_seconds() / 60.0

    prob += pulp.lpSum([
        slot_vars[i][s] * players.loc[i, 'TimeScore'] * slot_weights[s]
        for i in players.index for s in slots
    ])
    
    for i in players.index:
        prob += pulp.lpSum([slot_vars[i][s] for s in slots]) == 1
        pos_str = str(players.loc[i, 'Roster Position'])
        for s in slots:
            eligible = False
            if s == 'UTIL':
                eligible = True
            elif s == 'G':
                eligible = 'PG' in pos_str or 'SG' in pos_str
            elif s == 'F':
                eligible = 'SF' in pos_str or 'PF' in pos_str
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
                final_lineup[s] = players.loc[i, 'Name + ID']
                
    return [final_lineup.get(s, "EMPTY") for s in slots]

def main():
    parser = argparse.ArgumentParser(description="NBA DFS Optimization Engine (Parallel)")
    parser.add_argument("-n", "--num_lineups", type=int, default=10, help="Number of lineups to generate")
    parser.add_argument("-r", "--randomness", type=float, default=0.1, help="Randomness factor (0.0 - 1.0)")
    parser.add_argument("-u", "--min_unique", type=int, default=1, help="Min unique players vs previous lineups")
    args = parser.parse_args()

    print("Starting NBA DFS Optimizer (Parallel Mode)...")
    print(f"Settings: {args.num_lineups} lineups, {args.randomness * 100:.0f}% randomness, {args.min_unique} min unique")
    
    # Check if randomness is 0
    if args.randomness <= 0:
        print("WARNING: Randomness is 0. Parallel workers will likely generate identical lineups.")
        print("Using sequential Iterative Exclusion logic instead? No, this script is now Parallel-only.")
        print("Please enable randomness (>0) for parallel mode efficiency.")

    try:
        projs_file = get_latest_projections()
        print(f"Using projections: {os.path.basename(projs_file)}")
        
        df = load_data(projs_file, ENTRIES_PATH)
        print(f"Loaded {len(df)} players.")
        
        # Strategy: Generate more than needed to account for duplicates/overlap
        target_lineups = args.num_lineups
        oversample_factor = 3 if args.min_unique > 1 else 1.5
        num_tasks = int(target_lineups * oversample_factor)
        
        print(f"Spinning up pool with {multiprocessing.cpu_count()} cores to generate ~{num_tasks} candidates...")
        
        candidates = []
        
        with concurrent.futures.ProcessPoolExecutor() as executor:
            # We must pass df and randomness to each worker
            # Since df is static, it gets pickled once (or shared via COW on Linux, but picked on Windows)
            futures = [executor.submit(generate_single_lineup, df, args.randomness) for _ in range(num_tasks)]
            
            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                try:
                    names, indices = future.result()
                    if names and indices:
                        candidates.append((names, indices))
                    
                    if (i + 1) % 20 == 0:
                        print(f"Candidates generated: {i + 1}/{num_tasks}")
                except Exception as exc:
                    print(f"Worker generated exception: {exc}")

        print(f"Total candidates generated: {len(candidates)}")
        
        # Filter for Uniqueness / Min Unique
        final_lineups = []
        selected_indices_list = []
        
        print("Filtering candidates for uniqueness...")
        for names, indices in candidates:
            if len(final_lineups) >= target_lineups:
                break
                
            is_valid = True
            for prev_indices in selected_indices_list:
                # Calculate overlap
                # Intersection size
                overlap = len(indices.intersection(prev_indices))
                # Max allowed overlap = 8 - min_unique
                if overlap > (ROSTER_SIZE - args.min_unique):
                    is_valid = False
                    break
            
            if is_valid:
                # Post-process slotting (fast)
                slotted = slot_lineup_by_time(names, df)
                final_lineups.append(slotted)
                selected_indices_list.append(indices)
        
        print(f"Final valid lineups selected: {len(final_lineups)}")
        
        if len(final_lineups) < target_lineups:
            print("Warning: Could not find enough unique lineups from the candidate pool.")
            print("Try increasing randomness or running again.")

        # Save
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR)
            
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(OUTPUT_DIR, f"lineup-pool-{timestamp}.csv")
        
        out_df = pd.DataFrame(final_lineups, columns=['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UTIL'])
        out_df.to_csv(output_file, index=False)
        print(f"Saved {len(final_lineups)} lineups to {output_file}")
        
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    multiprocessing.freeze_support() # Good practice for Windows
    main()