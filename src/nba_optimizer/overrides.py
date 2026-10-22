"""Typed player settings for stage runs (O-13): ``NAME=VALUE`` parsing,
player lookup, and projection/ownership overrides.

Players are named by DK ID or by the DKEntries ``Name`` (case-insensitive:
exact match first, then a unique substring).
"""

import difflib
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

# CLI flag -> merged player-pool column it overrides.
OVERRIDE_FIELDS = {"proj": "Projection", "own": "Own_Proj"}

# An inherited override carries while the export still has its recorded "from" value.
CARRY_TOL = 1e-6


def split_list(values: Optional[Iterable[str]]) -> List[str]:
    """Flatten repeated and ``;``-separated values: ["a; b", "c"] -> ["a", "b", "c"]."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out = []
    for value in values:
        out.extend(part.strip() for part in str(value).split(";") if part.strip())
    return out


def parse_assignment(text: str) -> Tuple[str, float]:
    """``"Name=55"`` -> ``("Name", 55.0)``. Raises ValueError on bad syntax."""
    player, sep, value = str(text).rpartition("=")
    player = player.strip()
    if not sep or not player or not value.strip():
        raise ValueError(f"bad setting {text!r}: expected PLAYER=VALUE")
    try:
        return player, float(value)
    except ValueError:
        raise ValueError(f"bad setting {text!r}: {value.strip()!r} is not a number") from None


def fmt_value(value: float) -> str:
    """55.0 -> "55", 50.5594555 -> "50.5594555"."""
    return f"{value:g}" if float(value).is_integer() else f"{value}"


def resolve_player(token: str, df_players: pd.DataFrame) -> Tuple[int, str]:
    """(dk_id, name) for a DK ID or a name in *df_players* (``ID``, ``Name`` columns).

    Raises ValueError for an unknown or ambiguous player, listing the candidates.
    """
    token = str(token).strip()
    ids = df_players["ID"].astype(str)
    names = df_players["Name"].astype(str)
    if token.isdigit():
        hit = df_players[ids == token]
        if len(hit):
            return int(token), str(hit["Name"].iloc[0])
        raise ValueError(f"unknown player ID {token}")

    lowered = names.str.lower()
    key = token.lower()
    for mask in (lowered == key, lowered.str.contains(key, regex=False)):
        hit = df_players[mask].drop_duplicates("ID")
        if len(hit) == 1:
            return int(hit["ID"].iloc[0]), str(hit["Name"].iloc[0])
        if len(hit) > 1:
            candidates = [f"{n} ({i})" for n, i in zip(hit["Name"], hit["ID"])]
            raise ValueError(f"ambiguous player {token!r}: matches {candidates}; use the DK ID")
    close = difflib.get_close_matches(token, names.unique().tolist(), n=5, cutoff=0.6)
    hint = f"; did you mean {close}?" if close else ""
    raise ValueError(f"unknown player {token!r}{hint}")


def resolve_overrides(df_players: pd.DataFrame, proj: Iterable[str], own: Iterable[str]) -> List[dict]:
    """Typed ``--proj``/``--own`` values as ``{dk_id, name, field, to}`` (a later one wins)."""
    resolved: Dict[Tuple[int, str], dict] = {}
    for flag, values in (("proj", proj), ("own", own)):
        for text in split_list(values):
            token, value = parse_assignment(text)
            dk_id, name = resolve_player(token, df_players)
            field = OVERRIDE_FIELDS[flag]
            resolved[(dk_id, field)] = {"dk_id": dk_id, "name": name, "field": field, "to": value}
    return list(resolved.values())


def current_value(df_players: pd.DataFrame, dk_id: int, field: str) -> Optional[float]:
    """The export's value of *field* for *dk_id*, or None if the player isn't in it."""
    hit = df_players.loc[df_players["ID"].astype(str) == str(dk_id), field]
    return float(hit.iloc[0]) if len(hit) else None


def apply_override_list(df_players: pd.DataFrame, overrides: List[dict]) -> Tuple[pd.DataFrame, List[dict]]:
    """Apply resolved overrides; return (new frame, records with ``from`` = the export's value)."""
    df = df_players.copy()
    applied = []
    for o in overrides:
        mask = df["ID"].astype(str) == str(o["dk_id"])
        if not mask.any():
            print(f"Warning: {o['name']} isn't in the projections; override ignored.")
            continue
        before = float(df.loc[mask, o["field"]].iloc[0])
        df.loc[mask, o["field"]] = float(o["to"])
        applied.append({"dk_id": int(o["dk_id"]), "name": o["name"], "field": o["field"],
                        "from": before, "to": float(o["to"])})
    return df, applied


def apply_overrides(df_players: pd.DataFrame, proj: List[str], own: List[str]) -> Tuple[pd.DataFrame, List[dict]]:
    """Parse, resolve and apply ``--proj``/``--own`` values to the merged player pool."""
    return apply_override_list(df_players, resolve_overrides(df_players, proj, own))
