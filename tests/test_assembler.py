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

    monkeypatch.setattr(assembler, "build_model", no_solve)
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
    assert record["solve"]["method"] == "ilp" and record["solve"]["proven_optimal"] is True
    assert record["settings"]["min_unique"] == 1 and record["min_unique_removed"] == 0
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


def test_diagnose_builds_model_once(monkeypatch):
    """R1: an infeasible request with 3 caps builds the model once and names only Harper's cap.

    Harper is in all 100 lineups, so his 80% cap alone is impossible; Anunoby's
    50% cap and KAT's 20% floor are each satisfiable (see the tests above).
    """
    builds = []
    real_build = assembler.build_model

    def counting_build(*args, **kwargs):
        builds.append(1)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(assembler, "build_model", counting_build)
    settings = AssembleSettings(n_entries=40, max={DYLAN_HARPER: 80, OG_ANUNOBY: 50}, min={KARL_ANTHONY_TOWNS: 20})
    with pytest.raises(ValueError) as exc:
        assemble(_ranked(), settings)

    assert len(builds) == 1
    culprits = str(exc.value).splitlines()[1:]
    assert len(culprits) == 1 and culprits[0].strip().startswith("Dylan Harper max 80%")


# --- min_unique at assemble (O-14) --------------------------------------------
# Numbers verified against the fixture with PuLP 3.3 + HiGHS on 2026-10-22/23.


def _with_copy_of_rank_1() -> pd.DataFrame:
    """The fixture with a copy of rank 1 inserted as rank 2, renumbered 1..101."""
    df = _ranked()
    df = pd.concat([df.iloc[[0]], df], ignore_index=True)
    df["Final_Rank"] = range(1, len(df) + 1)
    return df


def _selected_sets(result) -> list:
    return [{extract_player_id(row[s]) for s in ROSTER_SLOTS} for _, row in result.df_selected.iterrows()]


def _max_shared(sets) -> int:
    return max(len(a & b) for i, a in enumerate(sets) for b in sets[i + 1:])


def test_unique_survivors_match_pairwise_walk():
    """The subset lookup keeps exactly what comparing each row with every earlier kept row keeps."""
    sets = assembler._player_sets(_ranked())
    for u in range(1, 6):
        naive = []
        for i, players in enumerate(sets):
            if all(len(players & sets[k]) <= 8 - u for k in naive):
                naive.append(i)
        assert assembler.unique_survivors(sets, u) == naive
    assert assembler.unique_survivors(sets, 0) == list(range(100))


def test_walkdown_drops_worse_copy_of_duplicate():
    """Of two identical lineups the better-ranked stays; the copy at rank 2 goes."""
    result = assemble(_with_copy_of_rank_1(), AssembleSettings(n_entries=40, min_unique=1))
    assert result.df_selected["Final_Rank"].tolist() == [1] + list(range(3, 42))
    assert result.min_unique_removed == 1
    assert result.kept_top_n == 39 and result.skipped_above_worst == 1
    assert result.solve["method"] == "top_n"


def test_min_unique_zero_allows_duplicates():
    result = assemble(_with_copy_of_rank_1(), AssembleSettings(n_entries=40, min_unique=0))
    assert result.df_selected["Final_Rank"].tolist() == list(range(1, 41))


def test_min_unique_2_fixture():
    result = assemble(_ranked(), AssembleSettings(n_entries=40, min_unique=2))
    assert result.min_unique_removed == 4
    assert result.df_selected["Final_Rank"].tolist() == list(range(1, 41))


def test_min_unique_3_fixture():
    result = assemble(_ranked(), AssembleSettings(n_entries=40, min_unique=3))
    ranks = result.df_selected["Final_Rank"].tolist()
    assert result.min_unique_removed == 54
    assert result.solve["objective_rank_sum"] == 1472 and result.solve["worst_rank"] == 84
    assert result.kept_top_n == 23 and result.skipped_above_worst == 44
    assert ranks[:2] == [1, 2]
    assert _max_shared(_selected_sets(result)) <= 5


def test_no_caps_skips_solver(monkeypatch):
    def no_solve(*args, **kwargs):
        raise AssertionError("solver called")

    monkeypatch.setattr(assembler, "build_model", no_solve)
    result = assemble(_ranked(), AssembleSettings(n_entries=40, min_unique=1))
    assert result.df_selected["Final_Rank"].tolist() == list(range(1, 41))


