import glob
import os
import re
from dataclasses import replace
from datetime import datetime
from typing import Optional

import pandas as pd

from . import assembler, engine, exporter, exposure_report, late_swapper, ranker, records
from .config import load_config_from_env
from .settings import find_record, latest_record_path, resolve_settings, stages_between, warn_ignored
from .slate import PRE_L0_ENTRIES, SLATE_FILE, load_or_write_slate, lock_or_none
from .utils import get_latest_file, merge_player_pool, parse_dk_entries

PROJS_TIME_RE = re.compile(r"NBA-Projs-(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")


def _snapshot_projections(projs_file, slate, slate_dir, run_time):
    """Copy the projections into the slate folder as O-0 does; return the path to use."""
    if not slate_dir:
        return projs_file
    lock = lock_or_none(slate, run_time)
    projs_copy = records.snapshot_input(
        projs_file, slate_dir, records.projections_copy_name(projs_file, lock)
    )
    return os.path.join(slate_dir, projs_copy)


def slate_finished(slate: Optional[dict], run_time: datetime) -> bool:
    """True once the slate's last lock has passed."""
    return bool(slate) and lock_or_none(slate, run_time) is None


def latest_l0_projections(slate_dir: str) -> str:
    """The slate folder's newest L0 projections copy: the last export before lock 0."""
    copies = glob.glob(os.path.join(slate_dir, "L0-NBA-Projs-*.csv"))
    if not copies:
        raise FileNotFoundError(f"past slate: no L0-NBA-Projs-*.csv copy in {slate_dir}")
    return max(copies, key=_export_time)


def _export_time(path: str) -> datetime:
    """The export time in an ``L0-NBA-Projs-YYYY-MM-DD_HH-MM-SS`` name, else the modified time.

    The name survives a copy that drops modified times (a Drive web download, a plain cp).
    """
    match = PROJS_TIME_RE.search(os.path.basename(path))
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%S")
    return datetime.fromtimestamp(os.path.getmtime(path))


def _newest_projections(config, slate, slate_dir, run_time, with_projections, rerank):
    """Projections for the run, or None when none are wanted.

    Normally a snapshot of the newest export in projs_dir. On a finished
    slate the newest export belongs to another slate, so a re-rank gets None
    (it uses the parent run's projections, R2) and a full run uses the
    folder's newest L0 copy, keeping a regenerated pool to pre-lock-0 numbers.
    """
    if not with_projections:
        return None
    if slate_dir and slate_finished(slate, run_time):
        if rerank:
            return None
        projs_file = latest_l0_projections(slate_dir)
        print(f"past slate: using {os.path.basename(projs_file)}, the slate's last L0 projections")
        records.check_blend(pd.read_csv(projs_file))
        return projs_file
    source_projs = get_latest_file(config.projs_dir, "NBA-Projs-*.csv")
    projs_file = _snapshot_projections(source_projs, slate, slate_dir, run_time)
    records.check_blend(pd.read_csv(projs_file))
    return projs_file


def prepare_slate_inputs(config, run_time, with_projections=True, rerank=False):
    """Resolve tonight's slate and copy the run's inputs into its folder.

    Returns (config, slate, projs_file, slate_dir). With NBA_DATA_ROOT set,
    the returned config reads its DKEntries from the slate-folder copy and
    writes pools and ranked files to the slate folder; without it, config is
    unchanged, the slate is built in memory (or None) and slate_dir is None.
    Without *with_projections* (a run starting at assemble or export) no
    projections are copied and projs_file is None; for a finished slate see
    _newest_projections.
    """
    slate, slate_dir = load_or_write_slate(config, config.entries_path)

    if slate_dir:
        # lock is None after the last lock: copies are named "Post-..." and
        # the exporter writes no entry set (see exporter.write_export_entry_set).
        lock = lock_or_none(slate, run_time)
        entries_name = PRE_L0_ENTRIES if lock == 0 else f"{records.lock_prefix(lock)}-DKEntries.csv"
        entries_copy = records.snapshot_input(config.entries_path, slate_dir, entries_name)
        config = replace(
            config,
            entries_path=os.path.join(slate_dir, entries_copy),
            lineup_pool_dir=slate_dir,
            ranked_lineup_dir=slate_dir,
        )

    projs_file = _newest_projections(config, slate, slate_dir, run_time, with_projections, rerank)
    return config, slate, projs_file, slate_dir


def use_slate_dir(config, slate_dir, run_time, with_projections=True, rerank=False):
    """Like prepare_slate_inputs for an existing slate folder (``--slate-dir``).

    Uses the folder's Pre-L0-DKEntries.csv and slate.json; nothing but the
    projections (when needed) is copied in.
    """
    slate_dir = os.path.abspath(slate_dir)
    slate_path = os.path.join(slate_dir, SLATE_FILE)
    entries = os.path.join(slate_dir, PRE_L0_ENTRIES)
    for path in (slate_path, entries):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{os.path.basename(path)} not found in {slate_dir}")
    slate = records.read_json(slate_path)
    config = replace(config, entries_path=entries, lineup_pool_dir=slate_dir, ranked_lineup_dir=slate_dir)
    projs_file = _newest_projections(config, slate, slate_dir, run_time, with_projections, rerank)
    return config, slate, projs_file, slate_dir


