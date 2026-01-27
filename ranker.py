import pandas as pd
import numpy as np
import glob
import os
import argparse
import traceback
from datetime import datetime
from typing import Dict

# --- CONFIGURATION ---
PROJS_DIR = r"G:\My Drive\Documents\CSV-Exports"
LINEUP_DIR = r"G:\My Drive\Documents\CSV-Exports\lineup-pools"

def get_latest_file(directory: str, pattern: str) -> str:
    """Finds the most recent file matching a pattern in a directory."""
    files = glob.glob(os.path.join(directory, pattern))
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} found in {directory}")
    return max(files, key=os.path.basename)

def load_data(lineup_file: str, projs_file: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Loads lineups and player data (projections/ownership)."""
    df_lineups = pd.read_csv(lineup_file)
    df_projs = pd.read_csv(projs_file)
    df_projs['ID'] = df_projs['ID'].astype(str)
    
    # Extract ID from Name + ID string: "Name (ID)"
    def extract_id(val):
        if pd.isna(val):
            return None
        # Look for digits inside parentheses
        import re
        match = re.search(r'\((\d+)\)', str(val))
        return match.group(1) if match else None

    # We need a mapping from Name + ID to Projection and Ownership
    # The engine uses Name + ID in the CSV, so we'll map that directly.
    # To do this reliably, we'll read DKEntries again or just use the IDs.
    
    # Better approach: Create a dictionary from the Projections file
    # But wait, the Projections file only has ID. The engine merges it with DKEntries.
    # We should probably have saved the player data or re-run the merge logic.
    # Let's re-run the merge logic here to get the full player context.
    
    from engine import load_data as engine_load_data, ENTRIES_PATH
    df_players = engine_load_data(projs_file, ENTRIES_PATH)
    
    return df_lineups, df_players

def rank_lineups(df_lineups: pd.DataFrame, df_players: pd.DataFrame, weights: Dict[str, float]):
    """
    Calculates metrics and ranks lineups based on weighted scores.
    
    Weights should look like: {'proj': 1.0, 'own': 0.5, 'geo': 0.5}
    Higher weights mean that metric has more influence on the final score.
    Note: For 'own' and 'geo', we want LOWER values, so we rank accordingly.
    """
    # Map Name + ID to metrics
    proj_map = df_players.set_index('Name + ID')['Projection'].to_dict()
    own_map = df_players.set_index('Name + ID')['Own_Proj'].to_dict()
    
    lineup_results = []
    
    slots = ['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UTIL']
    
    for idx, row in df_lineups.iterrows():
        lineup_names = [row[s] for s in slots]
        
        total_proj = sum([proj_map.get(name, 0) for name in lineup_names])
        total_own = sum([own_map.get(name, 0) for name in lineup_names])
        
        # Geomean Ownership (add small epsilon to avoid log(0))
        own_values = [own_map.get(name, 0) for name in lineup_names]
        geo_own = np.exp(np.mean(np.log([max(0.1, o) for o in own_values])))
        
        lineup_results.append({
            'Lineup_ID': idx + 1,
            'Total_Projection': total_proj,
            'Total_Ownership': total_own,
            'Geomean_Ownership': geo_own,
            **{s: row[s] for s in slots}
        })
        
    df_res = pd.DataFrame(lineup_results)
    
    # Calculate Ranks (1 is best)
    # Total Projection: Higher is better
    df_res['Proj_Rank'] = df_res['Total_Projection'].rank(ascending=False)
    # Total Ownership: Lower is better
    df_res['Own_Rank'] = df_res['Total_Ownership'].rank(ascending=True)
    # Geomean Ownership: Lower is better
    df_res['Geo_Rank'] = df_res['Geomean_Ownership'].rank(ascending=True)
    
    # Final Score: Weighted sum of ranks
    # Lower Score = Better Lineup
    df_res['Lineup_Score'] = (
        df_res['Proj_Rank'] * weights.get('proj', 1.0) +
        df_res['Own_Rank'] * weights.get('own', 1.0) +
        df_res['Geo_Rank'] * weights.get('geo', 1.0)
    )
    
    # Sort by Score
    df_res = df_res.sort_values('Lineup_Score')
    df_res['Final_Rank'] = range(1, len(df_res) + 1)
    
    return df_res

def main():
    parser = argparse.ArgumentParser(description="NBA DFS Lineup Sorter & Ranker")
    parser.add_argument("--proj_weight", type=float, default=0.85, help="Weight for Projection Rank")
    parser.add_argument("--own_weight", type=float, default=0.0, help="Weight for Total Ownership Rank")
    parser.add_argument("--geo_weight", type=float, default=0.15, help="Weight for Geomean Ownership Rank")
    args = parser.parse_args()

    print("Starting NBA DFS Sorter & Ranker...")
    
    try:
        # 1. Identify latest files
        lineup_file = get_latest_file(LINEUP_DIR, "lineup-pool-*.csv")
        projs_file = get_latest_file(PROJS_DIR, "NBA-Projs-*.csv")
        
        print(f"Ranking: {os.path.basename(lineup_file)}")
        print(f"Using metrics from: {os.path.basename(projs_file)}")
        
        # 2. Load and merge
        df_lineups, df_players = load_data(lineup_file, projs_file)
        
        # 3. Rank
        weights = {
            'proj': args.proj_weight,
            'own': args.own_weight,
            'geo': args.geo_weight
        }
        df_ranked = rank_lineups(df_lineups, df_players, weights)
        
        # 4. Save
        # Reuse timestamp from original lineup file if possible, or just new one
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(LINEUP_DIR, f"ranked-lineups-{timestamp}.csv")
        
        # Reorder columns to put rankings first
        cols = ['Final_Rank', 'Lineup_Score', 'Total_Projection', 'Total_Ownership', 'Geomean_Ownership', 
                'Proj_Rank', 'Own_Rank', 'Geo_Rank'] + \
               ['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UTIL']
        
        df_ranked[cols].to_csv(output_file, index=False)
        print(f"Successfully ranked {len(df_ranked)} lineups.")
        print(f"Saved to: {output_file}")
        
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
