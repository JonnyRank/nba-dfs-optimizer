"""Assembling the 40 entries from the real 10/20 ranked pool (O-13 §3.6, §3.8).

The fixture holds the top 100 lineups of the 2,472-lineup pool; N = 40 is
the number of entries in that night's DKEntries. Expected numbers were
verified against the fixture with PuLP + HiGHS on 2026-10-21.
"""

import os

import pandas as pd
import pytest

from nba_optimizer import assembler
from nba_optimizer.assembler import AssembleSettings, assemble
from nba_optimizer.config import Config, ROSTER_SLOTS
from nba_optimizer.utils import extract_player_id

NIGHT_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "2026-10-20")
RANKED = os.path.join(NIGHT_DIR, "ranked-lineups-2026-10-20_135723.csv")
UPLOAD = os.path.join(NIGHT_DIR, "upload-ready-DKEntries-2026-10-20_135723.csv")

OG_ANUNOBY = 44451272
KARL_ANTHONY_TOWNS = 44451218
DYLAN_HARPER = 44451282
PAUL_GEORGE = 44451243


def _ranked() -> pd.DataFrame:
    return pd.read_csv(RANKED)


def _count(df: pd.DataFrame, dk_id: int) -> int:
    return sum(
        any(extract_player_id(row[s]) == str(dk_id) for s in ROSTER_SLOTS) for _, row in df.iterrows()
    )


def test_assemble_no_constraints_is_top_n():
    """With no caps the 40 are ranks 1-40, row for row the night's upload file."""
    result = assemble(_ranked(), AssembleSettings(n_entries=40))
    df_upload = pd.read_csv(UPLOAD)
    df_upload = df_upload[df_upload["Entry ID"].notna()]

    assert result.df_selected["Final_Rank"].tolist() == list(range(1, 41))
    assert result.df_selected["Entry_Order"].tolist() == list(range(1, 41))
    assert result.df_selected[list(ROSTER_SLOTS)].values.tolist() == df_upload[list(ROSTER_SLOTS)].values.tolist()
    assert result.kept_top_n == 40 and result.skipped_above_worst == 0


def test_assemble_max_cap():
    """OG Anunoby (67 of 100) at 50% -> exactly 20; worst rank 69, 31 of 1-40 kept, same as greedy."""
    result = assemble(_ranked(), AssembleSettings(n_entries=40, max={OG_ANUNOBY: 50}))

    assert _count(result.df_selected, OG_ANUNOBY) == 20
    assert result.solve["worst_rank"] == 69
    assert result.kept_top_n == 31

    # Greedy: walk the ranks, skip a lineup that would put Anunoby over 20.
    greedy, anunoby = [], 0
    for _, row in _ranked().iterrows():
        has = any(extract_player_id(row[s]) == str(OG_ANUNOBY) for s in ROSTER_SLOTS)
        if has and anunoby == 20:
            continue
        greedy.append(int(row["Final_Rank"]))
        anunoby += has
        if len(greedy) == 40:
            break
    assert result.df_selected["Final_Rank"].tolist() == greedy


def test_assemble_min_floor():
    """KAT is in 3 of the top 40 and 31 of the 100; a 20% floor needs 8."""
    df = _ranked()
    assert _count(df.head(40), KARL_ANTHONY_TOWNS) == 3 and _count(df, KARL_ANTHONY_TOWNS) == 31

    result = assemble(df, AssembleSettings(n_entries=40, min={KARL_ANTHONY_TOWNS: 20}))
    assert _count(result.df_selected, KARL_ANTHONY_TOWNS) >= 8
    assert result.solve["worst_rank"] == 47
    assert result.kept_top_n == 35


def test_assemble_infeasible_names_culprit(tmp_path):
    """Harper is in all 100 lineups, so at most 32 of 40 is impossible; nothing is written."""
    cfg = Config(ranked_lineup_dir=str(tmp_path))
    with pytest.raises(ValueError) as exc:
        assembler.run(cfg, RANKED, AssembleSettings(n_entries=40, max={DYLAN_HARPER: 80}))

    assert "Dylan Harper" in str(exc.value)
    assert "in 100 of 100 lineups" in str(exc.value)
    assert os.listdir(tmp_path) == []


def test_assemble_min_precheck(monkeypatch):
    """Paul George is in 5 of 100 lineups and the floor needs 8: fails before any solve."""
    def no_solve(*args, **kwargs):
        raise AssertionError("solver called")

    monkeypatch.setattr(assembler, "_solve", no_solve)
    with pytest.raises(ValueError, match="in 5 of 100 lineups, need 8"):
        assemble(_ranked(), AssembleSettings(n_entries=40, min={PAUL_GEORGE: 20}))


def test_assemble_n_larger_than_pool_fails():
    with pytest.raises(ValueError, match="only 100 lineups"):
        assemble(_ranked(), AssembleSettings(n_entries=150))


def test_assemble_percent_out_of_range_fails():
    with pytest.raises(ValueError, match="0-100"):
        assemble(_ranked(), AssembleSettings(n_entries=40, max={OG_ANUNOBY: 120}))


def test_assemble_deterministic():
    settings = AssembleSettings(n_entries=40, max={OG_ANUNOBY: 50}, min={KARL_ANTHONY_TOWNS: 20})
    first = assemble(_ranked(), settings).df_selected["Final_Rank"].tolist()
    second = assemble(_ranked(), settings).df_selected["Final_Rank"].tolist()
    assert first == second


def test_assemble_writes_csv_and_record(tmp_path):
    """The CSV keeps the ranked columns plus Entry_Order; the JSON records caps with their counts."""
    from nba_optimizer import records

    cfg = Config(ranked_lineup_dir=str(tmp_path))
    out = assembler.run(cfg, RANKED, AssembleSettings(n_entries=40, max={OG_ANUNOBY: 50}))
    df = pd.read_csv(out)
    assert list(df.columns) == ["Entry_Order"] + list(_ranked().columns)
    assert len(df) == 40

    record = records.read_json(out[:-4] + ".json")
    assert record["ranked_file"] == os.path.basename(RANKED)
    assert record["settings"]["max"] == [{"dk_id": OG_ANUNOBY, "name": "OG Anunoby", "pct": 50, "count": 20}]
    assert record["solve"]["worst_rank"] == 69
    assert record["skipped_above_worst"] == 69 - 40
    anunoby = next(e for e in record["exposures"] if e["dk_id"] == OG_ANUNOBY)
    assert anunoby == {"dk_id": OG_ANUNOBY, "name": "OG Anunoby", "count": 20, "pct": 50.0}


def test_own_max_replaces_max_all():
    """--max-all 50 with --max "Dylan Harper=100": Harper (in all 100 lineups) stays at 40 of 40,
    while the blanket cap binds on everyone else (Ausar Thompson is in 25 of the top 40)."""
    result = assemble(_ranked(), AssembleSettings(n_entries=40, max={DYLAN_HARPER: 100}, max_all=50))
    by_id = {e["dk_id"]: e["count"] for e in result.exposures}

    assert by_id[DYLAN_HARPER] == 40
    assert by_id[44451275] == 20
    assert all(count <= 20 for dk_id, count in by_id.items() if dk_id != DYLAN_HARPER)
