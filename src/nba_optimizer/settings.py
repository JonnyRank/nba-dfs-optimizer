"""Effective settings for stage runs (O-13 §3.3).

Precedence: typed on the command line > inherited from the latest record of
the same stage in the slate folder > Config default. A full run (from
``generate``) never inherits.
"""

import glob
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from . import records
from .assembler import AssembleSettings, fmt_pct
from .config import Config
from .overrides import (
    CARRY_TOL, current_value, fmt_value, parse_assignment, resolve_overrides, resolve_player, split_list,
)

STAGES = ("generate", "rank", "assemble", "export")
RECORD_PATTERNS = {"rank": "ranked-lineups-*.json", "assemble": "assembled-lineups-*.json"}
WEIGHT_NAMES = (("proj_weight", "proj"), ("own_weight", "own"), ("geo_weight", "geo"))

# Flags that only matter when a given stage runs (§6.1). Values are the arg dests.
GENERATE_FLAGS = ("num_lineups", "randomness", "min_unique", "min_salary", "min_projection", "seed")
RANK_FLAGS = ("proj_weight", "own_weight", "geo_weight")
OVERRIDE_FLAGS = ("proj", "own")
CAP_FLAGS = ("max_caps", "min_caps", "max_all", "clear_caps")
EXPORT_FLAGS = ("top_x",)
FLAG_LABELS = {
    "num_lineups": "-n", "randomness": "-r", "min_unique": "-u", "min_salary": "-ms",
    "min_projection": "-mp", "seed": "--seed", "proj_weight": "-pw", "own_weight": "-ow",
    "geo_weight": "-gw", "proj": "--proj", "own": "--own", "max_caps": "--max", "min_caps": "--min",
    "max_all": "--max-all", "clear_caps": "--clear-caps", "clear_overrides": "--clear-overrides",
    "reset_settings": "--reset-settings", "top_x": "-t", "pool": "--pool", "ranked": "--ranked",
    "assembled": "--assembled",
}


@dataclass
class EffectiveSettings:
    weights: Dict[str, float] = field(default_factory=dict)       # proj/own/geo
    overrides: List[dict] = field(default_factory=list)           # {dk_id, name, field, to}
    caps: Optional[AssembleSettings] = None
    rank_inherited: List[str] = field(default_factory=list)
    assemble_inherited: List[str] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)


def stages_between(from_stage: str, to_stage: str) -> List[str]:
    i, j = STAGES.index(from_stage), STAGES.index(to_stage)
    if i > j:
        raise ValueError(f"--from {from_stage} is after --to {to_stage}")
    return list(STAGES[i:j + 1])


