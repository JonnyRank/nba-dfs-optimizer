import argparse
import glob
import os
import re

import pandas as pd

from .config import Config, ROSTER_SLOTS
from .utils import get_latest_file


def run(cfg: Config, top_x: int = 0):
    try:
        # 1. Locate latest files
        entries_file = get_latest_file(cfg.output_dir, "upload-ready-DKEntries-*", use_mtime=True)
        projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*", use_mtime=True)

        # 2. Parse Projections for Ownership
        df_projs = pd.read_csv(projs_file)
        df_projs["ID"] = df_projs["ID"].astype(str)
        # Create a dictionary mapping ID to Projected Ownership
        own_dict = df_projs.set_index("ID")["Own_Proj"].to_dict()

        # 3. Parse Exported Entries
        # Read headers first to handle ragged CSV rows safely
        header_df = pd.read_csv(entries_file, nrows=0)
        valid_cols = header_df.columns.tolist()
        df_entries = pd.read_csv(entries_file, usecols=valid_cols, dtype=str)

        # Filter to valid entry rows
        df_entries = df_entries[df_entries["Entry ID"].notna()]
        total_lineups = len(df_entries)

        if total_lineups == 0:
            print("No valid lineups found in the latest export.")
            return

        # 4. Extract Players from Slots
        slots = ROSTER_SLOTS
        all_players = []

        for slot in slots:
            if slot in df_entries.columns:
                all_players.extend(df_entries[slot].dropna().tolist())

        # 5. Calculate Exposures
        exposure_counts = pd.Series(all_players).value_counts()

        report_data = []
        for player_str, count in exposure_counts.items():
            # Extract ID from string like "Giannis Antetokounmpo (42062851) (LOCKED)"
            id_match = re.search(r"\((\d+)\)", str(player_str))
            player_id = id_match.group(1) if id_match else None

            # Clean up name for display
            name = re.sub(r"\s*\(\d+\).*$", "", str(player_str))

            exposure_pct = (count / total_lineups) * 100
            own_pct = own_dict.get(player_id, 0.0) if player_id else 0.0
            leverage = exposure_pct - own_pct

            report_data.append(
                {
                    "Player": name,
                    "Exposure %": exposure_pct,
                    "Proj Own %": own_pct,
                    "Leverage": leverage,
                }
            )

        df_report = pd.DataFrame(report_data)
        df_report = df_report.sort_values(by="Exposure %", ascending=False).reset_index(
            drop=True
        )

        # 6. Display Output
        print("--- Entry Exposures ---")
        print(f"Total Lineups: {total_lineups}")
        print(f"Source: {os.path.basename(entries_file)}")

        # Format columns for readability
        formatters = {
            "Exposure %": "{:.1f}%".format,
            "Proj Own %": "{:.1f}%".format,
            "Leverage": "{:+.1f}".format,
        }

        display_df = df_report.copy()
        for col, fmt in formatters.items():
            display_df[col] = display_df[col].apply(fmt)

        if top_x > 0:
            print(display_df.head(top_x).to_string(index=False))
        else:
            print(display_df.to_string(index=False))

    except Exception as e:
        print(f"Failed to generate exposure report: {e}")


def main():
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Exposure Report")
    parser.add_argument(
        "-t",
        "--top_x",
        type=int,
        default=0,
        help="Limit display to top X highest-exposed players. Use 0 for all.",
    )
    args = parser.parse_args()

    cfg = load_config_from_env()
    run(cfg, args.top_x)


if __name__ == "__main__":
    main()
