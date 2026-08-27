"""Tests for the ingest layer.

The ADP path is tested entirely against a committed fixture — no network — so
these stay green on a plane, in CI, and in a web container whose egress proxy
blocks fantasyfootballcalculator.com.
"""

import json

import pytest

from fw.sources import ADP_ATTRIBUTION, _STAT_MAP, load_adp

FIXTURE = "tests/fixtures/adp_ppr_12team.json"


def test_load_adp_parses_fixture():
    df = load_adp(FIXTURE)
    assert df.height == 6
    assert df.columns == ["player", "position", "team", "adp", "times_drafted"]


def test_load_adp_preserves_draft_order():
    """ADP must survive parsing as a sortable float, not a formatted string.

    FFC also ships "adp_formatted" ("1.01" style round.pick), which sorts
    lexically and would silently mis-order the board.
    """
    df = load_adp(FIXTURE).sort("adp")
    assert df["player"][0] == "Ja'Marr Chase"
    assert df["adp"].dtype.is_float()


def test_defense_rows_survive():
    """DEF is a draftable position here, and elite DST is worth more than
    consensus in this league, so it must not be filtered out as a non-player."""
    df = load_adp(FIXTURE)
    assert "DEF" in df["position"].to_list()


def test_no_kicker_in_this_league():
    """No K slot on the roster, so a K appearing in the board is a bug."""
    assert "K" not in load_adp(FIXTURE)["position"].to_list()


def test_attribution_string_is_present():
    """FFC's terms require attribution; the sheet renders this string."""
    assert "Fantasy Football Calculator" in ADP_ATTRIBUTION


def test_stat_map_covers_every_scored_category():
    """Guards against a mapping that silently drops a scoring category.

    Anything scored in league.toml but absent from both the map and the
    derived columns would score as zero for every player — invisible, and
    wrong in the same direction for everyone.
    """
    derived = {"fumbles_lost", "pick_sixes"}
    mapped = set(_STAT_MAP.values()) | derived
    required = {
        "passing_yards", "passing_tds", "interceptions", "pick_sixes", "passing_2pt",
        "rushing_yards", "rushing_tds", "rushing_2pt", "rush_40plus",
        "receptions", "receiving_yards", "receiving_tds", "receiving_2pt", "recv_40plus",
        "fumbles_lost", "return_tds", "offensive_fumble_return_tds",
    }
    assert required <= mapped, f"unmapped scoring categories: {sorted(required - mapped)}"


def test_malformed_payload_is_rejected(tmp_path):
    """A failed fetch must not be parsed as an empty board."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"status": "Success", "players": []}))
    with pytest.raises(Exception):
        load_adp(bad).select("player").item()
