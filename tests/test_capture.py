"""nba-dfs-capture finalize/record against the real 2026-10-20 night.

That night: L0 was the optimizer's upload before BOS@DET (3:00 PM ET); L1
and L2 were Stokastic late swaps before PHI@NYK (7:00) and OKC@SAS (9:30).
DK accepted every upload exactly, so the chain verifies 40/40 at each lock.
"""

import csv
import os
import shutil
from datetime import datetime

import pandas as pd
import pytest

from nba_optimizer import capture, records

from conftest import set_mtime

SLATE_ID = "2026-10-20_classic_main"
NEXT_MORNING = datetime.fromisoformat("2026-10-21T09:00:00-05:00")


def _finalize(sweep, slate_dir, **kwargs):
    return capture.finalize(
        str(slate_dir),
        [str(sweep)],
        entries=str(sweep / "Pre-L0-DKEntries.csv"),
        assume_default_params=True,
        now=NEXT_MORNING,
        **kwargs,
    )


def _assignment(payload, name):
    matches = [a for a in payload["assignments"] if os.path.basename(a["file"]) == name]
    assert len(matches) == 1, name
    return matches[0]


def _rewrite_rows(src, dest, edit):
    with open(src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    edit(rows)
    with open(dest, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)


def test_assign_by_mtime_opening_night(opening_night, tmp_path):
    """Dry run: each file lands in its lock window; nothing is copied or written."""
    slate_dir = tmp_path / "slates" / SLATE_ID
    payload = _finalize(opening_night, slate_dir, dry_run=True)

    def role_lock(name):
        a = _assignment(payload, name)
        return a["role"], a["lock"], a["used"]

    assert role_lock("L0-NBA-Projs-2026-10-20_13-55-35.csv") == ("projs_basic", 0, True)
    assert role_lock("L1-NBA-Projs-2026-10-20_17-55-17.csv") == ("projs_basic", 1, True)
    assert role_lock("L2-NBA-Projs-2026-10-20_20-28-20.csv") == ("projs_basic", 2, True)
    assert role_lock("L1-DK_NBA_Main_Late_Swap_Lineups.csv") == ("stok_export", 1, True)
    assert role_lock("L2-DK_NBA_Main_Late_Swap_Lineups.csv") == ("stok_export", 2, True)
    assert role_lock("upload-ready-DKEntries-2026-10-20_135723.csv") == ("upload_candidate", 0, True)

    template = _assignment(payload, "NBA-Projs-Template-26-27-WIP_2026-10-20_21-44-33.csv")
    assert template["used"] is False and template["reason"] == "modified after the last lock"

    # Post-L0 (18:05 CT) and Post-L1 (19:33 CT) were downloaded after lock 1 (18:00 CT).
    for name in ("Post-L0-DKEntries.csv", "Post-L1-DKEntries.csv"):
        assert role_lock(name)[:2] == ("midnight", 2)
    assert [m["after_lock"] for m in payload["midnight_checks"]] == [1, 1]

    assert _assignment(payload, "Post-L2-DKEntries.csv")["role"] == "final"
    assert not slate_dir.exists()


def test_finalize_opening_night(opening_night, tmp_path):
    """Every lock is in force 40/40 and the final DK state equals L2."""
    slate_dir = tmp_path / "slates" / SLATE_ID
    payload = _finalize(opening_night, slate_dir)

    assert [(c["lock"], c["status"], c["verified_entries"]) for c in payload["chain"]] == [
        (0, "in_force", 40), (1, "in_force", 40), (2, "in_force", 40),
    ]
    assert payload["final_matches_last"] == 40
    assert payload["mismatches"] == []
    assert payload["unique_lineups_by_lock"] == {0: 40, 1: 40, 2: 40}
    assert payload["changed_vs_previous"] == {1: 27, 2: 11}
    assert [(m["verified"], m["entries"]) for m in payload["midnight_checks"]] == [(40, 40), (40, 40)]

    sources = {es["lock"]: es["source"] for es in payload["entry_sets"]}
    assert sources == {0: "optimizer", 1: "stokastic", 2: "stokastic"}
    l0 = next(es for es in payload["entry_sets"] if es["lock"] == 0)
    assert l0["run_id"] == records.read_json(
        str(slate_dir / "ranked-lineups-2026-10-20_135723.json"))["run_id"]

    df = pd.read_csv(slate_dir / "slate-entries.csv")
    assert len(df) == 3 * 40 * 8
    assert df.groupby("lock")["lineup_changed"].sum().div(8).tolist() == [0, 27, 11]

    for name in ("slate.json", "Pre-L0-DKEntries.csv", "Final-DKEntries.csv", "finalize.json",
                 "L1-DK_NBA_Main_Late_Swap_Lineups.csv", "L2-NBA-Projs-2026-10-20_20-28-20.csv"):
        assert (slate_dir / name).is_file(), name

    run = records.read_json(str(slate_dir / "ranked-lineups-2026-10-20_135723.json"))
    assert run["params_source"] == "reconstructed"
    assert run["params"]["base_seed"] is None
    assert run["inputs"]["projections"]["file"] == "L0-NBA-Projs-2026-10-20_13-55-35.csv"


def test_finalize_idempotent(opening_night, tmp_path):
    """A second finalize rewrites identical records and copies nothing new."""
    slate_dir = tmp_path / "slates" / SLATE_ID
    _finalize(opening_night, slate_dir)
    first = {n: (slate_dir / n).read_bytes() for n in os.listdir(slate_dir)}
    _finalize(opening_night, slate_dir)
    second = {n: (slate_dir / n).read_bytes() for n in os.listdir(slate_dir)}
    assert sorted(second) == sorted(first)
    assert second == first


def test_finalize_without_final_records_unverified(opening_night, tmp_path):
    """No final DKEntries: entry sets are kept as 'recorded' with a warning."""
    os.remove(opening_night / "Post-L2-DKEntries.csv")
    payload = _finalize(opening_night, tmp_path / "slates" / SLATE_ID)
    assert {es["status"] for es in payload["entry_sets"]} == {"recorded"}
    assert any("not verified" in w for w in payload["warnings"])


def test_finalize_ignores_other_slate(opening_night, tmp_path):
    """A Stok export whose entry IDs aren't tonight's is listed and ignored."""
    other = opening_night / "DK_NBA_Main_Late_Swap_Lineups (1).csv"

    def renumber(rows):
        for row in rows[1:]:
            row[0] = str(int(row[0]) + 10_000_000)

    _rewrite_rows(opening_night / "L2-DK_NBA_Main_Late_Swap_Lineups.csv", other, renumber)
    set_mtime(str(other), "2026-10-20T20:29:55-05:00")

    payload = _finalize(opening_night, tmp_path / "slates" / SLATE_ID)
    a = _assignment(payload, other.name)
    assert a["used"] is False and "other slate" in a["reason"]
    assert [c["status"] for c in payload["chain"]] == ["in_force"] * 3
    assert len([es for es in payload["entry_sets"] if es["lock"] == 2]) == 1


def _expanded_export(src_template, dest, bump):
    df = pd.read_csv(src_template)
    df.loc[0, "Own_Proj"] = df.loc[0, "Own_Proj"] + bump  # distinct contents; blend still holds
    df.to_csv(dest, index=False)


def test_projections_closest_to_lock(opening_night, tmp_path):
    """chain[2] takes the last export before lock 2; the L2 swap records the one before the Stok file."""
    template = opening_night / "NBA-Projs-Template-26-27-WIP_2026-10-20_21-44-33.csv"
    os.remove(opening_night / "L2-NBA-Projs-2026-10-20_20-28-20.csv")
    names = {}
    for i, hhmm in enumerate(("20-05", "20-15", "20-25")):
        name = f"NBA-Projs-Template-26-27-WIP_2026-10-20_{hhmm}-00.csv"
        _expanded_export(template, opening_night / name, i + 1)
        set_mtime(str(opening_night / name), f"2026-10-20T{hhmm.replace('-', ':')}:00-05:00")
        names[hhmm] = name
    set_mtime(str(opening_night / "L2-DK_NBA_Main_Late_Swap_Lineups.csv"), "2026-10-20T20:20:00-05:00")

    slate_dir = tmp_path / "slates" / SLATE_ID
    payload = _finalize(opening_night, slate_dir)

    assert payload["chain"][2]["projections_file"] == "L2-NBA-Projs-2026-10-20_20-25-00.csv"
    l2 = next(es for es in payload["entry_sets"] if es["lock"] == 2)
    assert l2["projections_file"] == "L2-NBA-Projs-2026-10-20_20-15-00.csv"
    ignored = _assignment(payload, names["20-05"])
    assert ignored["used"] is False and ignored["lock"] == 2
    assert not (slate_dir / "L2-NBA-Projs-2026-10-20_20-05-00.csv").exists()


def test_projections_carry_forward_when_window_empty(opening_night, tmp_path):
    os.remove(opening_night / "L1-NBA-Projs-2026-10-20_17-55-17.csv")
    payload = _finalize(opening_night, tmp_path / "slates" / SLATE_ID)
    assert payload["chain"][1]["projections_file"] == payload["chain"][0]["projections_file"]
    assert any("no projections export before lock 1" in w for w in payload["warnings"])


def test_record_rejects_locked_change(opening_night, tmp_path):
    """An L1 file that swaps out a BOS@DET player (locked at lock 0) can't be what DK accepted."""
    slate_dir = tmp_path / "slates" / SLATE_ID
    ctx = capture.load_context(str(slate_dir), entries=str(opening_night / "Pre-L0-DKEntries.csv"))
    capture.record(str(opening_night / "upload-ready-DKEntries-2026-10-20_135723.csv"), str(slate_dir), lock=0)

    stok = opening_night / "L1-DK_NBA_Main_Late_Swap_Lineups.csv"
    df = records.read_lineup_file(str(stok))
    row = df.iloc[0]
    slot = next(s for s in ("PG", "SG", "SF", "PF", "C", "G", "F") if ctx.player_lock[int(row[s])] == 0)
    in_lineup = {int(row[s]) for s in ("PG", "SG", "SF", "PF", "C", "G", "F", "UTIL")}
    replacement = next(p for p, k in ctx.player_lock.items() if k == 0 and p not in in_lineup)
    altered = tmp_path / "L1-altered.csv"

    def alter(rows):
        idx = 4 + ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"].index(slot)
        rows[1][idx] = f"Someone Else ({replacement})"

    _rewrite_rows(stok, altered, alter)
    with pytest.raises(ValueError, match=rf"entry {row['entry_id']} slot {slot}: locked player changed"):
        capture.record(str(altered), str(slate_dir), lock=1)

    # The unaltered export is accepted and pinned.
    assert capture.record(str(stok), str(slate_dir), lock=1) == "L1-DK_NBA_Main_Late_Swap_Lineups.csv"
    assert records.read_json(str(slate_dir / "pins.json"))["entry_sets"].keys() == {"0", "1"}
    shutil.rmtree(slate_dir)


def test_same_export_resaved_after_lock_counts_in_both_windows(opening_night, tmp_path):
    """An identical re-export after lock 0 doesn't hide the pre-lock export from lock 0."""
    resaved = opening_night / "NBA-Projs-2026-10-20_14-06-47.csv"
    shutil.copy(opening_night / "L0-NBA-Projs-2026-10-20_13-55-35.csv", resaved)
    set_mtime(str(resaved), "2026-10-20T14:06:47-05:00")

    payload = _finalize(opening_night, tmp_path / "slates" / SLATE_ID)

    l0 = _assignment(payload, "L0-NBA-Projs-2026-10-20_13-55-35.csv")
    assert (l0["lock"], l0["used"]) == (0, True)
    assert payload["chain"][0]["projections_file"] == "L0-NBA-Projs-2026-10-20_13-55-35.csv"
    assert _assignment(payload, resaved.name)["lock"] == 1
