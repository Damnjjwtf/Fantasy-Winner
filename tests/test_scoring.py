"""Golden tests for scoring.py.

Every expected value below is hand-computed in the comment above it. If one of
these fails, the arithmetic in the comment is the spec — fix the code, not the
test, unless league.toml genuinely changed.
"""

import pytest

from fw.scoring import load_rules, points_allowed_points, score_dst, score_offense


@pytest.fixture(scope="module")
def rules():
    return load_rules("league.toml")


def test_wr_with_long_non_scoring_catch(rules):
    """The bonus case that decides the whole board.

    8 rec = 8.0 | 112 yds x 0.1 = 11.2 | 1 TD = 6.0 | one 44-yd catch = +2.0
    The 44-yarder did NOT score, and it still pays.
    """
    line = {
        "receptions": 8,
        "receiving_yards": 112,
        "receiving_tds": 1,
        "recv_40plus": 1,
        "recv_40plus_td": 0,
    }
    assert score_offense(line, rules) == pytest.approx(27.2)


def test_same_line_under_td_only_reading(rules):
    """Flipping the flag drops the bonus: 27.2 - 2.0 = 25.2.

    This is the delta the whole 40-yard question is worth on one catch. It is
    asserted so that flipping applies_to_td_only is a provable change rather
    than a hopeful one.
    """
    td_only = {**rules}
    td_only["scoring"] = {**rules["scoring"]}
    td_only["scoring"]["bonus"] = {**rules["scoring"]["bonus"], "applies_to_td_only": True}
    line = {
        "receptions": 8,
        "receiving_yards": 112,
        "receiving_tds": 1,
        "recv_40plus": 1,
        "recv_40plus_td": 0,
    }
    assert score_offense(line, td_only) == pytest.approx(25.2)


def test_qb_pick_six_stacks(rules):
    """A 280-yard, 2-TD game is nearly worthless here once turnovers land.

    280 x 0.04 = 11.2 | 2 TD x 4 = 8.0 | 2 INT x -2 = -4.0 | 1 pick six = -4.0
    The pick six is counted as an interception AND penalised: -6 for that play.
    """
    line = {
        "passing_yards": 280,
        "passing_tds": 2,
        "interceptions": 2,
        "pick_sixes": 1,
    }
    assert score_offense(line, rules) == pytest.approx(11.2)


def test_rb_negative_game(rules):
    """Negative points are enabled, so a bad game really is negative.

    8 yds x 0.1 = 0.8 | 2 fumbles lost x -2 = -4.0
    """
    line = {"rushing_yards": 8, "rushing_tds": 0, "fumbles_lost": 2}
    assert score_offense(line, rules) == pytest.approx(-3.2)


def test_rb_long_touchdown_counts_once_as_bonus(rules):
    """A 45-yard TD run is both a TD and a 40+ yard attempt, not two bonuses.

    62 yds x 0.1 = 6.2 | 1 TD = 6.0 | one 40+ attempt = +2.0
    """
    line = {
        "rushing_yards": 62,
        "rushing_tds": 1,
        "rush_40plus": 1,
        "rush_40plus_td": 1,
    }
    assert score_offense(line, rules) == pytest.approx(14.2)


def test_dst_shutout(rules):
    """The generous top tier is why elite DST matters here.

    0 PA = 10.0 | 4 sacks = 4.0 | 2 INT x 2 = 4.0 | 1 FR x 2 = 2.0 | 1 TD = 6.0
    """
    line = {
        "points_allowed": 0,
        "sacks": 4,
        "interceptions": 2,
        "fumble_recoveries": 1,
        "tds": 1,
    }
    assert score_dst(line, rules) == pytest.approx(26.0)


def test_dst_blowout_loss(rules):
    """35+ allowed is -4, and one sack does not save it.

    35 PA = -4.0 | 1 sack = 1.0
    """
    assert score_dst({"points_allowed": 35, "sacks": 1}, rules) == pytest.approx(-3.0)


@pytest.mark.parametrize(
    "pa,expected",
    [(0, 10.0), (1, 7.0), (6, 7.0), (7, 4.0), (13, 4.0), (14, 2.0), (20, 2.0),
     (21, 0.0), (27, 0.0), (28, -2.0), (34, -2.0), (35, -4.0), (60, -4.0)],
)
def test_points_allowed_tier_boundaries(pa, expected, rules):
    """Every boundary from the settings screen, including both sides of each."""
    assert points_allowed_points(pa, rules) == pytest.approx(expected)


def test_misc_categories_are_not_dropped(rules):
    """Return TD and offensive fumble return TD are free points most models miss.

    1 return TD = 6.0 | 1 offensive fumble return TD = 6.0
    """
    line = {"return_tds": 1, "offensive_fumble_return_tds": 1}
    assert score_offense(line, rules) == pytest.approx(12.0)


def test_empty_line_is_zero(rules):
    assert score_offense({}, rules) == 0.0


def test_dst_requires_points_allowed(rules):
    """A missing points-allowed must fail loudly, not score as a shutout.

    Defaulting it to 0 would award the top tier (10 pts) to any unit whose row
    is missing the field, silently floating broken rows to the top of the board.
    """
    with pytest.raises(ValueError, match="points_allowed"):
        score_dst({"sacks": 3}, rules)


def test_dst_zero_points_allowed_still_works(rules):
    """An explicit 0 is a real shutout and must still score the top tier."""
    assert score_dst({"points_allowed": 0}, rules) == pytest.approx(10.0)
