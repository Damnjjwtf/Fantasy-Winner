"""Tests for board construction.

These exercise the pure logic — tiering, baselines, projection — on synthetic
frames, so they need no network and pin the behaviours that were actually got
wrong during the build.
"""

import polars as pl
import pytest

from fw.board import assign_tiers, project, replacement_baselines
from fw.scoring import load_rules


@pytest.fixture(scope="module")
def rules():
    return load_rules("league.toml")


def _board(position: str, vbds: list[float]) -> pl.DataFrame:
    return pl.DataFrame({
        "player": [f"{position}{i}" for i in range(len(vbds))],
        "position": [position] * len(vbds),
        "vbd": vbds,
    })


def test_elite_outlier_gets_its_own_tier():
    """A player far above the field must not be lumped in with it."""
    b = assign_tiers(_board("WR", [200.0, 90.0, 88.0, 86.0, 84.0, 82.0]), gap_mult=2.0)
    top = b.filter(pl.col("player") == "WR0")["tier"][0]
    assert (b.filter(pl.col("tier") == top).height) == 1


def test_steep_head_does_not_swallow_the_tail():
    """The bug that made the first two tiering attempts useless.

    Huge gaps at the top inflate any position-wide statistic. With a global
    threshold, 68 of 75 receivers landed in one tier spanning +77 to -90 VBD —
    a board that looks correct if you only ever read the top.
    """
    vbds = [220.0, 180.0, 142.0, 121.0] + [100.0 - i * 3.0 for i in range(40)]
    b = assign_tiers(_board("WR", vbds), gap_mult=2.0)
    biggest = max(n for _, n in b["tier"].value_counts().rows())
    assert biggest <= 8, f"a tier of {biggest} is too coarse to read on the clock"


def test_flat_region_is_still_split():
    """A smooth decline has no cliffs, but must stay readable anyway.

    17 tight ends declining steadily across 60 VBD points is not one tier,
    even though no single gap between them is a cliff.
    """
    b = assign_tiers(_board("TE", [60.0 - i * 3.5 for i in range(18)]), gap_mult=2.0)
    assert b["tier"].n_unique() > 1
    assert max(n for _, n in b["tier"].value_counts().rows()) <= 8


def test_tiers_never_improve_as_value_falls():
    """Tier numbers must increase monotonically down the board."""
    vbds = [150.0, 120.0, 119.0, 80.0, 79.0, 40.0, 39.0, 38.0, 10.0]
    b = assign_tiers(_board("RB", vbds), gap_mult=2.0).sort("vbd", descending=True)
    tiers = b["tier"].to_list()
    assert tiers == sorted(tiers)


def test_no_kicker_baseline(rules):
    """This league has no K slot, so a K baseline would corrupt every VBD."""
    proj = pl.DataFrame({
        "player": [f"p{i}" for i in range(120)],
        "position": ["RB"] * 40 + ["WR"] * 40 + ["TE"] * 20 + ["QB"] * 20,
        "proj_points": [300.0 - i for i in range(120)],
    })
    assert "K" not in replacement_baselines(proj, rules)


def test_flex_lowers_the_baseline(rules):
    """FLEX means more RB/WR are startable, so replacement is deeper.

    If the flex spots were ignored, the baseline would sit at the dedicated
    starter count and every flex-eligible player's VBD would be overstated.
    """
    proj = pl.DataFrame({
        "player": [f"p{i}" for i in range(200)],
        "position": ["RB"] * 100 + ["WR"] * 100,
        "proj_points": [300.0 - i * 0.5 for i in range(100)] * 2,
    })
    base = replacement_baselines(proj, rules)
    teams = rules["league"]["teams"]
    dedicated_rb = rules["roster"]["starters"]["RB"] * teams
    rb_at_dedicated = 300.0 - (dedicated_rb - 1) * 0.5
    assert base["RB"] < rb_at_dedicated, "flex spots were not allocated"


def test_project_maps_adp_rank_to_curve():
    """Projection comes from rank within position, not raw ADP number."""
    adp = pl.DataFrame({
        "player": ["a", "b", "c"], "position": ["WR"] * 3,
        "team": ["X"] * 3, "adp": [5.0, 12.0, 30.0], "times_drafted": [1, 1, 1],
    })
    curve = pl.DataFrame({
        "position": ["WR"] * 3, "pos_rank": [1, 2, 3], "proj_points": [300.0, 250.0, 200.0],
    })
    out = project(adp, curve).sort("adp")
    assert out["proj_points"].to_list() == [300.0, 250.0, 200.0]


def test_project_drops_players_beyond_the_curve():
    """Deep ADP rows with no historical analogue must not become nulls."""
    adp = pl.DataFrame({
        "player": ["a", "b"], "position": ["WR"] * 2,
        "team": ["X"] * 2, "adp": [5.0, 12.0], "times_drafted": [1, 1],
    })
    curve = pl.DataFrame({"position": ["WR"], "pos_rank": [1], "proj_points": [300.0]})
    assert project(adp, curve).height == 1
