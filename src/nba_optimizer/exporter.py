import argparse
import os
import traceback
from datetime import datetime
from typing import Optional

import pandas as pd

from . import records
from .assembler import _player_sets, unique_survivors
from .config import Config, ROSTER_SLOTS, STANDARD_EXPORT_PREFIX
from .utils import get_latest_file, read_ragged_csv


def run(
    cfg: Config,
    assembled_file: Optional[str] = None,
    ranked_file: Optional[str] = None,
    run_time: Optional[datetime] = None,
) -> str:
    """Export lineups into a DraftKings-compatible CSV.

    With *assembled_file* the DKEntries rows are filled in its Entry_Order;
    otherwise with the top-ranked lineups of *ranked_file*. After the CSV,
    writes the L0 entry-set candidate for a pre-lock run. When the ranked
    file sits in a slate folder (it has a slate.json), the upload-ready CSV
    is copied there and the entry set is written there; otherwise the entry
    set goes next to the CSV.

    Args:
        cfg: Pipeline configuration.
        assembled_file: An ``assembled-lineups-*.csv`` (O-13); wins over
            *ranked_file*, which is then read from its record.
        ranked_file: Explicit path to a ranked-lineups CSV. When neither is
            given, the most recent file in ``cfg.ranked_lineup_dir`` is used
            (standalone fallback behaviour).
        run_time: The run's instant, shared by every stage's filenames.

    Returns:
        Path to the written export CSV, or an empty string if the run failed
        before producing output.
    """
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

        # 3. Load lineups — an assembly in entry order, else the ranked file's
        #    top rows (explicit path, or latest-file discovery when standalone).
        assembly = {}
        if assembled_file:
            assembly = _read_assembly_record(assembled_file)
            if assembly.get("ranked_file"):
                ranked_file = os.path.join(os.path.dirname(os.path.abspath(assembled_file)), assembly["ranked_file"])
            print(f"Using assembled lineups from: {os.path.basename(assembled_file)}")
            df_ranked = pd.read_csv(assembled_file).sort_values("Entry_Order").reset_index(drop=True)
        else:
            if not ranked_file:
                ranked_file = get_latest_file(cfg.ranked_lineup_dir, "ranked-lineups-*.csv")
            print(f"Using ranked lineups from: {os.path.basename(ranked_file)}")
            df_ranked = pd.read_csv(ranked_file).sort_values("Final_Rank", kind="stable").reset_index(drop=True)
            # The pool keeps exact duplicates (O-14) and -u normally applies at
            # assemble; without an assembly, still never upload the same lineup twice.
            keep = unique_survivors(_player_sets(df_ranked), Config.min_unique)
            if len(keep) < len(df_ranked):
                print(f"No assembly: removed {len(df_ranked) - len(keep)} exact duplicates "
                      f"(min_unique {Config.min_unique})")
                df_ranked = df_ranked.iloc[keep].reset_index(drop=True)

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
        run_time = (run_time or datetime.now()).astimezone()
        run_record = _read_run_record(ranked_file) if ranked_file else {}
        slate_id = run_record.get("slate_id") or assembly.get("slate_id")
        slate_date = slate_id[:10] if slate_id else run_time.strftime("%Y-%m-%d")
        # Same "<Type>-" prefix as the ranked file on non-main slates (slate_id ends in _classic_<type>).
        slate_type = slate_id.rsplit("_", 1)[-1] if slate_id else "main"
        type_part = "" if slate_type == "main" else f"{slate_type.capitalize()}-"
        timestamp = f"{type_part}{slate_date}_{run_time.strftime('%H%M%S')}"
        output_file = os.path.join(
            cfg.output_dir, f"{STANDARD_EXPORT_PREFIX}-{timestamp}.csv"
        )

        # Write updated entries
        df_entries.to_csv(output_file, index=False, na_rep="")

        print(f"Successfully exported {fill_count} lineups to {output_file}")

        try:
            write_export_entry_set(
                output_file, ranked_file or assembled_file, run_record, run_time,
                assembly_id=assembly.get("assembly_id"),
            )
        except Exception as e:
            print(f"Warning: entry set not written: {e}")
        return output_file

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return ""


def _read_run_record(ranked_file: str) -> dict:
    path = records.run_record_path(ranked_file)
    if not os.path.isfile(path):
        return {}
    try:
        return records.read_json(path)
    except (OSError, ValueError) as e:
        print(f"Warning: couldn't read run record {os.path.basename(path)}: {e}")
        return {}


def _read_assembly_record(assembled_file: str) -> dict:
    path = os.path.splitext(assembled_file)[0] + ".json"
    if not os.path.isfile(path):
        print(f"Warning: no assembly record next to {os.path.basename(assembled_file)}.")
        return {}
    return records.read_json(path)


def write_export_entry_set(
    export_file: str, ranked_file: str, run_record: dict, run_time: datetime,
    assembly_id: Optional[str] = None,
) -> str:
    """Write the optimizer L0 entry-set candidate for *export_file*; return its path.

    The lock is the export's own: from the slate folder's slate.json at
    *run_time* when there is one, else the run record's. Writes nothing
    (returns "") unless that is lock 0: after lock 0, late swaps are captured
    by ``nba-dfs-capture finalize`` / ``record`` (O-13 §3.13); with no slate
    facts (e.g. a mid-night DKEntries in the legacy layout) the lock is unknown.
    """
    from .slate import SLATE_FILE, lock_or_none

    slate_dir = os.path.dirname(os.path.abspath(ranked_file))
    in_slate_dir = os.path.isfile(os.path.join(slate_dir, SLATE_FILE))
    slate = records.read_json(os.path.join(slate_dir, SLATE_FILE)) if in_slate_dir else None
    lock = lock_or_none(slate, run_time) if slate else run_record.get("lock")
    if lock != 0:
        if lock is not None:
            reason = f"run is after lock 0 (before lock {lock})"
        elif slate or run_record.get("slate_id"):
            reason = "run is after the slate's last lock"
        else:
            reason = "no slate facts for this run"
        print(f"Warning: {reason}; no entry set written.")
        if slate or run_record.get("slate_id"):
            print("Reminder: late swaps are captured by nba-dfs-capture finalize / record.")
        return ""

    if slate:
        lineups_file = records.snapshot_input(export_file, slate_dir, os.path.basename(export_file))
        target_dir = slate_dir
        entry_order = slate.get("entry_ids")
    else:
        lineups_file = os.path.basename(export_file)
        target_dir = os.path.dirname(os.path.abspath(export_file))
        entry_order = None

    payload = records.make_entry_set(
        slate_id=run_record.get("slate_id"),
        lock=lock,
        source="optimizer",
        created_at=run_time,
        lineups_file=lineups_file,
        lineups_sha256=records.sha256_file(export_file),
        df_lineups=records.read_lineup_file(export_file),
        projections_file=run_record.get("inputs", {}).get("projections", {}).get("file"),
        run_id=run_record.get("run_id"),
        rank_map=records.rank_map_from_ranked(ranked_file),
        entry_order=entry_order,
        assembly_id=assembly_id,
    )
    path = records.write_entry_set(target_dir, payload)
    print(f"Entry set: {os.path.basename(path)} ({len(payload['entries'])} entries)")
    return path


def main():
    from .config import load_config_from_env

    parser = argparse.ArgumentParser(description="NBA DFS Entry Exporter")
    parser.parse_args()

    cfg = load_config_from_env()
    run(cfg)


if __name__ == "__main__":
    main()