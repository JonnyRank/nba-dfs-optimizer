import pandas as pd
import numpy as np
import pulp
import glob
import os
import re
import traceback
import argparse
from datetime import datetime
from typing import List, Set

# --- CONFIGURATION ---
ENTRIES_PATH = r"C:\Users\jrank\Downloads\DKEntries.csv"
PROJS_DIR = r"G:\My Drive\Documents\CSV-Exports"
OUTPUT_DIR = r"G:\My Drive\Documents\CSV-Exports\lineup-pools"

SALARY_CAP = 50000
ROSTER_SIZE = 8
MIN_GAMES = 2

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

def solve_lineup(df: pd.DataFrame, randomness: float, past_lineups: List[Set[int]], min_unique: int) -> tuple[List[str], Set[int]]:
    """
    Generates a single optimal lineup using PuLP, excluding past lineups.
    
    Args:
        df: Player DataFrame.
        randomness: Random variance.
        past_lineups: List of sets, where each set contains the indices of players in a previous lineup.
        min_unique: Minimum number of unique players required vs past lineups.
        
    Returns:
        tuple: (List of player names, Set of player indices)
    """
    try:
        prob = pulp.LpProblem("NBA_DFS", pulp.LpMaximize)
        
        # Randomize Projections if randomness > 0
        if randomness > 0:
            df['SimProj'] = df['Projection'] * (1 + np.random.uniform(-randomness, randomness, len(df)))
        else:
            df['SimProj'] = df['Projection']
        
        player_vars = pulp.LpVariable.dicts("player", df.index, cat=pulp.LpBinary)
        
        prob += pulp.lpSum([df.loc[i, 'SimProj'] * player_vars[i] for i in df.index])
        
        # Standard Constraints
        prob += pulp.lpSum([df.loc[i, 'Salary'] * player_vars[i] for i in df.index]) <= SALARY_CAP
        prob += pulp.lpSum([player_vars[i] for i in df.index]) == ROSTER_SIZE
        
        # Exclusion Constraints (Iterative Solver)
        # For every past lineup, ensure we don't pick more than (8 - min_unique) of the same players
        for prev_indices in past_lineups:
            prob += pulp.lpSum([player_vars[i] for i in prev_indices]) <= (ROSTER_SIZE - min_unique)
        
        # Positional Constraints
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
        traceback.print_exc()
        return None, None

def slot_lineup_by_time(lineup_names: List[str], df: pd.DataFrame) -> List[str]:
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
    
    if pulp.LpStatus[prob.status] != 'Optimal':
        return lineup_names
        
    final_lineup = {}
    for i in players.index:
        for s in slots:
            if pulp.value(slot_vars[i][s]) > 0.5:
                final_lineup[s] = players.loc[i, 'Name + ID']
                
    return [final_lineup.get(s, "EMPTY") for s in slots]

def main():
    parser = argparse.ArgumentParser(description="NBA DFS Optimization Engine")
    parser.add_argument("--num_lineups", type=int, default=10, help="Number of lineups to generate")
    parser.add_argument("--randomness", type=float, default=0.1, help="Randomness factor (0.0 - 1.0)")
    parser.add_argument("--min_unique", type=int, default=1, help="Min unique players vs previous lineups")
    args = parser.parse_args()

    print("Starting NBA DFS Optimizer (Sim/Solve)...")
    print(f"Settings: {args.num_lineups} lineups, {args.randomness * 100:.0f}% randomness, {args.min_unique} min unique")

    try:
        projs_file = get_latest_projections()
        print(f"Using projections: {os.path.basename(projs_file)}")
        
        df = load_data(projs_file, ENTRIES_PATH)
        print(f"Loaded {len(df)} players.")
        
        lineups = []
        past_indices_list = []
        
        while len(lineups) < args.num_lineups:
            names, indices = solve_lineup(df, args.randomness, past_indices_list, args.min_unique)
            if names:
                slotted = slot_lineup_by_time(names, df)
                lineups.append(slotted)
                past_indices_list.append(indices)
                
                if len(lineups) % 20 == 0:
                    print(f"Generated {len(lineups)}/{args.num_lineups} lineups...")
            else:
                print("Failed to find optimal lineup (constraints too tight?), stopping.")
                break
        
        if not os.path.exists(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR)
            
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(OUTPUT_DIR, f"lineup-pool-{timestamp}.csv")
        
        out_df = pd.DataFrame(lineups, columns=['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UTIL'])
        out_df.to_csv(output_file, index=False)
        print(f"Saved {len(lineups)} lineups to {output_file}")
        
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
