"""ADP + history -> projected points -> VBD -> tiers -> data/board.csv.

Method
------
We do not try to out-project the market on individual players. Consensus ADP
already encodes thousands of drafters' opinions about who is good; our edge is
that this league is not scored like the market's. So:

1. Score three seasons of real stat lines under OUR rules (scoring.py).
2. Within each season and position, rank players by those points and average
   across seasons. That yields a **points-by-positional-finish curve**: what the
   Nth-best WR actually scores in a league like ours.
3. Rank 2026 ADP within position and read each player's projection off that
   curve. The market supplies the ordering; history supplies the scale.

This is honest about what it does and does not know. It will not call a
breakout the market missed. It will correctly price the fact that our 40+ yard
bonus, full PPR, punitive QB turnovers and generous DST tiers make positional
scarcity here different from generic PPR.

VBD is then points above the last startable player at each position, with the
FLEX allocated from the data rather than a guessed split.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from fw.scoring import load_rules, points_allowed_points, score_dst, score_offense
from fw.sources import UNAVAILABLE, load_adp, normalize_name, player_meta, season_stats

OFFENSE = ("QB", "RB", "WR", "TE")
BOARD = Path("data/board.csv")

# Every ordering in this module must be totally determined by the data. Polars
# sorts are not stable by default, and replacement-level players sit at exactly
# vbd 0.0, so ties were being broken arbitrarily: the same inputs produced
# boards that differed by a few rows between runs. Harmless-looking, but it
# means the board you rebuild on draft day need not match the sheet you printed
# and rehearsed with.
#
# Player name alone already gives a total order; ADP is preferred ahead of it
# where available so ties fall in market order rather than alphabetically. The
# helper adapts rather than demanding an `adp` column from functions that have
# no other use for one.
def _tiebreak(df: pl.DataFrame) -> list[str]:
    return [c for c in ("adp", "player") if c in df.columns]


def positional_curve(seasons: list[int], rules: dict) -> pl.DataFrame:
    """Average points scored by the Nth-best player at each position.

    Averaged across seasons so one freak year does not define a rank. This is
    the only place league scoring meets historical production.
    """
    stats = season_stats(seasons).filter(pl.col("position").is_in(OFFENSE))
    scored = stats.with_columns(
        pl.Series("points", [score_offense(r, rules) for r in stats.to_dicts()])
    )
    return (
        scored.with_columns(
            pl.col("points").rank("ordinal", descending=True)
            .over(["season", "position"]).alias("pos_rank")
        )
        .group_by(["position", "pos_rank"])
        .agg(pl.col("points").mean().alias("proj_points"))
        .sort(["position", "pos_rank"])
    )


def dst_curve(seasons: list[int], rules: dict) -> pl.DataFrame:
    """Same curve for team defences.

    Points allowed is per-game in the tier table, so it is summed week by week
    from the schedule rather than applied once to a season total — a team that
    allows 0 twice and 35 twice is worth far more than its average suggests.

    Safeties and some return touchdowns are not cleanly available in team_stats.
    They are rare and roughly uniform across teams, so they shift every defence
    about equally and do not change the ordering VBD depends on.
    """
    import nflreadpy as nfl

    games = nfl.load_schedules(seasons).filter(pl.col("game_type") == "REG")
    # One row per team per game, with what that team's defence allowed.
    allowed = pl.concat([
        games.select(pl.col("season"), pl.col("home_team").alias("team"),
                     pl.col("away_score").alias("pa")),
        games.select(pl.col("season"), pl.col("away_team").alias("team"),
                     pl.col("home_score").alias("pa")),
    ]).drop_nulls("pa")

    pa_points = (
        allowed.with_columns(
            pl.Series("wk_pts", [points_allowed_points(int(p), rules) for p in allowed["pa"]])
        )
        .group_by(["season", "team"])
        .agg(pl.col("wk_pts").sum().alias("pa_points"))
    )

    ts = nfl.load_team_stats(seasons, summary_level="reg")
    events = ts.select(
        pl.col("season"), pl.col("team"),
        pl.col("def_sacks").fill_null(0).alias("sacks"),
        pl.col("def_interceptions").fill_null(0).alias("interceptions"),
        pl.col("fumble_recovery_opp").fill_null(0).alias("fumble_recoveries"),
        pl.col("def_tds").fill_null(0).alias("tds"),
        (pl.col("def_punt_blocks").fill_null(0) + pl.col("def_pat_blocks").fill_null(0)
         + pl.col("def_fg_blocks").fill_null(0)).alias("blocked_kicks"),
    )

    rows = events.join(pa_points, on=["season", "team"]).to_dicts()
    for r in rows:
        # points_allowed is handled per-week above, so it is passed as 0 here and
        # the weekly total added back. score_dst still requires the key.
        r["points"] = score_dst({**r, "points_allowed": 21}, rules) \
            - points_allowed_points(21, rules) + r["pa_points"]

    scored = pl.DataFrame(rows).with_columns(pl.lit("DEF").alias("position"))
    return (
        scored.with_columns(
            pl.col("points").rank("ordinal", descending=True)
            .over("season").alias("pos_rank")
        )
        .group_by(["position", "pos_rank"])
        .agg(pl.col("points").mean().alias("proj_points"))
        .sort("pos_rank")
    )


def project(adp: pl.DataFrame, curve: pl.DataFrame) -> pl.DataFrame:
    """Attach a projection to each ADP row via its rank within position."""
    ranked = adp.sort(_tiebreak(adp)).with_columns(
        pl.col("adp").rank("ordinal").over("position").alias("pos_rank")
    )
    return ranked.join(curve, on=["position", "pos_rank"], how="left").drop_nulls("proj_points")


def replacement_baselines(proj: pl.DataFrame, rules: dict) -> dict[str, float]:
    """Points of the last startable player at each position.

    Dedicated starters come straight from the roster config. The FLEX spots are
    then allocated by taking the best remaining RB/WR/TE across the league — so
    the split reflects what this scoring actually rewards, rather than a
    hard-coded "flex is usually 60% RB" that would bake in someone else's league.
    """
    teams = rules["league"]["teams"]
    starters = rules["roster"]["starters"]
    flex_eligible = rules["roster"]["flex_eligible"]

    dedicated = {pos: starters.get(pos, 0) * teams for pos in ("QB", "RB", "WR", "TE", "DEF")}

    pool = (
        proj.filter(pl.col("position").is_in(flex_eligible))
        .sort(_tiebreak(proj))
        .with_columns(pl.col("proj_points").rank("ordinal", descending=True)
                      .over("position").alias("within"))
        .filter(pl.col("within") > pl.col("position").replace_strict(dedicated, default=0))
        .sort(["proj_points"] + _tiebreak(proj),
              descending=[True] + [False] * len(_tiebreak(proj)))
        .head(starters.get("FLEX", 0) * teams)
    )
    for pos, n in pool["position"].value_counts().rows():
        dedicated[pos] += n

    baselines = {}
    for pos, n in dedicated.items():
        at_pos = proj.filter(pl.col("position") == pos).sort(
            ["proj_points"] + _tiebreak(proj),
            descending=[True] + [False] * len(_tiebreak(proj)))
        if at_pos.height == 0 or n == 0:
            continue
        baselines[pos] = float(at_pos["proj_points"][min(n, at_pos.height) - 1])
    return baselines


def assign_tiers(board: pl.DataFrame, gap_mult: float, max_tier_size: int = 8) -> pl.DataFrame:
    """Split each position into tiers by recursively cutting at its biggest gap.

    One mechanism, two jobs. A segment is split at its largest internal gap when
    EITHER that gap is a genuine cliff (more than `gap_mult` times the position's
    median gap) OR the segment has grown past `max_tier_size` and stopped being
    useful to read.

    Both halves are needed, and each fixes a way the earlier attempts failed:

    * A pure global gap threshold tiered the elite end correctly and then put
      68 of 75 receivers in one tier spanning +77 to -90 VBD. The enormous
      top-end gaps (WR1 to WR2 was 38 points) inflate any position-wide
      statistic until nothing below them can clear it.
    * Making the threshold local (a rolling median) fixed the tail but broke
      differently: a window centred on the top of a flat region still straddles
      the steep region above it, washing out real 7-point breaks among tight
      ends whose neighbours were separated by 2.

    Recursive splitting sidesteps both, because each cut re-evaluates only the
    span it applies to. The size cap is an explicit admission that a genuinely
    smooth stretch has no cliffs to find — we cut it at its weakest point
    anyway, because "these 17 players decline steadily over 60 points" still
    needs to be readable at 11pm on a 60-second clock.
    """
    out = []
    for pos in sorted(board["position"].unique().to_list()):
        tb = _tiebreak(board)
        grp = board.filter(pl.col("position") == pos).sort(
            ["vbd"] + tb, descending=[True] + [False] * len(tb))
        vals = grp["vbd"].to_list()
        n = len(vals)
        gaps = [vals[i] - vals[i + 1] for i in range(n - 1)]
        cliff = gap_mult * (pl.Series(gaps).median() or 0.0) if gaps else 0.0

        cuts: list[int] = []
        pending = [(0, n)]
        while pending:
            lo, hi = pending.pop()
            if hi - lo < 2:
                continue
            span = gaps[lo:hi - 1]
            best = max(range(len(span)), key=span.__getitem__)
            if span[best] <= cliff and (hi - lo) <= max_tier_size:
                continue
            cut = lo + best + 1
            cuts.append(cut)
            pending += [(lo, cut), (cut, hi)]

        tiers, tier = [], 1
        for i in range(n):
            if i in set(cuts):
                tier += 1
            tiers.append(tier)
        out.append(grp.with_columns(pl.Series("tier", tiers)))
    tb = _tiebreak(board)
    return pl.concat(out).sort(["vbd"] + tb, descending=[True] + [False] * len(tb))


def attach_status(board: pl.DataFrame) -> pl.DataFrame:
    """Mark players whose roster status says they are not available to play.

    A player on IR or PUP is otherwise indistinguishable from a healthy one on
    this board — same ADP, same projection, same tier — which is exactly the
    mistake worth spending a query to avoid. Left as a flag rather than a
    filter: statuses change, and a player you know is coming back in week 3 may
    still be worth a late pick. The board says what it knows; you decide.
    """
    meta = player_meta().select("join_key", "status").unique("join_key")
    keyed = board.with_columns(
        pl.col("player").map_elements(normalize_name, return_dtype=pl.String).alias("join_key")
    )
    return (
        keyed.join(meta, on="join_key", how="left")
        .with_columns(
            pl.col("status")
            .replace_strict(UNAVAILABLE, default=None)
            .alias("unavailable")
        )
        .drop("join_key")
    )


def build(adp_path: str | Path, rules: dict) -> pl.DataFrame:
    seasons = rules["board"]["history_seasons"]
    curve = pl.concat([positional_curve(seasons, rules), dst_curve(seasons, rules)])
    proj = project(load_adp(adp_path), curve)

    baselines = replacement_baselines(proj, rules)
    board = proj.with_columns(
        (pl.col("proj_points")
         - pl.col("position").replace_strict(baselines, default=None)).alias("vbd")
    ).drop_nulls("vbd")

    tiered = assign_tiers(board.sort(_tiebreak(board)), rules["board"]["tier_gap_mult"])
    return attach_status(tiered).with_columns(
        pl.col("proj_points").round(1), pl.col("vbd").round(1)
    ).with_row_index("overall_rank", offset=1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the VBD board. Slot-agnostic.")
    ap.add_argument("--adp", required=True, help="cached FFC ADP json (see sources.fetch_adp)")
    ap.add_argument("--out", default=str(BOARD))
    ap.add_argument("--config", default="league.toml")
    args = ap.parse_args()

    rules = load_rules(args.config)
    board = build(args.adp, rules)

    out = Path(args.out)
    # Never overwrite a known-good board in place: the last ADP refresh happens
    # on draft day, and a bad board at 10pm with no fallback is unrecoverable.
    if out.exists():
        backup = out.with_suffix(".prev.csv")
        out.replace(backup)
        print(f"previous board kept at {backup}")
    out.parent.mkdir(parents=True, exist_ok=True)
    board.write_csv(out)
    print(f"wrote {out} ({board.height} players)")


if __name__ == "__main__":
    main()
