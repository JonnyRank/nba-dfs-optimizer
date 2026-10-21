"""File identification, projection checks and copy rules for nightly capture."""

import os

import pandas as pd

from nba_optimizer import records

from conftest import OPENING_NIGHT_DIR

TEMPLATE = os.path.join(OPENING_NIGHT_DIR, "NBA-Projs-Template-26-27-WIP_2026-10-20_21-44-33.csv")


def test_classify_opening_night_files():
    """Each 10/20 file is identified by its contents, not its name."""
    expected = {
        "Pre-L0-DKEntries.csv": "pretemplate",
        "upload-ready-DKEntries-2026-10-20_135723.csv": "upload_candidate",
        "L1-DK_NBA_Main_Late_Swap_Lineups.csv": "stok_export",
        "L2-DK_NBA_Main_Late_Swap_Lineups.csv": "stok_export",
        "L0-NBA-Projs-2026-10-20_13-55-35.csv": "projs_basic",
        "L1-NBA-Projs-2026-10-20_17-55-17.csv": "projs_basic",
        "L2-NBA-Projs-2026-10-20_20-28-20.csv": "projs_basic",
        "NBA-Projs-Template-26-27-WIP_2026-10-20_21-44-33.csv": "projs_expanded",
        "Post-L0-DKEntries.csv": "midnight",
        "Post-L1-DKEntries.csv": "midnight",
        "Post-L2-DKEntries.csv": "final",
    }
    actual = {name: records.classify_file(os.path.join(OPENING_NIGHT_DIR, name)) for name in expected}
    assert actual == expected


def test_read_lineup_file_parses_stok_export_ids():
    """The Stok export (BOM, no pool block, reordered rows) yields integer DK IDs per slot."""
    df = records.read_lineup_file(os.path.join(OPENING_NIGHT_DIR, "L1-DK_NBA_Main_Late_Swap_Lineups.csv"))
    assert len(df) == 40
    row = df.set_index("entry_id").loc["5303852548"]
    assert row["contest_id"] == 196456024
    assert [int(row[s]) for s in ("PG", "SG", "UTIL")] == [44451282, 44451268, 44451199]
    assert not df[[c for c in df.columns if c.endswith("_locked")]].to_numpy().any()


def test_lineup_key_is_sorted_ids():
    assert records.lineup_key([44451282, 44451199, 44451268]) == "44451199-44451268-44451282"


def test_check_blend_template_clean():
    """All 125 rows of the 10/20 template agree with the blend rule."""
    result = records.check_blend(pd.read_csv(TEMPLATE))
    assert result == {"rows": 125, "mismatches": 0, "examples": []}


def test_check_blend_flags_perturbed_row(capsys):
    """A Projection that isn't mins x Blend FPPM is flagged and warned about, not raised."""
    df = pd.read_csv(TEMPLATE)
    df.loc[0, "Projection"] = df.loc[0, "Projection"] + 1.0
    result = records.check_blend(df)
    assert result["mismatches"] == 1
    assert result["examples"] == [df.loc[0, "Player"]]
    assert "blend check" in capsys.readouterr().out


def test_check_blend_basic_layout_is_none():
    df = pd.read_csv(os.path.join(OPENING_NIGHT_DIR, "L0-NBA-Projs-2026-10-20_13-55-35.csv"))
    assert records.check_blend(df) is None


def test_min_source_my_vs_stok():
    """My Mins wins when filled and non-zero; blank or 0 falls back to Stok Mins."""
    df = pd.DataFrame({
        "ID": [1, 2, 3],
        "Projection": [32.0 * 1.25, 30.0 * 1.0, 28.0 * 1.5],
        "Stok Mins": [30.0, 30.0, 28.0],
        "My Mins": [32.0, None, 0.0],
        "LS FPPM": [1.2, 1.0, 1.4],
        "Stok FPPM": [1.3, 1.0, 1.6],
        "My FPPM": [0.0, None, 0.0],
        "Blend FPPM": [1.25, 1.0, 1.5],
    })
    derived = records.derive_projection_fields(df)
    assert derived["min_source"].tolist() == ["my", "stok", "stok"]
    assert derived["mins_used"].tolist() == [32.0, 30.0, 28.0]
    assert records.check_blend(df)["mismatches"] == 0

    df.loc[0, "Projection"] = 30.0 * 1.25  # built from Stok Mins although My Mins is set
    assert records.check_blend(df, warn=False)["mismatches"] == 1


def test_snapshot_input_reuses_identical_and_never_overwrites(tmp_path):
    """Same contents reuse the existing copy; a different file under the same name gets -HHMMSS."""
    src_a = tmp_path / "a.csv"
    src_b = tmp_path / "b.csv"
    src_a.write_text("ID,Projection,Own_Proj\n1,10,5\n")
    src_b.write_text("ID,Projection,Own_Proj\n1,11,5\n")
    slate_dir = tmp_path / "slate"

    first = records.snapshot_input(str(src_a), str(slate_dir), "L0-NBA-Projs.csv")
    again = records.snapshot_input(str(src_a), str(slate_dir), "other-name.csv")
    other = records.snapshot_input(str(src_b), str(slate_dir), "L0-NBA-Projs.csv")

    assert first == again == "L0-NBA-Projs.csv"
    assert other.startswith("L0-NBA-Projs-") and other != first
    assert (slate_dir / first).read_text() == src_a.read_text()
    assert sorted(os.listdir(slate_dir)) == sorted([first, other])


def test_check_blend_skips_when_columns_missing(capsys):
    """An expanded export missing Blend FPPM warns and returns None instead of raising."""
    df = pd.read_csv(TEMPLATE).drop(columns=["Blend FPPM"])
    assert records.check_blend(df) is None
    assert "blend check skipped" in capsys.readouterr().out


def test_projections_copy_name_keeps_source_naming(tmp_path):
    """Copies keep the macro's name (old or new timestamp format), minus browser/capture prefixes."""
    new_format = tmp_path / "NBA-Projs-2026-10-21_10-21_13-55-35 (1).csv"
    old_format = tmp_path / "L1-NBA-Projs-2026-10-20_17-55-17.csv"
    other = tmp_path / "projections.csv"
    for p in (new_format, old_format, other):
        p.write_text("ID,Projection,Own_Proj\n")
    assert records.projections_copy_name(str(new_format), 0) == "L0-NBA-Projs-2026-10-21_10-21_13-55-35.csv"
    assert records.projections_copy_name(str(old_format), 2) == "L2-NBA-Projs-2026-10-20_17-55-17.csv"
    assert records.projections_copy_name(str(new_format), None) == "Post-NBA-Projs-2026-10-21_10-21_13-55-35.csv"
    assert records.projections_copy_name(str(other), 1).startswith("L1-NBA-Projs-")
