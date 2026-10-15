# Plan 007: Lock down lineup-ranking semantics with characterization tests

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat eade9a1..HEAD -- src/nba_optimizer/ranker.py src/nba_optimizer/config.py tests/test_ranker.py docs/codebase/TESTING.md docs/codebase/CONCERNS.md AGENTS.md BACKLOG.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (tests and docs only; no production code changes)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `eade9a1`, 2026-10-15
- **Issue**: https://github.com/JonnyRank/nba-dfs-optimizer/issues/62
- **Supersedes**: `plans/005-vectorize-lineup-ranking.md` (REJECTED; see its reconcile note)

## Why this matters

`ranker.rank_lineups` decides which lineups from the generated pool get
uploaded to DraftKings, but nothing tests its scoring. The only ranker tests,
in `tests/test_pipeline_artifacts.py`, check which files `ranker.run()` reads
and writes, not the numbers it produces. So a change to the scoring could
silently change which lineups get entered. Plan 005 proposed vectorizing this
function for speed. It was rejected after measuring: `rank_lineups` takes
0.13 s for 2,500 lineups, 0.5 s for 10,000 and 2.5 s for 50,000, compared with
about 44 s of lineup generation. This plan keeps plan 005's one valuable part,
the characterization tests.

## Current state

- `src/nba_optimizer/ranker.py` — `rank_lineups(df_lineups, df_players, weights)` (lines 23–71) computes per-lineup metrics and ranks the lineups. `run()` (line 74 onward) loads the files, calls `rank_lineups`, and writes a CSV. **Do not modify this file.**
- `src/nba_optimizer/config.py:7` — `ROSTER_SLOTS = ("PG", "SG", "SF", "PF", "C", "G", "F", "UTIL")`.
- `tests/test_utils.py` — the style to copy. It has a module docstring, plain `test_*` functions (no classes), a one-line docstring per test stating the domain rule, and no mocking.

Excerpt from `src/nba_optimizer/ranker.py:27-71`, the behavior these tests lock down:

```python
    proj_map = df_players.set_index("Name + ID")["Projection"].to_dict()
    own_map = df_players.set_index("Name + ID")["Own_Proj"].to_dict()

    lineup_results = []
    slots = ROSTER_SLOTS

    for idx, row in df_lineups.iterrows():
        lineup_names = [row[s] for s in slots]

        total_proj = sum([proj_map.get(name, 0) for name in lineup_names])
        total_own = sum([own_map.get(name, 0) for name in lineup_names])

        # Geomean Ownership (add small epsilon to avoid log(0))
        own_values = [own_map.get(name, 0) for name in lineup_names]
        geo_own = np.exp(np.mean(np.log([max(0.1, o) for o in own_values])))
        ...
    df_res["Proj_Rank"] = df_res["Total_Projection"].rank(ascending=False)
    df_res["Own_Rank"] = df_res["Total_Ownership"].rank(ascending=True)
    df_res["Geo_Rank"] = df_res["Geomean_Ownership"].rank(ascending=True)

    # Final Score: Weighted sum of ranks
    df_res["Lineup_Score"] = (
        df_res["Proj_Rank"] * weights.get("proj", 1.0)
        + df_res["Own_Rank"] * weights.get("own", 1.0)
        + df_res["Geo_Rank"] * weights.get("geo", 1.0)
    )

    # Sort by Score
    df_res = df_res.sort_values("Lineup_Score")
    df_res["Final_Rank"] = range(1, len(df_res) + 1)
```

The tests lock down these rules:
- A player missing from the pool counts as 0 projection and 0 ownership.
- The geomean floors each player's ownership at 0.1.
- Ranks use pandas' default `method="average"`, so tied lineups share a rank (e.g. 1.5).
- A lower `Lineup_Score` is better.
- `Lineup_ID` is the lineup's 1-based row position in the input.
- The returned frame is sorted by score but keeps its original index. Look rows up by `Lineup_ID`, not by position, unless the test is checking the sorted order.

## Commands you will need

Run from the repo root in PowerShell. If `python` is not the repo venv, use `.\venv\Scripts\python.exe`.

| Purpose | Command | Expected on success |
|---|---|---|
| New tests only | `python -m pytest -q tests/test_ranker.py` | `7 passed` |
| Full suite | `python -m pytest -q` | `49 passed` (42 before this plan) |
| Import check | `python -c "from nba_optimizer import engine, ranker, exporter"` | exit 0 |

## Scope

**In scope** (the only files you should modify):
- `tests/test_ranker.py` (create)
- `docs/codebase/TESTING.md` (the "Known gaps" bullet at line 46, plus one new coverage-table row)
- `docs/codebase/CONCERNS.md` (the text of the line 9 row "Automated tests cover only a small baseline", and the line 36 `iterrows()` row)
- `AGENTS.md` (only the test-list bullets around lines 69–75)
- `BACKLOG.md` (only the `* **Status**:` line under `### [Implement] Vectorize Lineup Ranking Logic`, at line 151)
- `plans/README.md` (only the plan 007 status row; skip this if a reviewer told you they maintain the index)

