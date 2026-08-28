"""Upstream data -> data/raw/. The only module that touches the network.

Two sources, deliberately:

* **ADP** from the Fantasy Football Calculator REST API — free for personal
  use, attribution required, and explicitly not to be called frequently, so
  every fetch is cached to disk and re-fetch is opt-in.
* **History and player metadata** from nflreadpy (nflverse).

Sleeper is NOT used. It was in the original plan for player metadata, but
`nflreadpy.load_players()` already carries name, position, team and status, and
nflreadpy is a dependency regardless. Dropping Sleeper removes a network call,
a rate limit and an attribution obligation for nothing lost.

With only one HTTP endpoint left, the stdlib covers it — no `httpx`/`requests`.

Nothing here is imported by track.py. Draft night never calls this module.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import polars as pl

RAW = Path("data/raw")

# Attribution required by FFC's terms of use. Surfaced on the printed sheet.
ADP_ATTRIBUTION = "ADP data provided by Fantasy Football Calculator"
_ADP_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams={teams}&year={season}"

# nflverse player_stats column -> our internal scoring schema (see scoring.py).
# Keeping the mapping in one dict means an upstream rename is a one-line fix.
_STAT_MAP = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "passing_interceptions": "interceptions",
    "passing_2pt_conversions": "passing_2pt",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "rushing_2pt_conversions": "rushing_2pt",
    "rushing_40": "rush_40plus",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "receiving_tds": "receiving_tds",
    "receiving_2pt_conversions": "receiving_2pt",
    "receiving_40": "recv_40plus",
    "special_teams_tds": "return_tds",
    "fumble_recovery_tds": "offensive_fumble_return_tds",
}

# Fumbles lost arrive split by how the fumble happened; our scoring wants one
# number, and a QB's strip-sacks count just as much as a runner's.
_FUMBLE_COLS = ("rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost")


def fetch_adp(season: int, teams: int, fmt: str = "ppr", *, force: bool = False) -> Path:
    """Download ADP to data/raw/, returning the cached path.

    Idempotent by default: an existing cache is reused rather than re-fetched,
    because FFC asks not to be called frequently and because a draft-week
    refresh should be a deliberate act, not a side effect of running a script.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / f"adp_{season}_{teams}team_{fmt}.json"
    if dest.exists() and not force:
        return dest

    url = _ADP_URL.format(fmt=fmt, teams=teams, season=season)
    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.loads(resp.read().decode())

    if payload.get("status") != "Success":
        raise RuntimeError(f"FFC returned status={payload.get('status')!r} for {url}")
    if not payload.get("players"):
        raise RuntimeError(f"FFC returned no players for {url}")

    # Written only after validation, so a bad response never replaces a good cache.
    dest.write_text(json.dumps(payload, indent=2))
    return dest


def load_adp(path: str | Path) -> pl.DataFrame:
    """Parse a cached FFC payload into name/position/team/adp."""
    payload = json.loads(Path(path).read_text())
    return pl.DataFrame(payload["players"]).select(
        pl.col("name").alias("player"),
        pl.col("position"),
        pl.col("team"),
        pl.col("adp").cast(pl.Float64),
        pl.col("times_drafted").cast(pl.Int64),
    )


def pick_sixes(seasons: list[int]) -> pl.DataFrame:
    """Interceptions returned for a touchdown, per passer per season.

    Not available in player_stats — it only carries total interceptions — so it
    is derived from play-by-play. This league penalises a pick six on top of the
    interception, so without this a gunslinger QB scores 4 points too high for
    every one he throws.
    """
    import nflreadpy as nfl

    pbp = nfl.load_pbp(seasons)
    return (
        pbp.filter((pl.col("interception") == 1) & (pl.col("return_touchdown") == 1))
        .group_by(["season", "passer_player_id"])
        .len()
        .rename({"passer_player_id": "player_id", "len": "pick_sixes"})
    )


def season_stats(seasons: list[int]) -> pl.DataFrame:
    """Regular-season totals per player, in scoring.py's schema.

    The 40+ yard bonus counts come straight from nflverse's `rushing_40` and
    `receiving_40`, which are counts of 40+ yard plays — exactly the stat our
    league's any-play bonus pays on. No play-by-play derivation needed.
    """
    import nflreadpy as nfl

    df = nfl.load_player_stats(seasons, summary_level="reg")
    present = {src: dst for src, dst in _STAT_MAP.items() if src in df.columns}
    missing = set(_STAT_MAP) - set(present)
    if missing:
        raise KeyError(f"nflverse schema changed; missing columns: {sorted(missing)}")

    fumbles = [c for c in _FUMBLE_COLS if c in df.columns]
    return (
        df.select(
            pl.col("player_id"),
            pl.col("player_display_name").alias("player"),
            pl.col("position"),
            pl.col("season"),
            *[pl.col(src).fill_null(0).alias(dst) for src, dst in present.items()],
            pl.sum_horizontal([pl.col(c).fill_null(0) for c in fumbles]).alias("fumbles_lost"),
        )
        .join(pick_sixes(seasons), on=["season", "player_id"], how="left")
        .with_columns(pl.col("pick_sixes").fill_null(0))
    )


# Roster statuses that mean a player is not currently available to play.
# nflverse `load_injuries` only covers in-season game-status reports (2009-2025),
# so during draft week there is no structured feed for "who is hurt going into
# drafts". Roster status is what exists, and it catches the severe end: a player
# on IR or PUP must never sit on the board looking like a healthy pick.
#
# It does NOT catch the soft cases — "recovering, expected back week 4",
# "limited in camp". Those still need a human reading the news, which is what
# data/notes.toml is for.
UNAVAILABLE = {
    "RES": "injured reserve",
    "PUP": "physically unable to perform",
    "SUS": "suspended",
    "NWT": "not with team",
    "RET": "retired",
    "RSN": "reserve (non-football)",
    "RSR": "reserve (retired)",
    "CUT": "not on a roster",
}


def normalize_name(name: str) -> str:
    """Join key for ADP names against nflverse names.

    FFC and nflverse punctuate differently (Ja'Marr vs JaMarr, A.J. vs AJ), and
    suffixes drift, so both sides are reduced to letters only.
    """
    base = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    for suffix in (" jr", " sr", " ii", " iii", " iv", " v"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return "".join(ch for ch in base if ch.isalnum())


def player_meta() -> pl.DataFrame:
    """Name/position/team/roster status, for attaching availability to the board."""
    import nflreadpy as nfl

    df = nfl.load_players()
    if "last_season" in df.columns:
        # Decades of retired players share names with current ones; restricting
        # to recent activity stops a 1990s namesake supplying a status.
        df = df.filter(pl.col("last_season") >= 2025)
    return df.select(
        pl.col("gsis_id").alias("player_id"),
        pl.col("display_name").alias("player"),
        pl.col("position"),
        pl.col("latest_team").alias("team"),
        pl.col("status"),
    ).with_columns(
        pl.col("player").map_elements(normalize_name, return_dtype=pl.String).alias("join_key")
    )