def parent_projections(config, record_dir: str, parent_record: dict) -> str:
    """The parent run's projections copy, for a re-rank on a finished slate (R2)."""
    recorded = (parent_record or {}).get("inputs", {}).get("projections", {})
    name = recorded.get("file")
    if not name:
        raise FileNotFoundError("past slate: the parent run record names no projections file")
    for directory in (record_dir, config.projs_dir):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            if recorded.get("sha256") and records.sha256_file(path) != recorded["sha256"]:
                print(f"Warning: {name} has changed since the parent run")
            return path
    raise FileNotFoundError(f"past slate: the parent run's projections {name} not found in {record_dir}")


def _arg(args, name, default=None):
    return getattr(args, name, default)


def find_input(config, args, from_stage: str, record_dir: str, legacy: bool):
    """(path, run record or None) of the artifact a ``--from`` stage starts from (§3.2)."""
    stage, key, explicit, directory, pattern = {
        "rank": ("rank", "pool_file", "pool", config.lineup_pool_dir, "lineup-pool-*.csv"),
        "assemble": ("rank", "ranked_file", "ranked", config.ranked_lineup_dir, "ranked-lineups-*.csv"),
        "export": ("assemble", "assembled_file", "assembled", config.ranked_lineup_dir, "assembled-lineups-*.csv"),
    }[from_stage]

    path = _arg(args, explicit)
    if path:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"--{explicit} file not found: {path}")
        return path, find_record(record_dir, stage, key, os.path.basename(path))

    rec_path = latest_record_path(record_dir, stage)
    if rec_path:
        rec = records.read_json(rec_path)
        if rec.get(key):
            candidate = os.path.join(directory, rec[key])
            if os.path.isfile(candidate):
                return candidate, rec
    if legacy:
        try:
            path = get_latest_file(directory, pattern)
            return path, find_record(record_dir, stage, key, os.path.basename(path))
        except FileNotFoundError:
            pass
    what = {"rank": "lineup pool", "assemble": "ranked file", "export": "assembly"}[from_stage]
    raise FileNotFoundError(f"--from {from_stage}: no {what} found in {record_dir}")


def _print_projections_rule(projs_file: str, parent_record: Optional[dict]) -> None:
    parent = (parent_record or {}).get("inputs", {}).get("projections", {})
    if not parent:
        print(f"Projections: {os.path.basename(projs_file)} (newest export)")
        return
    same = parent.get("sha256") == records.sha256_file(projs_file)
    note = "same as the parent run's" if same else f"newer than the parent run's {parent.get('file')}"
    print(f"Projections: {os.path.basename(projs_file)} ({note})")


def _assembly_ranked_file(assembled_file: str) -> Optional[str]:
    path = os.path.splitext(assembled_file)[0] + ".json"
    if not os.path.isfile(path):
        return None
    name = records.read_json(path).get("ranked_file")
    return os.path.join(os.path.dirname(os.path.abspath(assembled_file)), name) if name else None