**Out of scope** (do NOT touch):
- `src/nba_optimizer/ranker.py`. This plan describes the current behavior. If a test fails against the unmodified code, either the test is wrong or the code has drifted (STOP). Never "fix" the ranker.
- Vectorizing `rank_lineups`. It was rejected (see "Why this matters").
- `tests/test_pipeline_artifacts.py`. It covers the file handoff; leave it alone.

## Git workflow

- Branch: `advisor/007-ranker-characterization-tests`
- Commit messages follow the style in `git log`: `test: characterize lineup ranking semantics (plan 007)`, then `docs: record ranker test coverage (plan 007)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Create `tests/test_ranker.py`

Create the file with exactly this content. It was run against `rank_lineups` at `eade9a1` and all 7 tests passed:

```python
"""Characterization tests for lineup scoring in nba_optimizer.ranker.rank_lineups.

These lock down the current ranking semantics on a tiny hand-built player
pool, so a future change to rank_lineups cannot silently change which lineups
come out on top. Every expected number can be checked by hand from PLAYERS.
"""

import math

import pandas as pd
import pytest

from nba_optimizer.config import ROSTER_SLOTS
from nba_optimizer.ranker import rank_lineups

# (Name + ID, Projection, Own_Proj)
PLAYERS = [
    ("A1 (1)", 50, 30.0),
    ("A2 (2)", 45, 25.0),
    ("A3 (3)", 40, 20.0),
    ("A4 (4)", 35, 15.0),
    ("A5 (5)", 30, 10.0),
    ("A6 (6)", 25, 8.0),
    ("A7 (7)", 20, 5.0),
    ("A8 (8)", 15, 2.0),
    ("B1 (11)", 30, 1.0),
    ("B2 (12)", 30, 1.0),
    ("Z0 (20)", 10, 0.0),
]

# Projection 260, ownership 115.
LINEUP_1 = ["A1 (1)", "A2 (2)", "A3 (3)", "A4 (4)", "A5 (5)", "A6 (6)", "A7 (7)", "A8 (8)"]
# A5/A6 swapped for two 1%-owned B players: projection 265, ownership 99.
LINEUP_2 = ["A1 (1)", "A2 (2)", "A3 (3)", "A4 (4)", "B1 (11)", "B2 (12)", "A7 (7)", "A8 (8)"]
# Contains a 0%-owned player (Z0) and a player missing from the pool (Ghost):
# projection 230, ownership 105.
LINEUP_3 = ["A1 (1)", "A2 (2)", "A3 (3)", "A4 (4)", "A5 (5)", "Z0 (20)", "A7 (7)", "Ghost (99)"]

# ranker.run() defaults (proj_weight=0.85, own_weight=0.0, geo_weight=0.15).
DEFAULT_WEIGHTS = {"proj": 0.85, "own": 0.0, "geo": 0.15}


def _players() -> pd.DataFrame:
    return pd.DataFrame(PLAYERS, columns=["Name + ID", "Projection", "Own_Proj"])


def _lineups(*lineups) -> pd.DataFrame:
    return pd.DataFrame(list(lineups), columns=list(ROSTER_SLOTS))


def _geomean(values) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


def test_totals_sum_projection_and_ownership_across_all_slots():
    """Total_Projection and Total_Ownership are plain sums over all 8 slots."""
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_2), _players(), DEFAULT_WEIGHTS)
    df_by_id = df_ranked.set_index("Lineup_ID")

    assert df_by_id.loc[1, "Total_Projection"] == 260
    assert df_by_id.loc[1, "Total_Ownership"] == pytest.approx(115.0)
    assert df_by_id.loc[2, "Total_Projection"] == 265
    assert df_by_id.loc[2, "Total_Ownership"] == pytest.approx(99.0)


def test_missing_player_contributes_zero_projection_and_ownership():
    """A lineup player absent from the player pool counts as 0 projection and
    0 ownership instead of raising (e.g. a player dropped from projections)."""
    df_ranked = rank_lineups(_lineups(LINEUP_3), _players(), DEFAULT_WEIGHTS)
    row = df_ranked.iloc[0]

    assert row["Total_Projection"] == 230
    assert row["Total_Ownership"] == pytest.approx(105.0)


