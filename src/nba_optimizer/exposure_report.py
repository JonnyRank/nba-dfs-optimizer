import argparse
import os
import re

import pandas as pd

from .config import ROSTER_SLOTS, Config
from .utils import get_latest_file


def run(cfg: Config, top_x: int = 25):
    try:
        # 1. Locate latest files
        entries_file = get_latest_file(cfg.output_dir, "upload-ready-DKEntries-*.csv", use_mtime=True)
        projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv", use_mtime=True)

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

        display_df = df_report.head(top_x) if top_x > 0 else df_report

        rows = []
        for _, row in display_df.iterrows():
            rows.append(
                {
                    "Player": row["Player"],
                    "Exposure": f"{row['Exposure %']:.2f}%",
                    "Own Proj": f"{row['Proj Own %']:.2f}%",
                    "Leverage": f"{row['Leverage']:.1f}%",
                }
            )

        name_w = max(len("Player"), max(len(r["Player"]) for r in rows))
        exp_w = max(len("Exposure"), max(len(r["Exposure"]) for r in rows))
        own_w = max(len("Own Proj"), max(len(r["Own Proj"]) for r in rows))
        lev_w = max(len("Leverage"), max(len(r["Leverage"]) for r in rows))

        print(
            f"{'Player':^{name_w}}  {'Exposure':^{exp_w}}  {'Own Proj':^{own_w}}  {'Leverage':^{lev_w}}"
        )
        for r in rows:
            print(
                f"{r['Player']:<{name_w}}  {r['Exposure']:>{exp_w}}  {r['Own Proj']:>{own_w}}  {r['Leverage']:>{lev_w}}"
            )

    except Exception as e:
        print(f"Failed to generate exposure report: {e}")


def main():
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Exposure Report")
    parser.add_argument(
        "-t",
        "--top_x",
        type=int,
        default=25,
        help="Limit display to top X highest-exposed players (Default: 25). Use 0 for all",
    )
    args = parser.parse_args()

    cfg = load_config_from_env()
    run(cfg, args.top_x)


if __name__ == "__main__":
    main()