def _generated_at(path: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(records.read_json(path)["generated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_paths(directory: Optional[str], stage: str) -> List[str]:
    """Records of *stage* in *directory*, oldest to newest by ``generated_at``."""
    if not directory or not os.path.isdir(directory):
        return []
    found = []
    for path in glob.glob(os.path.join(directory, RECORD_PATTERNS[stage])):
        when = _generated_at(path)
        if when is not None:
            found.append((when, os.path.basename(path), path))
    return [path for _, _, path in sorted(found)]


def latest_record_path(directory: Optional[str], stage: str) -> Optional[str]:
    """Path of the newest record of *stage* in *directory*, by its ``generated_at``."""
    paths = record_paths(directory, stage)
    return paths[-1] if paths else None


def find_record(directory: Optional[str], stage: str, key: str, name: str) -> Optional[dict]:
    """Newest record of *stage* whose *key* is *name* (e.g. the latest run on a given pool)."""
    for path in reversed(record_paths(directory, stage)):
        rec = records.read_json(path)
        if rec.get(key) == name:
            return rec
    return None


def latest_record(slate_dir: Optional[str], stage: str) -> Optional[dict]:
    """``"rank"`` -> newest run record, ``"assemble"`` -> newest assembly record (None if none)."""
    path = latest_record_path(slate_dir, stage)
    return records.read_json(path) if path else None


def _arg(args, name, default=None):
    return getattr(args, name, default)


def _clear_targets(value) -> Optional[List[str]]:
    """None: no clear. []: clear all. Otherwise the named players."""
    if value is None:
        return None
    names = split_list(value)
    if not names or any(n.lower() == "all" for n in names):
        return []
    return names


def _typed(args, name, defaults) -> bool:
    value = _arg(args, name)
    if name in defaults:
        return value is not None and value != defaults[name]
    if isinstance(value, (list, tuple)):
        return bool(split_list(value))
    return value not in (None, False, "")


def warn_ignored(args, stages: List[str], defaults: Dict[str, object]) -> None:
    """Warn about flags that have no effect in the selected stages (§6.1, §6.7)."""
    from_stage = stages[0]
    ignored = []
    if from_stage != "generate":
        ignored += [f for f in GENERATE_FLAGS if _typed(args, f, defaults)]
    if "rank" not in stages:
        ignored += [f for f in RANK_FLAGS if _typed(args, f, defaults)]
    if from_stage not in ("generate", "rank"):
        ignored += [f for f in OVERRIDE_FLAGS + ("clear_overrides",) if _typed(args, f, defaults)]
    elif from_stage == "generate" and _arg(args, "clear_overrides") is not None:
        ignored.append("clear_overrides")
    if "assemble" not in stages:
        ignored += [f for f in CAP_FLAGS if _typed(args, f, defaults)]
    if "export" not in stages:
        ignored += [f for f in EXPORT_FLAGS if _typed(args, f, defaults)]
    if from_stage == "generate" and _arg(args, "reset_settings"):
        ignored.append("reset_settings")
    for flag, stage in (("pool", "rank"), ("ranked", "assemble"), ("assembled", "export")):
        if _arg(args, flag) and from_stage != stage:
            ignored.append(flag)
    for name in ignored:
        why = "the pool already exists" if name in GENERATE_FLAGS else "its stage doesn't run"
        if name == "reset_settings":
            why = "a full run never inherits"
        if name == "clear_overrides" and from_stage == "generate":
            why = "a full run never inherits"
        print(f"Warning: {FLAG_LABELS.get(name, name)} ignored: {why}.")


def _clear_ids(targets: List[str], inherited: Dict[int, str], df_players, what: str) -> set:
    """DK IDs to clear: each name is matched against the inherited entries first
    (so a player missing from tonight's export can still be cleared), then the pool.
    """
    df_inherited = pd.DataFrame({"ID": [str(k) for k in inherited], "Name": list(inherited.values())})
    ids = set()
    for t in targets:
        error = "nothing inherited"
        for df in (df_inherited, df_players):
            if df is None or df.empty:
                continue
            try:
                ids.add(resolve_player(t, df)[0])
                break
            except ValueError as e:
                error = e
        else:
            print(f"Warning: --clear-{what} {t!r} matched no inherited {what} ({error}); nothing cleared for it.")
    return ids


def _src(rec_path: Optional[str]) -> str:
    return f"inherited from {os.path.basename(rec_path)}"


def _resolve_weights(args, cfg: Config, rank_rec, rank_path, out: EffectiveSettings) -> None:
    params = (rank_rec or {}).get("params", {})
    for name, key in WEIGHT_NAMES:
        typed = _arg(args, name)
        if typed is not None:
            value, source = float(typed), "typed"
        elif params.get(name) is not None:
            value, source = float(params[name]), _src(rank_path)
            out.rank_inherited.append(name)
        else:
            value, source = float(getattr(cfg, name)), "default"
        out.weights[key] = value
        out.lines.append(f"  {name} = {fmt_value(value)} ({source})")


def _resolve_overrides(args, df_players, rank_rec, rank_path, out: EffectiveSettings) -> None:
    inherited = [dict(o) for o in (rank_rec or {}).get("overrides") or []]
    targets = _clear_targets(_arg(args, "clear_overrides"))
    if targets == []:
        inherited = []
    elif targets:
        drop = _clear_ids(targets, {int(o["dk_id"]): o["name"] for o in inherited}, df_players, "overrides")
        inherited = [o for o in inherited if int(o["dk_id"]) not in drop]

    kept = {}
    for o in inherited:
        cur = current_value(df_players, o["dk_id"], o["field"])
        if cur is None:
            print(f"Warning: {o['name']} override {fmt_value(o['to'])} dropped: not in the newest export")
        elif abs(cur - float(o["from"])) > CARRY_TOL:
            print(f"Warning: {o['name']} override {fmt_value(o['to'])} dropped: newest export now says {fmt_value(cur)}")
        else:
            kept[(int(o["dk_id"]), o["field"])] = (
                {"dk_id": int(o["dk_id"]), "name": o["name"], "field": o["field"], "to": float(o["to"])},
                _src(rank_path),
            )
    for o in resolve_overrides(df_players, _arg(args, "proj") or [], _arg(args, "own") or []):
        kept[(o["dk_id"], o["field"])] = (o, "typed")

    if any(src != "typed" for _, src in kept.values()):
        out.rank_inherited.append("overrides")
    out.overrides = [o for o, _ in kept.values()]
    if not kept:
        out.lines.append("  overrides: none")
    for o, src in kept.values():
        out.lines.append(f"  override {o['name']} {o['field']} = {fmt_value(o['to'])} ({src})")


def _resolve_caps(args, df_players, n_entries: int, asm_rec, asm_path, out: EffectiveSettings) -> None:
    caps = AssembleSettings(n_entries=n_entries)
    sources: Dict[tuple, str] = {}
    settings = (asm_rec or {}).get("settings", {})
    for kind in ("max", "min"):
        for c in settings.get(kind) or []:
            getattr(caps, kind)[int(c["dk_id"])] = float(c["pct"])
            caps.names[int(c["dk_id"])] = c.get("name") or str(c["dk_id"])
            sources[(kind, int(c["dk_id"]))] = _src(asm_path)
    if settings.get("max_all") is not None:
        caps.max_all = float(settings["max_all"])
        sources[("max_all", None)] = _src(asm_path)

    targets = _clear_targets(_arg(args, "clear_caps"))
    if targets == []:
        caps.max, caps.min, caps.max_all = {}, {}, None
        sources.clear()
    elif targets:
        for dk_id in _clear_ids(targets, {k: caps.names.get(k, str(k)) for k in {**caps.max, **caps.min}},
                                df_players, "caps"):
            caps.max.pop(dk_id, None)
            caps.min.pop(dk_id, None)

    for kind, dest in (("max", "max_caps"), ("min", "min_caps")):
        for text in split_list(_arg(args, dest)):
            token, pct = parse_assignment(text)
            dk_id, name = resolve_player(token, df_players)
            getattr(caps, kind)[dk_id] = pct
            caps.names[dk_id] = name
            sources[(kind, dk_id)] = "typed"
    if _arg(args, "max_all") is not None:
        caps.max_all = float(_arg(args, "max_all"))
        sources[("max_all", None)] = "typed"

    for kind in ("max", "min", "max_all"):
        keys = [k for k in sources if k[0] == kind and k in _live_keys(caps)]
        if any(sources[k] != "typed" for k in keys):
            out.assemble_inherited.append(kind)
    out.caps = caps
    if not (caps.max or caps.min or caps.max_all is not None):
        out.lines.append("  caps: none")
    for kind in ("max", "min"):
        for dk_id, pct in getattr(caps, kind).items():
            out.lines.append(f"  {kind} {caps.names.get(dk_id, dk_id)} = {fmt_pct(pct)}% ({sources[(kind, dk_id)]})")
    if caps.max_all is not None:
        out.lines.append(f"  max_all = {fmt_pct(caps.max_all)}% ({sources[('max_all', None)]})")


def _live_keys(caps: AssembleSettings) -> set:
    keys = {("max", k) for k in caps.max} | {("min", k) for k in caps.min}
    if caps.max_all is not None:
        keys.add(("max_all", None))
    return keys


def resolve_settings(
    args,
    cfg: Config,
    slate_dir: Optional[str],
    stages: Optional[List[str]] = None,
    df_players: Optional[pd.DataFrame] = None,
    n_entries: Optional[int] = None,
) -> EffectiveSettings:
    """Values and sources for every setting the selected stages use; prints the block.

    *slate_dir* is where records are looked up (the slate folder, or the
    ranked-lineups dir in the legacy layout). *df_players* is the merged
    player pool from the newest export (needed for overrides and caps);
    *n_entries* is N for the caps' counts.
    """
    stages = stages or list(STAGES)
    inherit = stages[0] != "generate" and not _arg(args, "reset_settings")
    out = EffectiveSettings()
    rank_path = latest_record_path(slate_dir, "rank") if inherit else None
    rank_rec = records.read_json(rank_path) if rank_path else None

    if "rank" in stages:
        _resolve_weights(args, cfg, rank_rec, rank_path, out)
    if stages[0] in ("generate", "rank") and df_players is not None:
        _resolve_overrides(args, df_players, rank_rec, rank_path, out)
    if "assemble" in stages:
        asm_path = latest_record_path(slate_dir, "assemble") if inherit else None
        asm_rec = records.read_json(asm_path) if asm_path else None
        _resolve_caps(args, df_players, n_entries or 0, asm_rec, asm_path, out)

    print("Effective settings:")
    for line in out.lines or ["  (none for these stages)"]:
        print(line)
    return out