def test_geomean_ownership_floors_zero_and_missing_at_0_1():
    """Geomean_Ownership floors each player's ownership at 0.1 before the log,
    so a 0%-owned or missing player pulls the geomean down without making it
    zero or undefined."""
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_3), _players(), DEFAULT_WEIGHTS)
    df_by_id = df_ranked.set_index("Lineup_ID")

    assert df_by_id.loc[1, "Geomean_Ownership"] == pytest.approx(
        _geomean([30, 25, 20, 15, 10, 8, 5, 2])
    )
    # Z0 (0%) and Ghost (missing) both become 0.1.
    assert df_by_id.loc[2, "Geomean_Ownership"] == pytest.approx(
        _geomean([30, 25, 20, 15, 10, 0.1, 5, 0.1])
    )


def test_default_weights_rank_order():
    """With the run() default weights, the score is 0.85*Proj_Rank +
    0.15*Geo_Rank (lower is better) and Final_Rank follows the score.

    Proj_Rank: L2 (265) 1, L1 (260) 2, L3 (230) 3.
    Geo_Rank (lowest geomean is best): L3 1, L2 2, L1 3.
    Scores: L2 1.15, L1 2.15, L3 2.70.
    """
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_2, LINEUP_3), _players(), DEFAULT_WEIGHTS)
    df_by_id = df_ranked.set_index("Lineup_ID")

    assert df_by_id["Proj_Rank"].to_dict() == {1: 2.0, 2: 1.0, 3: 3.0}
    assert df_by_id["Own_Rank"].to_dict() == {1: 3.0, 2: 1.0, 3: 2.0}
    assert df_by_id["Geo_Rank"].to_dict() == {1: 3.0, 2: 2.0, 3: 1.0}
    assert df_by_id.loc[2, "Lineup_Score"] == pytest.approx(1.15)
    assert df_by_id.loc[1, "Lineup_Score"] == pytest.approx(2.15)
    assert df_by_id.loc[3, "Lineup_Score"] == pytest.approx(2.70)
    assert df_ranked["Lineup_ID"].tolist() == [2, 1, 3]
    assert df_ranked["Final_Rank"].tolist() == [1, 2, 3]


def test_ownership_only_weights_rank_by_lowest_total_ownership():
    """Weights are honored: with only own_weight set, the lineup with the
    lowest Total_Ownership ranks first (L2 99, L3 105, L1 115)."""
    weights = {"proj": 0.0, "own": 1.0, "geo": 0.0}
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_2, LINEUP_3), _players(), weights)

    assert df_ranked["Lineup_ID"].tolist() == [2, 3, 1]
    assert df_ranked["Final_Rank"].tolist() == [1, 2, 3]


def test_tied_metrics_share_average_rank():
    """Lineups with identical metrics get the average of the tied ranks
    (pandas rank method='average'), e.g. two-way tie for first = 1.5."""
    df_ranked = rank_lineups(_lineups(LINEUP_1, LINEUP_1), _players(), DEFAULT_WEIGHTS)

    assert df_ranked["Proj_Rank"].tolist() == [1.5, 1.5]
    assert df_ranked["Own_Rank"].tolist() == [1.5, 1.5]
    assert df_ranked["Geo_Rank"].tolist() == [1.5, 1.5]


def test_output_keeps_slot_columns_and_lineup_ids():
    """Each ranked row carries its original 8 slot assignments, and Lineup_ID
    is the 1-based position of the lineup in the input pool."""
    lineups = [LINEUP_1, LINEUP_2, LINEUP_3]
    df_ranked = rank_lineups(_lineups(*lineups), _players(), DEFAULT_WEIGHTS)

    assert sorted(df_ranked["Lineup_ID"].tolist()) == [1, 2, 3]
    for _, row in df_ranked.iterrows():
        assert [row[s] for s in ROSTER_SLOTS] == lineups[row["Lineup_ID"] - 1]