def run_pipeline(args, run_time: Optional[datetime] = None):
    """Run the stages generate -> rank -> assemble -> export between --from and --to.

    *args* may be any namespace with the cli.add_pipeline_args fields;
    missing ones take their defaults, so a GUI can call this directly.
    """
    from .cli import pipeline_defaults

    # Load base configuration from environment
    config = load_config_from_env()

    # Override configuration with CLI arguments
    config = replace(
        config,
        min_salary=_arg(args, "min_salary", config.min_salary),
        min_projection=_arg(args, "min_projection", config.min_projection),
        slate_type=_arg(args, "slate_type", "main"),
        seed=_arg(args, "seed"),
    )

    if _arg(args, "late_swap"):
        print("\n=== RUNNING LATE SWAP RE-OPTIMIZATION ===")
        late_swapper.run(config)
        print("\n===========================================")
        print("Late Swap Complete!")
        print("Check your exports/ folder for the 'late-swap-entries' file.")
        print("===========================================")
        return

    defaults = pipeline_defaults()
    from_stage = _arg(args, "from_stage") or "generate"
    to_stage = _arg(args, "to_stage") or "export"
    # One instant supplies every stage's filenames, generated_at and the run ID.
    run_time = (run_time or datetime.now()).astimezone().replace(microsecond=0)
    try:
        stages = stages_between(from_stage, to_stage)
        if _arg(args, "no_slate_folder"):
            if _arg(args, "slate_dir"):
                raise ValueError("--no-slate-folder can't be combined with --slate-dir")
            # This run only: the legacy exports layout, nothing read from or written to the slates folder.
            config = replace(config, data_root="")
            print("No slate folder: using the legacy exports layout for this run.")
        with_projections = from_stage in ("generate", "rank")
        rerank = from_stage == "rank"
        if _arg(args, "slate_dir"):
            config, slate, projs_file, slate_dir = use_slate_dir(
                config, _arg(args, "slate_dir"), run_time, with_projections, rerank=rerank
            )
        else:
            config, slate, projs_file, slate_dir = prepare_slate_inputs(
                config, run_time, with_projections, rerank=rerank
            )
        legacy = slate_dir is None
        record_dir = slate_dir or config.ranked_lineup_dir
        warn_ignored(args, stages, defaults)

        pool_file = ranked_file = assembled_file = None
        parent_record = None
        if rerank:
            pool_file, parent_record = find_input(config, args, "rank", record_dir, legacy)
            # {} still marks a re-rank: engine params unknown, recorded as null.
            parent_record = parent_record or {}
            print(f"Pool: {os.path.basename(pool_file)}")
            if projs_file is None:
                # Finished slate: the newest export is another slate's (R2).
                projs_file = parent_projections(config, record_dir, parent_record)
                print(f"past slate: using {os.path.basename(projs_file)} from the parent run")
            else:
                _print_projections_rule(projs_file, parent_record)
        elif from_stage == "assemble":
            ranked_file, _ = find_input(config, args, "assemble", record_dir, legacy)
        elif from_stage == "export":
            assembled_file, _ = find_input(config, args, "export", record_dir, legacy)

        df_players = parse_dk_entries(config.entries_path)
        if with_projections:
            df_players = merge_player_pool(df_players, pd.read_csv(projs_file), how="inner")
        n_entries = len(records.read_lineup_file(config.entries_path)) if "assemble" in stages else None
        eff = resolve_settings(args, config, record_dir, stages, df_players, n_entries)
        if eff.caps is not None:
            # Out-of-range values fail now, not after generate and rank.
            assembler.validate_settings(eff.caps)
    except (ValueError, KeyError, OSError) as e:
        # OSError covers FileNotFoundError and a Drive-locked copy (PermissionError).
        print(f"Error: {e}")
        return
    slate_date = slate["slate_date"] if slate else None

    if "generate" in stages:
        print("\n--- Phase 1: Generating Lineups ---")
        pool_file = engine.run(
            config,
            num_lineups=_arg(args, "num_lineups", defaults["num_lineups"]),
            randomness=_arg(args, "randomness", defaults["randomness"]),
            min_unique=_arg(args, "min_unique", defaults["min_unique"]),
            projs_file=projs_file,
            run_time=run_time,
            slate_date=slate_date,
            overrides=eff.overrides,
        )
        if not pool_file:
            print("Error: Lineup generation failed. Aborting pipeline.")
            return

    if "rank" in stages:
        print("\n--- Phase 2: Ranking Lineups ---")
        ranked_file = ranker.run(
            config,
            proj_weight=eff.weights["proj"],
            own_weight=eff.weights["own"],
            geo_weight=eff.weights["geo"],
            lineup_file=pool_file,
            projs_file=projs_file,
            num_lineups=_arg(args, "num_lineups", defaults["num_lineups"]),
            randomness=_arg(args, "randomness", defaults["randomness"]),
            min_unique=_arg(args, "min_unique", defaults["min_unique"]),
            base_seed=config.seed,
            slate=slate,
            run_time=run_time,
            overrides=eff.overrides,
            parent_record=parent_record,
            inherited=eff.rank_inherited,
        )
        if not ranked_file:
            print("Error: Lineup ranking failed. Aborting pipeline.")
            return

    if "assemble" in stages:
        print("\n--- Phase 3: Assembling Entries ---")
        try:
            assembled_file = assembler.run(
                config, ranked_file, eff.caps, run_time=run_time, slate=slate,
                inherited=eff.assemble_inherited,
            )
        except (ValueError, OSError) as e:
            print(f"Error: {e}")
            print("Nothing written. Aborting pipeline.")
            return

    if "export" in stages:
        print("\n--- Phase 4: Exporting to DraftKings CSV ---")
        export_file = exporter.run(config, assembled_file=assembled_file, run_time=run_time)
        if not export_file:
            print("Error: Export failed. Aborting pipeline.")
            return

        print("\n--- Phase 5: Generating Exposure Report ---")
        ranked_for_export = ranked_file or _assembly_ranked_file(assembled_file)
        df_effective = None
        if ranked_for_export:
            try:
                df_effective = ranker.effective_player_table(config, ranked_for_export)
            except (ValueError, KeyError, OSError) as e:
                print(f"Warning: exposure report uses the latest projections ({e})")
        exposure_report.run(
            config,
            top_x=_arg(args, "top_x", defaults["top_x"]),
            entries_file=export_file,
            df_players=df_effective,
        )

    print("\n=================================================================")
    if to_stage == "export":
        print("Optimization Pipeline Complete!")
        print("Check your exports folder for the 'upload-ready-DKEntries' file.")
    else:
        print(f"Stopped after {to_stage} (--to {to_stage}); nothing exported.")
    print("=================================================================")
