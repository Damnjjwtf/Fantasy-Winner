"""Stat line -> fantasy points under this league's exact rules.

Pure functions. No I/O beyond reading league.toml, no network, no dependencies
outside the stdlib. Everything here is driven by league.toml so that changing a
league setting never means changing code.

On the 40+ yard bonus
---------------------
Yahoo carries BOTH of these as distinct scoring categories:

    any-play          "40+ Yard Receptions"        (Receiving 40 Yd Rec)
                      "40+ Yard Rushing Attempts"  (Rushing 40 Yd Att)
    touchdown-only    "40+ Yard Reception Touchdowns"  (Receiving 40 Yd TD)
                      "40+ Yard Passing Touchdowns"    (Passing 40 Yd TD)

Our settings screen reads "40+ Yard Receptions" and "40+ Yard Run" — the
any-play names, with no "Touchdowns" qualifier — so the bonus pays on ANY 40+
yard run or reception, scoring or not. That is `applies_to_td_only = false`.

The flag exists because this is the single highest-leverage number in the model:
if it were TD-only, every WR and RB ranking would shift. Flipping the flag
re-scores everything with no code change.

Note a 40+ yard touchdown is also a 40+ yard play, so `rush_40plus` counts it
too; `rush_40plus_td` is a strict subset used only when the flag is on.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

# Internal stat-line schema. sources.py maps upstream column names onto these;
# keeping the names ours means an upstream rename is a one-line mapping change
# rather than a rewrite of the scoring rules.
OFFENSE_KEYS = (
    "passing_yards", "passing_tds", "interceptions", "pick_sixes", "passing_2pt",
    "rushing_yards", "rushing_tds", "rushing_2pt", "rush_40plus", "rush_40plus_td",
    "receptions", "receiving_yards", "receiving_tds", "receiving_2pt",
    "recv_40plus", "recv_40plus_td",
    "fumbles_lost", "return_tds", "offensive_fumble_return_tds",
)

DST_KEYS = (
    "sacks", "interceptions", "fumble_recoveries", "tds", "safeties",
    "blocked_kicks", "return_tds", "extra_points_returned", "points_allowed",
)


def load_rules(path: str | Path = "league.toml") -> dict:
    """Parse league.toml. The only I/O in this module."""
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def points_allowed_points(points_allowed: int, rules: dict) -> float:
    """DST points for a points-allowed total, via the league's tier table.

    Tiers are ordered ascending by `max` and matched on the first tier the
    total fits in, so the table in league.toml reads exactly like Yahoo's
    settings screen.
    """
    for tier in rules["scoring"]["dst"]["points_allowed"]:
        if points_allowed <= tier["max"]:
            return float(tier["points"])
    raise ValueError(f"no points-allowed tier matched {points_allowed}")


def score_offense(stats: dict, rules: dict) -> float:
    """Fantasy points for one offensive player's stat line."""
    p = rules["scoring"]["passing"]
    ru = rules["scoring"]["rushing"]
    re = rules["scoring"]["receiving"]
    b = rules["scoring"]["bonus"]
    m = rules["scoring"]["misc"]
    g = stats.get

    total = 0.0

    # Passing. A pick six is scored twice on purpose: Yahoo counts it as an
    # interception AND applies the pick-six penalty, so it costs -6 here.
    total += g("passing_yards", 0) * p["yards"]
    total += g("passing_tds", 0) * p["td"]
    total += g("interceptions", 0) * p["interception"]
    total += g("pick_sixes", 0) * p["pick_six"]
    total += g("passing_2pt", 0) * p["two_pt"]

    # Rushing
    total += g("rushing_yards", 0) * ru["yards"]
    total += g("rushing_tds", 0) * ru["td"]
    total += g("rushing_2pt", 0) * ru["two_pt"]

    # Receiving
    total += g("receptions", 0) * re["reception"]
    total += g("receiving_yards", 0) * re["yards"]
    total += g("receiving_tds", 0) * re["td"]
    total += g("receiving_2pt", 0) * re["two_pt"]

    # 40+ yard bonuses — see the module docstring.
    td_only = b["applies_to_td_only"]
    rush_big = g("rush_40plus_td", 0) if td_only else g("rush_40plus", 0)
    recv_big = g("recv_40plus_td", 0) if td_only else g("recv_40plus", 0)
    total += rush_big * b["rush_40plus"]
    total += recv_big * b["recv_40plus"]

    # Misc — the categories generic models tend to drop.
    total += g("fumbles_lost", 0) * m["fumble_lost"]
    total += g("return_tds", 0) * m["return_td"]
    total += g("offensive_fumble_return_tds", 0) * m["offensive_fumble_return_td"]

    return round(total, 2)


def score_dst(stats: dict, rules: dict) -> float:
    """Fantasy points for one defense/special-teams unit.

    `points_allowed` is required rather than defaulted. Defaulting it to 0
    would score a missing value as a shutout — the single highest tier — so a
    bye week or a failed ID join would silently promote a unit to the top of
    the DST board. Every other stat sensibly defaults to zero; this one does
    not, so it is an error instead.
    """
    if "points_allowed" not in stats:
        raise ValueError(
            "score_dst requires 'points_allowed'; omitting it would score as a shutout"
        )
    d = rules["scoring"]["dst"]
    g = stats.get

    total = 0.0
    total += g("sacks", 0) * d["sack"]
    total += g("interceptions", 0) * d["interception"]
    total += g("fumble_recoveries", 0) * d["fumble_recovery"]
    total += g("tds", 0) * d["td"]
    total += g("safeties", 0) * d["safety"]
    total += g("blocked_kicks", 0) * d["block_kick"]
    total += g("return_tds", 0) * d["return_td"]
    total += g("extra_points_returned", 0) * d["extra_point_returned"]
    total += points_allowed_points(g("points_allowed", 0), rules)

    return round(total, 2)
