"""nba-dfs-capture finalize/record against the real 2026-10-20 night.

That night: L0 was the optimizer's upload before BOS@DET (3:00 PM ET); L1
and L2 were Stokastic late swaps before PHI@NYK (7:00) and OKC@SAS (9:30).
DK accepted every upload exactly, so the chain verifies 40/40 at each lock.
"""

import csv
import os
import shutil
import zipfile
from datetime import datetime

import pandas as pd
import pytest

from nba_optimizer import capture, records
from nba_optimizer import config as config_mod
from nba_optimizer.config import Config
from nba_optimizer.slate import load_or_write_slate

from conftest import make_twin, set_mtime

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
        name = f"NBA-Projs-2026-10-20_10-20_{hhmm}-00.csv"  # NBA-Projs-<slate date>_<MM-DD_HH-MM-SS>
        _expanded_export(template, opening_night / name, i + 1)
        set_mtime(str(opening_night / name), f"2026-10-20T{hhmm.replace('-', ':')}:00-05:00")
        names[hhmm] = name
    set_mtime(str(opening_night / "L2-DK_NBA_Main_Late_Swap_Lineups.csv"), "2026-10-20T20:20:00-05:00")

    slate_dir = tmp_path / "slates" / SLATE_ID
    payload = _finalize(opening_night, slate_dir)

    assert payload["chain"][2]["projections_file"] == "L2-NBA-Projs-2026-10-20_10-20_20-25-00.csv"
    l2 = next(es for es in payload["entry_sets"] if es["lock"] == 2)
    assert l2["projections_file"] == "L2-NBA-Projs-2026-10-20_10-20_20-15-00.csv"
    ignored = _assignment(payload, names["20-05"])
    assert ignored["used"] is False and ignored["lock"] == 2
    assert not (slate_dir / "L2-NBA-Projs-2026-10-20_10-20_20-05-00.csv").exists()


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


def test_record_rejects_out_of_range_lock(opening_night, tmp_path):
    slate_dir = tmp_path / "slates" / SLATE_ID
    capture.load_context(str(slate_dir), entries=str(opening_night / "Pre-L0-DKEntries.csv"))
    with pytest.raises(ValueError, match="out of range"):
        capture.record(str(opening_night / "L1-DK_NBA_Main_Late_Swap_Lineups.csv"), str(slate_dir), lock=7)
    assert not (slate_dir / "pins.json").exists()


def test_record_rejects_other_slate_projections(opening_night, tmp_path):
    slate_dir = tmp_path / "slates" / SLATE_ID
    capture.load_context(str(slate_dir), entries=str(opening_night / "Pre-L0-DKEntries.csv"))
    other = tmp_path / "NBA-Projs-2026-10-21_12-00-00.csv"
    pd.DataFrame({"ID": [1, 2, 3], "Projection": [30.0, 20.0, 10.0], "Own_Proj": [10.0, 5.0, 1.0]}).to_csv(other, index=False)
    with pytest.raises(ValueError, match="don't match this slate"):
        capture.record(str(other), str(slate_dir), lock=1)


def test_record_twice_rewrites_same_entry_set(opening_night, tmp_path):
    """Re-recording a file reuses its copy and entry-set ID (both keyed by contents/mtime)."""
    slate_dir = tmp_path / "slates" / SLATE_ID
    capture.load_context(str(slate_dir), entries=str(opening_night / "Pre-L0-DKEntries.csv"))
    upload = str(opening_night / "upload-ready-DKEntries-2026-10-20_135723.csv")
    capture.record(upload, str(slate_dir), lock=0)
    first = sorted(os.listdir(slate_dir))
    capture.record(upload, str(slate_dir), lock=0)
    assert sorted(os.listdir(slate_dir)) == first
    assert len([n for n in first if "-entry-set-" in n]) == 1


STANDINGS_CSV = b"Rank,EntryId,EntryName,TimeRemaining,Points,Lineup\r\n1,5000000001,someone (1/40),0,312.5,PG A SG B\r\n"
MORNING = "2026-10-21T07:10:44-05:00"


def _standings_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    set_mtime(str(path), MORNING)
    return path