```

**Verify**: `python -m pytest -q tests/test_ranker.py` → `7 passed`. Then `python -m pytest -q` → `49 passed`.

Commit: `test: characterize lineup ranking semantics (plan 007)`.

### Step 2: Prove the tests catch real changes (temporary edits, not committed)

1. In `src/nba_optimizer/ranker.py`, temporarily change `max(0.1, o)` to `max(0.01, o)`. Run `python -m pytest -q tests/test_ranker.py`. Expect at least 1 failure, including `test_geomean_ownership_floors_zero_and_missing_at_0_1`.
2. Revert that change. Then temporarily change `.rank(ascending=False)` on the `Proj_Rank` line to `.rank(ascending=True)` and run the same command. Expect failures in `test_default_weights_rank_order`.
3. Revert everything with `git checkout -- src/nba_optimizer/ranker.py`.

**Verify**: `git status --short src/` → no output. `python -m pytest -q` → `49 passed`.

### Step 3: Update docs

- `docs/codebase/TESTING.md`:
  - Add a coverage-table row after the `generate_single_lineup` row: Scope `Unit`, Covered `Yes (partial)`, Target `nba_optimizer.ranker.rank_lineups`, Notes `tests/test_ranker.py: totals, missing-player and 0.1 geomean floor, weighted rank order, average-rank ties, slot/Lineup_ID passthrough`.
  - Line 46, "Known gaps": this line currently says "end-to-end ranking and export logic in `ranker.py` and `exporter.py` (the artifact-handoff contract is tested; the scoring/formatting logic is not)". Change it to say that `tests/test_ranker.py` now characterizes the ranker's scoring, and that the formatting logic in `exporter.py` is still untested.
- `docs/codebase/CONCERNS.md`:
  - Line 9: remove `ranker.py` from the list of untested modules, and list `tests/test_ranker.py` alongside the existing test files.
  - Line 36 (`ranker.py` uses `iterrows()`): strike through the concern the same way as the resolved row directly above it. Set the symptom cell to `Measured 2026-10-15: 0.13 s / 2,500 lineups, 2.5 s / 50,000 — negligible vs ~44 s generation; vectorization rejected (plan 005)`.
- `AGENTS.md`:
  - After the `tests/test_pipeline_artifacts.py` bullet, add: `` - `tests/test_ranker.py` — `ranker.rank_lineups` scoring semantics (totals, 0.1 geomean floor, weighted rank order, ties). ``
  - In the sentence that follows the bullets, drop `ranking` and `ranker.py`, so it says the core export and leverage logic in `exporter.py` and `exposure_report.py` remains otherwise untested.
- `BACKLOG.md` line 151: change `* **Status**: Not Started` to `* **Status**: Rejected — measured negligible (0.13 s per 2,500 lineups); ranking semantics locked by tests instead (plan 007)`.

These files use CRLF line endings. Preserve them.

**Verify**:
- `git diff --stat` lists only `AGENTS.md`, `BACKLOG.md`, `docs/codebase/CONCERNS.md` and `docs/codebase/TESTING.md`, plus `plans/README.md` if you updated it.
- `Select-String -Path AGENTS.md -Pattern 'test_ranker.py' -SimpleMatch` → 1 match.

Commit: `docs: record ranker test coverage (plan 007)`.

## Test plan

- Step 1 adds 7 new tests in `tests/test_ranker.py`, modeled on `tests/test_utils.py`: plain functions, domain docstrings, no mocking, numbers you can check by hand.
- They cover:
  - totals summed over all 8 slots
  - a missing player counting as 0
  - the 0.1 geomean floor for 0%-owned and missing players
  - the rank order under default weights, with exact ranks and scores
  - weights being honored (the ownership-only order)
  - average ranks for ties
  - slot columns and `Lineup_ID` passing through unchanged
- Step 2 proves that two of the tests fail when the scoring really changes.
- Final check: `python -m pytest -q` → `49 passed`.

## Done criteria

- [ ] `python -m pytest -q tests/test_ranker.py` → `7 passed`
- [ ] `python -m pytest -q` → `49 passed`
- [ ] `git diff --stat eade9a1..HEAD -- src/` → no output (production code untouched)
- [ ] `Select-String -Path docs\codebase\TESTING.md,AGENTS.md -Pattern 'test_ranker.py' -SimpleMatch` → at least 2 matches
- [ ] `Select-String -Path BACKLOG.md -Pattern 'Rejected — measured negligible' -SimpleMatch` → 1 match
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any Step 1 test fails against the unmodified `ranker.py`. Do not edit the expected values or the ranker. Report the failing assertion and the actual value.
- Step 2's temporary edits do NOT make the named tests fail.
- `rank_lineups`' signature, or the `Own_Proj`, `Projection` or `Name + ID` column names, differ from the excerpt.
- The change appears to require editing `src/nba_optimizer/ranker.py`, other than the temporary edits in Step 2 that you revert.

## Maintenance notes

- Any intended change to ranking (a new metric, different tie handling, a different geomean floor) must update these tests in the same PR. That is the point of them. A reviewer should treat an unexplained change to an expected value as a red flag.
- `sort_values("Lineup_Score")` uses an unstable sort, so lineups with equal scores can come out in any order. The tests deliberately don't assert the order of tied scores. If that order ever matters (e.g. for reproducible exports), add `kind="stable"` and a test in the same PR.
- If vectorization is ever revisited (e.g. for pools of 100k+ lineups), these tests are the safety net. Re-measure first.

## Reconcile note (2026-10-15, after PR #63 review)

Review follow-ups in `23b5314` added `test_missing_weight_keys_default_to_one` (it pins the `weights.get(key, 1.0)` default) and a tie-order note in `test_tied_metrics_share_average_rank`'s docstring. So `tests/test_ranker.py` now has **8** tests and the full suite **50**, not the 7 / 49 stated above. The committed `tests/test_ranker.py` is canonical; the Step 1 code block is the original 7-test version.
