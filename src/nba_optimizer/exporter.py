import argparse
import os
import traceback
from datetime import datetime

import pandas as pd

from .config import Config, ROSTER_SLOTS
from .utils import get_latest_file, read_ragged_csv


def run(cfg: Config):
    print("Starting NBA DFS Entry Export...")

    try:
        # 1. Load the entire template using the robust utility function
        df_entries, valid_cols = read_ragged_csv(cfg.entries_path)

        # Filter back to just the valid entry columns
        df_entries = df_entries[valid_cols]

        # 2. Identify Valid Entry Rows
        valid_mask = df_entries["Entry ID"].notna()
        entry_count = valid_mask.sum()
        print(f"Detected {entry_count} valid entry slots.")

        # 3. Load latest ranked lineups
        ranked_file = get_latest_file(cfg.ranked_lineup_dir, "ranked-lineups-*.csv")
        print(f"Using ranked lineups from: {os.path.basename(ranked_file)}")
        df_ranked = pd.read_csv(ranked_file)

        if len(df_ranked) < entry_count:
            print(
                f"Warning: Only {len(df_ranked)} lineups available for {entry_count} slots."
            )
            fill_count = len(df_ranked)
        else:
            fill_count = entry_count

        # 4. Map lineups to entry slots
        slots = ROSTER_SLOTS

        # Explicitly cast columns to object to ensure string assignment works
        for slot in slots:
            if slot in df_entries.columns:
                df_entries[slot] = df_entries[slot].astype("object")

        valid_indices = df_entries.index[valid_mask].tolist()

        for i in range(fill_count):
            target_idx = valid_indices[i]
            for slot in slots:
                df_entries.loc[target_idx, slot] = df_ranked.loc[i, slot]

        # 5. Save the combined file
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(
            cfg.output_dir, f"upload-ready-DKEntries-{timestamp}.csv"
        )

        # Write updated entries
        df_entries.to_csv(output_file, index=False, na_rep="")

        print(f"Successfully exported {fill_count} lineups to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


def main():
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Entry Exporter")
    parser.parse_args()

    cfg = load_config_from_env()
    run(cfg)


if __name__ == "__main__":
    main()