def test_standings_from_zip(opening_night, tmp_path, capsys):
    """Standings zips as DK delivers them: the single CSV is extracted, the zip is left alone."""
    slate_dir = tmp_path / "slates" / SLATE_ID
    good = _standings_zip(opening_night / "contest-standings-196456024.zip",
                          {"contest-standings-196456024.csv": STANDINGS_CSV})
    # The zip's own name doesn't matter; the CSV inside it does.
    # macOS metadata entries don't count as extra files.
    renamed = _standings_zip(opening_night / "standings (1).zip",
                             {"contest-standings-196456031.csv": STANDINGS_CSV + b"2,5000000002,x,0,1,\r\n",
                              "__MACOSX/._contest-standings-196456031.csv": b"meta"})
    other = _standings_zip(opening_night / "contest-standings-999999999.zip",
                           {"contest-standings-999999999.csv": STANDINGS_CSV + b"2,6000000002,y,0,1,\r\n"})
    two = _standings_zip(opening_night / "two-files.zip",
                         {"contest-standings-196456024.csv": STANDINGS_CSV, "readme.txt": b"x"})
    unrelated = _standings_zip(opening_night / "photos.zip", {"foo.csv": b"a,b\r\n"})
    # A truncated or corrupted download (bad CRC) is warned about, not fatal.
    corrupt = opening_night / "contest-standings-196456031 (1).zip"
    with zipfile.ZipFile(corrupt, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("contest-standings-196456031.csv", STANDINGS_CSV + b"3,7000000003,z,0,1,\r\n")
    data = corrupt.read_bytes()
    i = data.index(b"someone")
    corrupt.write_bytes(data[:i] + b"S" + data[i + 1:])
    set_mtime(str(corrupt), MORNING)
    # A download cut off before the zip's file list: only its name marks it as standings.
    cut_off = opening_night / "contest-standings-196456024 (2).zip"
    cut_off.write_bytes(good.read_bytes()[:40])
    set_mtime(str(cut_off), MORNING)
    # Last night's broken zip from another contest is listed but not warned about.
    old_cut_off = opening_night / "contest-standings-888888888.zip"
    old_cut_off.write_bytes(good.read_bytes()[:41])
    set_mtime(str(old_cut_off), MORNING)
    zip_bytes = good.read_bytes()

    payload = _finalize(opening_night, slate_dir)

    assert (slate_dir / "contest-standings-196456024.csv").read_bytes() == STANDINGS_CSV
    assert (slate_dir / "contest-standings-196456031.csv").exists()
    assert os.path.getmtime(slate_dir / "contest-standings-196456024.csv") == os.path.getmtime(good)
    assert not any(os.path.basename(a["file"]) == unrelated.name for a in payload["assignments"])
    a = _assignment(payload, corrupt.name)
    assert a["used"] is False and "unreadable zip" in a["reason"]
    a = _assignment(payload, cut_off.name)
    assert a["used"] is False and "unreadable zip" in a["reason"]
    assert any(cut_off.name in w for w in payload["warnings"])
    a = _assignment(payload, old_cut_off.name)
    assert a["used"] is False and "other slate" in a["reason"]
    assert not any(old_cut_off.name in w for w in payload["warnings"])
    assert sorted(payload["standings"]) == ["contest-standings-196456024.csv", "contest-standings-196456031.csv"]
    assert good.read_bytes() == zip_bytes and not list(slate_dir.glob("*.zip"))
    assert not (slate_dir / "contest-standings-999999999.csv").exists()
    a = _assignment(payload, other.name)
    assert a["used"] is False and "other slate" in a["reason"]
    a = _assignment(payload, two.name)
    assert a["used"] is False and "2 files" in a["reason"]
    assert any(two.name in w for w in payload["warnings"])
    assert "two-files.zip" in capsys.readouterr().out

    # Zip plus its unzipped CSV (and the earlier extraction): still one copy.
    loose = opening_night / "contest-standings-196456024.csv"
    loose.write_bytes(STANDINGS_CSV)
    set_mtime(str(loose), MORNING)
    payload = _finalize(opening_night, slate_dir)
    assert len([n for n in os.listdir(slate_dir) if n.startswith("contest-standings-196456024")]) == 1
    assert payload["standings"].count("contest-standings-196456024.csv") == 1


# --- Alternate slates (O-15) ---


def _write_slate(root, slate_id, starts):
    d = root / slate_id
    d.mkdir(parents=True)
    records.write_json_atomic(str(d / "slate.json"), {
        "slate_id": slate_id, "slate_date": slate_id[:10], "slate_type": slate_id.rsplit("_", 1)[-1],
        "locks": [{"lock": k, "start": s, "games": []} for k, s in enumerate(starts)],
    })
    return str(d)


def _two_slate_night(root):
    """10/19 main, 10/20 main (3:00-9:30 PM ET) and a 10/20 night slate whose lock 0 is 2 h later."""
    _write_slate(root, "2026-10-19_classic_main", ["2026-10-19T19:00:00-04:00"])
    main = _write_slate(root, SLATE_ID, ["2026-10-20T15:00:00-04:00", "2026-10-20T21:30:00-04:00"])
    night = _write_slate(root, "2026-10-20_classic_night", ["2026-10-20T17:00:00-04:00", "2026-10-20T22:00:00-04:00"])
    return main, night


def test_finalize_targets_all_slates_of_date(tmp_path):
    """Next morning, finalize's targets are every 10/20 slate folder in lock-0 order, not 10/19's."""
    main, night = _two_slate_night(tmp_path)
    cfg = Config(data_root=str(tmp_path))
    assert capture.finalize_targets(cfg, NEXT_MORNING) == [main, night]


def test_finalize_main_loops_with_type_folders(tmp_path, monkeypatch, capsys):
    """`finalize` with no arguments runs once per slate, each searching its own type's projections folder."""
    main, night = _two_slate_night(tmp_path / "slates")
    cfg = Config(data_root=str(tmp_path / "slates"), projs_dir=str(tmp_path / "projections"),
                 downloads_dir=str(tmp_path / "downloads"))
    calls = []
    monkeypatch.setattr(config_mod, "load_config_from_env", lambda: cfg)
    monkeypatch.setattr(capture, "finalize", lambda slate_dir, search_dirs, **kw: calls.append(
        (slate_dir, search_dirs, kw["slate_type"])))

    assert capture.main(["finalize"]) == 0
    assert calls == [
        (main, [cfg.downloads_dir, cfg.projs_dir], "main"),
        (night, [cfg.downloads_dir, cfg.projs_dir + "-night"], "night"),
    ]
    out = capsys.readouterr().out
    assert out.index(f"=== {SLATE_ID} ===") < out.index("=== 2026-10-20_classic_night ===")


def test_record_picks_folder_by_ids(opening_night, tmp_path):
    """With two 10/20 slates, `record` picks the folder whose Pre-L0 DKEntries holds the file's players."""
    slates = tmp_path / "slates"
    load_or_write_slate(Config(data_root=str(slates)), str(opening_night / "Pre-L0-DKEntries.csv"))
    twin_entries = make_twin(str(opening_night / "Pre-L0-DKEntries.csv"), str(tmp_path / "DKEntries-Night.csv"))
    _, night_dir = load_or_write_slate(Config(data_root=str(slates), slate_type="night"), twin_entries)
    cfg = Config(data_root=str(slates))

    twin_upload = make_twin(str(opening_night / "upload-ready-DKEntries-2026-10-20_135723.csv"),
                            str(tmp_path / "upload-ready-DKEntries-Night-2026-10-20_135723.csv"))
    assert capture._record_slate_dir(cfg, twin_upload) == night_dir
    assert capture._record_slate_dir(cfg, str(opening_night / "upload-ready-DKEntries-2026-10-20_135723.csv")) \
        == str(slates / SLATE_ID)

    other = tmp_path / "NBA-Projs-2026-10-20_12-00-00.csv"
    pd.DataFrame({"ID": [1, 2, 3], "Projection": [30.0, 20.0, 10.0], "Own_Proj": [10.0, 5.0, 1.0]}).to_csv(other, index=False)
    with pytest.raises(ValueError, match="pass --slate-dir"):
        capture._record_slate_dir(cfg, str(other))
