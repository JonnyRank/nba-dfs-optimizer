import subprocess
# import argparse # Replaced with GooeyParser for GUI
import sys
from gooey import Gooey, GooeyParser

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

@Gooey(program_name="Jonny's NBA DFS Optimizer", default_size=(600, 700))
def main():
    # Change argparse.ArgumentParser to GooeyParser
    parser = GooeyParser(description="NBA DFS Optimizer - Main Orchestrator")
    # parser = argparse.ArgumentParser(description="NBA DFS Optimizer - Main Orchestrator")
    
    # Mode Toggle
    parser.add_argument("--late_swap", action="store_true", help="Run late swap re-optimization instead of full generation.")

    # Engine/Late-Swap Arguments
    parser.add_argument("-n", "--num_lineups", type=int, default=2500, help="Number of lineups to generate (Default: 2500)")
    parser.add_argument("-r", "--randomness", type=float, default=0.25, help="Randomness factor 0.0-1.0 (Default: 0.25)")
    parser.add_argument("-u", "--min_unique", type=int, default=1, help="Min unique players between lineups (Default: 1)")
    parser.add_argument("-ms", "--min_salary", type=int, default=49500, help="Min salary for a lineup (Default: 49500)")
    parser.add_argument("-mp", "--min_projection", type=float, default=10.0, help="Min projection for a player to be considered (Default: 10.0)")
    
    # Ranker Arguments
    parser.add_argument("-pw", "--proj_weight", type=float, default=0.8, help="Weight for Projection Rank (Default: 0.8)")
    parser.add_argument("-ow", "--own_weight", type=float, default=0.0, help="Weight for Ownership Rank (Default: 0.0)")
    parser.add_argument("-gw", "--geo_weight", type=float, default=0.2, help="Weight for Geomean Rank (Default: 0.2)")
    
    # Reporting Arguments
    parser.add_argument("-t", "--top_x", type=int, default=25, help="Display only top X exposed players (0 for all)")

    args = parser.parse_args()
    
    python_exe = sys.executable

    if args.late_swap:
        # --- LATE SWAP PIPELINE ---
        print("\n=== RUNNING LATE SWAP RE-OPTIMIZATION ===")
        late_swap_cmd = (
            f'"{python_exe}" late_swapper_v1.1.py '
            f'--min_salary {args.min_salary} '
            f'--min_projection {args.min_projection}'
        )
        run_command(late_swap_cmd, "Late Swap Optimization")
        
        print("\n===========================================")
        print("Late Swap Complete!")
        print("Check your exports/ folder for the 'late-swap-entries' file.")
        print("===========================================")
        return

    # --- DEFAULT PIPELINE ---
    # 1. Run Engine
    engine_cmd = (
        f'"{python_exe}" engine.py '
        f'--num_lineups {args.num_lineups} '
        f'--randomness {args.randomness} '
        f'--min_unique {args.min_unique} '
        f'--min_salary {args.min_salary} '
        f'--min_projection {args.min_projection}'
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
    
    # 4. Run Exposure Report
    report_cmd = f'"{python_exe}" exposure_report.py --top_x {args.top_x}'
    run_command(report_cmd, "Phase 4: Generating Exposure Report")

    print("\n==================================================================")
    print("Optimization Pipeline Complete!")
    print("Check your Downloads folder for the 'upload_ready_DKEntries' file.")
    print("==================================================================")

if __name__ == "__main__":
    main()
