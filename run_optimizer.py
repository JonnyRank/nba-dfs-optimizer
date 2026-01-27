import subprocess
import argparse
import sys
import os

def run_command(command, description):
    """Executes a shell command and prints status."""
    print(f"\n--- {description} ---")
    print(f"Running: {command}")
    try:
        # distinct separation between steps
        result = subprocess.run(command, shell=True, check=True, text=True)
        if result.returncode == 0:
            print(f"SUCCESS: {description} completed.")
        else:
            print(f"ERROR: {description} failed with return code {result.returncode}.")
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"CRITICAL ERROR during {description}: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="NBA DFS Optimizer - Main Orchestrator")
    
    # Engine Arguments
    parser.add_argument("--num_lineups", type=int, default=20, help="Number of lineups to generate (Default: 20)")
    parser.add_argument("--randomness", type=float, default=0.1, help="Randomness factor 0.0-1.0 (Default: 0.1)")
    parser.add_argument("--min_unique", type=int, default=1, help="Min unique players between lineups (Default: 1)")
    
    # Ranker Arguments
    parser.add_argument("--proj_weight", type=float, default=0.85, help="Weight for Projection Rank (Default: 0.85)")
    parser.add_argument("--own_weight", type=float, default=0.0, help="Weight for Ownership Rank (Default: 0.0)")
    parser.add_argument("--geo_weight", type=float, default=0.15, help="Weight for Geomean Rank (Default: 0.15)")
    
    args = parser.parse_args()
    
    # 1. Run Engine
    # We use the current python interpreter
    python_exe = sys.executable
    
    engine_cmd = (
        f'"{python_exe}" engine.py '
        f'--num_lineups {args.num_lineups} '
        f'--randomness {args.randomness} '
        f'--min_unique {args.min_unique}'
    )
    run_command(engine_cmd, "Phase 1: Generating Lineups")
    
    # 2. Run Ranker
    ranker_cmd = (
        f'"{python_exe}" ranker.py '
        f'--proj_weight {args.proj_weight} '
        f'--own_weight {args.own_weight} '
        f'--geo_weight {args.geo_weight}'
    )
    run_command(ranker_cmd, "Phase 2: Ranking Lineups")
    
    # 3. Run Exporter
    # Exporter automatically picks up the latest ranked file and finds the valid entries
    exporter_cmd = f'"{python_exe}" exporter.py'
    run_command(exporter_cmd, "Phase 3: Exporting to DraftKings CSV")
    
    print("\n===========================================")
    print("Optimization Pipeline Complete!")
    print("Check your Downloads folder for the 'upload_ready_DKEntries' file.")
    print("===========================================")

if __name__ == "__main__":
    main()
