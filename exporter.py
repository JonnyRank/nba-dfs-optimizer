import pandas as pd
import os
import glob
import argparse
import traceback
from datetime import datetime
import config


def get_latest_ranked_file() -> str:
    """Finds the most recent ranked-lineups-*.csv file."""
    files = glob.glob(os.path.join(config.LINEUP_DIR, "ranked-lineups-*.csv"))
    if not files:
        raise FileNotFoundError(f"No ranked lineup files found in {config.LINEUP_DIR}")
    return max(files, key=os.path.basename)


def main():
    parser = argparse.ArgumentParser(description="NBA DFS Entry Exporter")
    parser.parse_args()

    print("Starting NBA DFS Entry Export...")

    try:
        # 1. Load the entire template
        # We read it all at once. Pandas handles the side-by-side structure fine.
        # Force Entry ID and Contest ID to be strings to avoid .0 suffix

        # Fix for ragged CSV (ParserError): Read header first to get valid columns
        header_df = pd.read_csv(config.ENTRIES_PATH, nrows=0)
        valid_cols = header_df.columns.tolist()

        # Use dummy columns to handle the wider rows (player pool) further down in the file
        # We cap this at 25 total columns to save memory
        extra_count = max(0, 25 - len(valid_cols))
        all_cols = valid_cols + [f"extra_{i}" for i in range(extra_count)]

        df_entries = pd.read_csv(
            config.ENTRIES_PATH,
            header=None,
            names=all_cols,
            skiprows=1,
            dtype={"Entry ID": object, "Contest ID": object},
            engine="python",
        )

        # Filter back to just the entry columns
        df_entries = df_entries[valid_cols]

        # 2. Identify Valid Entry Rows
        # Valid rows have a non-empty Entry ID
        valid_mask = df_entries["Entry ID"].notna()
        entry_count = valid_mask.sum()
        print(f"Detected {entry_count} valid entry slots.")

        # 3. Load latest ranked lineups
        ranked_file = get_latest_ranked_file()
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
        slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]

        # Explicitly cast columns to object to ensure string assignment works
        for slot in slots:
            if slot in df_entries.columns:
                df_entries[slot] = df_entries[slot].astype("object")

        # Get indices of valid rows
        valid_indices = df_entries.index[valid_mask].tolist()

        for i in range(fill_count):
            target_idx = valid_indices[i]
            for slot in slots:
                df_entries.loc[target_idx, slot] = df_ranked.loc[i, slot]

        # 5. Save the combined file
        # Append date and time to filename to maintain history (YYYY-MM-DD_HHMMSS)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_file = os.path.join(
            config.OUTPUT_DIR, f"upload_ready_DKEntries-{timestamp}.csv"
        )

        # Write updated entries
        # na_rep='' ensures empty cells are written as empty strings
        df_entries.to_csv(output_file, index=False, na_rep="")

        print(f"Successfully exported {fill_count} lineups to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