def test_min_unique_too_few_survivors(tmp_path):
    cfg = Config(ranked_lineup_dir=str(tmp_path))
    with pytest.raises(ValueError) as exc:
        assembler.run(cfg, RANKED, AssembleSettings(n_entries=40, min_unique=4))
    assert "min_unique 4" in str(exc.value) and "17" in str(exc.value)
    assert os.listdir(tmp_path) == []


def test_min_unique_blocks_cap_names_min_unique():
    """Anunoby's 50% cap fits the full pool but not the 46 lineups left at -u 3."""
    with pytest.raises(ValueError) as exc:
        assemble(_ranked(), AssembleSettings(n_entries=40, max={OG_ANUNOBY: 50}, min_unique=3))
    assert "OG Anunoby" in str(exc.value) and "min_unique 3" in str(exc.value)
    assemble(_ranked(), AssembleSettings(n_entries=40, max={OG_ANUNOBY: 50}, min_unique=0))


def test_floor_precheck_reports_full_pool():
    with pytest.raises(ValueError) as exc:
        assemble(_ranked(), AssembleSettings(n_entries=40, min={KARL_ANTHONY_TOWNS: 50}, min_unique=3))
    assert "in 15 of 46 lineups, need 20" in str(exc.value)
    assert "31 of the full pool" in str(exc.value)


@pytest.mark.parametrize("u", [9, -1])
def test_min_unique_out_of_range(u):
    with pytest.raises(ValueError, match="0-8"):
        assemble(_ranked(), AssembleSettings(n_entries=40, min_unique=u))


def test_time_limit_uses_incumbent(monkeypatch, capsys):
    """At the limit a valid N-lineup incumbent is used, flagged as not proven optimal."""
    settings = AssembleSettings(n_entries=40, min={KARL_ANTHONY_TOWNS: 20}, min_unique=1)
    proven = assemble(_ranked(), settings)
    assert proven.solve["worst_rank"] == 47 and proven.kept_top_n == 35
    rows = [r - 1 for r in proven.df_selected["Final_Rank"]]   # -u 1 removes nothing: row = rank - 1

    monkeypatch.setattr(assembler, "solve_model", lambda model, **kw: assembler.SolveOutcome("TimeLimit", rows, False))
    capsys.readouterr()
    result = assemble(_ranked(), settings)
    assert result.df_selected["Final_Rank"].tolist() == proven.df_selected["Final_Rank"].tolist()
    assert result.solve["status"] == "TimeLimit" and result.solve["proven_optimal"] is False
    assert result.solve["method"] == "ilp"
    assert "Warning: solver hit its 10 s limit" in capsys.readouterr().out


def test_time_limit_no_solution_fails(monkeypatch):
    monkeypatch.setattr(assembler, "solve_model", lambda model, **kw: assembler.SolveOutcome("TimeLimit", [], False))
    with pytest.raises(ValueError, match="no solution found in 10 s"):
        assemble(_ranked(), AssembleSettings(n_entries=40, min={KARL_ANTHONY_TOWNS: 20}))


def test_diagnosis_timeout_is_reported_not_ruled_out(monkeypatch):
    """A relaxed re-solve that finds nothing in the limit is reported as unchecked, not as 'no single cause'."""
    outcomes = iter([assembler.SolveOutcome("Infeasible", [], False)])
    monkeypatch.setattr(assembler, "solve_model",
                        lambda model, **kw: next(outcomes, assembler.SolveOutcome("TimeLimit", [], False)))
    with pytest.raises(ValueError) as exc:
        assemble(_ranked(), AssembleSettings(n_entries=40, max={OG_ANUNOBY: 50}, min_unique=0))
    assert "couldn't check within 10 s" in str(exc.value) and "OG Anunoby max 50%" in str(exc.value)
    assert "no single constraint" not in str(exc.value)


def test_real_time_limit_maps_to_timelimit():
    """A real HiGHS solve cut off before any solution is TimeLimit with no rows (not PuLP's "Optimal")."""
    df = assembler._sorted_pool(_ranked())
    sets = assembler._player_sets(df)
    settings = AssembleSettings(n_entries=40, min={KARL_ANTHONY_TOWNS: 20})
    model = assembler.build_model(sets, df["Final_Rank"].tolist(), 40, assembler._constraints(settings, {}))
    outcome = assembler.solve_model(model, time_limit=1e-6)
    assert outcome.status == "TimeLimit" and outcome.chosen == [] and outcome.proven is False
