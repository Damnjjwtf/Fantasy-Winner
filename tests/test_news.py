"""Tests for the pre-draft news reader.

All offline — feeds are fixtures. This module never runs on draft night.
"""

from pathlib import Path

from fw.news import load_board_names, match, normalize_name, parse_feed

RSS = Path("tests/fixtures/feed_rss.xml")
ATOM = Path("tests/fixtures/feed_atom.xml")


def _players(*names):
    return [(n, normalize_name(n), "WR") for n in names]


def test_parses_rss_two_point_oh():
    entries = parse_feed(RSS.read_text())
    assert len(entries) == 3
    assert entries[0]["title"].startswith("Ja'Marr Chase")
    assert entries[0]["link"] == "https://example.test/chase"


def test_parses_atom_too():
    """Feeds differ and you should not have to care which shape yours is."""
    entries = parse_feed(ATOM.read_text())
    assert len(entries) == 1
    assert "Puka Nacua" in entries[0]["title"]
    assert entries[0]["link"] == "https://example.test/nacua"


def test_matches_players_across_punctuation():
    """The feed writes Ja'Marr; the board may not punctuate it identically."""
    hits = match(parse_feed(RSS.read_text()), _players("Ja'Marr Chase", "Bijan Robinson"))
    assert set(hits) == {"Ja'Marr Chase", "Bijan Robinson"}


def test_ignores_entries_with_no_board_players():
    """A weather roundup must not be reported as news about your team."""
    hits = match(parse_feed(RSS.read_text()), _players("Ja'Marr Chase"))
    assert all("weather" not in e["link"] for es in hits.values() for e in es)


def test_players_not_in_the_feed_are_not_reported():
    assert match(parse_feed(RSS.read_text()), _players("Somebody Elsewhere")) == {}


def test_short_names_do_not_match_promiscuously():
    """Guards against a two-letter key matching everything.

    A flood of false hits would train you to ignore the output, which is the
    same way the first cliff-warning design failed.
    """
    assert match(parse_feed(RSS.read_text()), [("AB", normalize_name("AB"), "WR")]) == {}


def test_board_defences_are_skipped(tmp_path):
    """Team defences are city names and would match half the feed."""
    board = tmp_path / "b.csv"
    board.write_text("player,position\nJa'Marr Chase,WR\nBaltimore,DEF\n")
    assert [p[0] for p in load_board_names(board)] == ["Ja'Marr Chase"]
