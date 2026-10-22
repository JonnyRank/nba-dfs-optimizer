"""Projection/ownership overrides on the real 10/20 files (O-13 §3.5)."""

import itertools
import os
from datetime import datetime

import pandas as pd
import pytest

from nba_optimizer import records, ranker
from nba_optimizer.config import Config, ROSTER_SLOTS
from nba_optimizer.overrides import parse_assignment, resolve_overrides, resolve_player
from nba_optimizer.utils import merge_player_pool, parse_dk_entries

NIGHT_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "2026-10-20")
ENTRIES = os.path.join(NIGHT_DIR, "Pre-L0-DKEntries.csv")
PROJS = os.path.join(NIGHT_DIR, "L0-NBA-Projs-2026-10-20_13-55-35.csv")
RANKED = os.path.join(NIGHT_DIR, "ranked-lineups-2026-10-20_135723.csv")

JAYSON_TATUM = 44451207
TATUM_EXPORT = 50.5594555
_SECONDS = itertools.count()


def _players() -> pd.DataFrame:
    return merge_player_pool(parse_dk_entries(ENTRIES), pd.read_csv(PROJS), how="inner")


def _rank(tmp_path, overrides=None, parent_record=None):
    """Rank the 100 fixture lineups (as a pool) with the given overrides; return (ranked df, record)."""
    cfg = Config(entries_path=ENTRIES, projs_dir=str(tmp_path), ranked_lineup_dir=str(tmp_path / "out"))
    pool = tmp_path / "lineup-pool-2026-10-20_135723.csv"
    if not pool.exists():
        pd.read_csv(RANKED)[list(ROSTER_SLOTS)].to_csv(pool, index=False)
    run_time = datetime(2026, 10, 20, 13, 0, next(_SECONDS) % 60).astimezone()
    out = ranker.run(cfg, lineup_file=str(pool), projs_file=PROJS, run_time=run_time,
                     overrides=overrides, parent_record=parent_record)
    return pd.read_csv(out), records.read_json(out[:-4] + ".json")


def _by_key(df: pd.DataFrame) -> dict:
    return {records.lineup_key(int(row[s].rsplit("(", 1)[1][:-1]) for s in ROSTER_SLOTS): row
            for _, row in df.iterrows()}


def test_parse_assignment():
    assert parse_assignment("Jayson Tatum=55") == ("Jayson Tatum", 55.0)
    assert parse_assignment(" De'Aaron Fox = 40.5 ") == ("De'Aaron Fox", 40.5)
    for bad in ("Jayson Tatum", "=55", "Jayson Tatum=", "Jayson Tatum=abc"):
        with pytest.raises(ValueError):
            parse_assignment(bad)


def test_override_by_name_and_id(tmp_path):
    """A lowercase name and the DK ID resolve to Tatum; every Tatum lineup gains 60 - 50.5594555."""
    df_players = _players()
    by_name = resolve_overrides(df_players, ["jayson tatum=60"], [])
    by_id = resolve_overrides(df_players, [f"{JAYSON_TATUM}=60"], [])
    assert by_name == by_id == [{"dk_id": JAYSON_TATUM, "name": "Jayson Tatum", "field": "Projection", "to": 60.0}]

    plain, _ = _rank(tmp_path)
    bumped, _ = _rank(tmp_path, overrides=by_name)
    plain_by, bumped_by = _by_key(plain), _by_key(bumped)
    tatum = f"Jayson Tatum ({JAYSON_TATUM})"
    n_tatum = 0
    for key, row in plain_by.items():
        gain = bumped_by[key]["Total_Projection"] - row["Total_Projection"]
        if tatum in row[list(ROSTER_SLOTS)].tolist():
            n_tatum += 1
            assert gain == pytest.approx(60 - TATUM_EXPORT)
        else:
            assert gain == pytest.approx(0)
    assert n_tatum == 51


def test_override_ambiguous_name_lists_candidates():
    df_players = _players()
    jalens = df_players[df_players["Name"].str.contains("Jalen")]
    assert len(jalens) > 1
    with pytest.raises(ValueError) as exc:
        resolve_player("jalen", df_players)
    for name in jalens["Name"]:
        assert name in str(exc.value)


def test_override_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown player"):
        resolve_player("Jayson Tatumm Jr", _players())
    with pytest.raises(ValueError, match="unknown player ID"):
        resolve_player("123", _players())


def test_override_recorded(tmp_path):
    """The run record keeps {dk_id, field, from, to}, with from = the export's value."""
    _, record = _rank(tmp_path, overrides=resolve_overrides(_players(), ["Jayson Tatum=60"], []))
    assert len(record["overrides"]) == 1
    o = record["overrides"][0]
    assert {k: o[k] for k in ("dk_id", "field", "to")} == {"dk_id": JAYSON_TATUM, "field": "Projection", "to": 60}
    assert o["from"] == pytest.approx(TATUM_EXPORT)
    assert o["name"] == "Jayson Tatum"


def test_override_not_in_pool_warns(tmp_path, capsys):
    """On a re-rank, an override on a player the pool doesn't contain warns."""
    in_pool = set(pd.read_csv(RANKED)[list(ROSTER_SLOTS)].values.ravel())
    df_players = _players()
    absent = df_players[~df_players["Name + ID"].isin(in_pool)].iloc[0]
    overrides = resolve_overrides(df_players, [f"{absent['ID']}=60"], [])

    _rank(tmp_path, overrides=overrides, parent_record={})
    out = capsys.readouterr().out
    assert f"{absent['Name']} isn't in this pool (filtered out at generation)" in out
