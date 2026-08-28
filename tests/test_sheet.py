"""Tests for the printable sheet — the last line of defence.

If everything else fails, this page is what the draft is run from, so the things
pinned here are the things that would make it useless on paper.
"""

import tomllib

import pytest

from fw.sheet import ATTRIBUTION, load_notes, my_picks, render


@pytest.fixture(scope="module")
def rules():
    with open("league.toml", "rb") as fh:
        return tomllib.load(fh)


@pytest.fixture
def board():
    rows = []
    for pos, n in (("QB", 8), ("RB", 20), ("WR", 24), ("TE", 10), ("DEF", 8)):
        for i in range(n):
            rows.append({"player": f"{pos} Player {i}", "position": pos,
                         "pos_rank": i + 1, "vbd": 200.0 - i * 7.0,
                         "tier": i // 4 + 1, "adp": float(i + 1),
                         "proj_points": 300.0 - i, "team": "FA"})
    return rows


def test_sheet_has_no_scripts(board, rules):
    """Static HTML only: it must render from a file:// URL on any machine,
    including one with no network and a browser that blocks scripts."""
    out = render(board, rules, 7, {})
    assert "<script" not in out.lower()
    assert "http://" not in out and "https://" not in out


def test_attribution_is_printed(board, rules):
    """FFC's terms require attribution, and it belongs where it is seen."""
    assert "Fantasy Football Calculator" in render(board, rules, 7, {})
    assert "Fantasy Football Calculator" in ATTRIBUTION


def test_slot_changes_the_pick_numbers(board, rules):
    """The sheet is slot-specific; two slots must not produce the same page."""
    assert render(board, rules, 1, {}) != render(board, rules, 12, {})


def test_pick_numbers_are_correct_for_the_slot(board, rules):
    out = render(board, rules, 1, {})
    assert "1 · 24 · 25 · 48" in out


def test_every_slot_renders(board, rules):
    """All 12 are pre-rendered the night before, so all 12 must work."""
    for slot in range(1, rules["league"]["teams"] + 1):
        assert f"Slot {slot}" in render(board, rules, slot, {})


def test_all_positions_appear(board, rules):
    out = render(board, rules, 7, {})
    for pos in ("QB", "RB", "WR", "TE", "DEF"):
        assert f"<h2>{pos}</h2>" in out


def test_no_kicker_column(board, rules):
    assert "<h2>K</h2>" not in render(board, rules, 7, {})


def test_notes_are_rendered_and_classified(board, rules):
    notes = {"RB Player 0": "avoid: hamstring", "WR Player 1": "target: WR1 role"}
    out = render(board, rules, 7, notes)
    assert "avoid: hamstring" in out and "target: WR1 role" in out
    assert 'class="avoid"' in out and 'class="target"' in out


def test_missing_notes_file_is_not_an_error(tmp_path):
    """Notes are optional; their absence must never block printing the sheet."""
    assert load_notes(tmp_path / "nope.toml") == {}


def test_player_names_are_escaped(board, rules):
    """Real names carry apostrophes and periods (Ja'Marr, A.J.)."""
    board = board + [{"player": "Ja'Marr <script>", "position": "WR", "pos_rank": 99,
                      "vbd": 1.0, "tier": 9, "adp": 99.0, "proj_points": 1.0, "team": "FA"}]
    out = render(board, rules, 7, {})
    assert "<script>" not in out
    assert "&lt;script&gt;" in out or "Ja&#x27;Marr" in out


def test_snake_picks_match_the_tracker():
    """sheet.my_picks and track.my_picks must agree, or the printed sheet and
    the screen disagree about which picks are yours."""
    from fw.track import my_picks as track_picks
    for slot in (1, 6, 12):
        assert my_picks(slot, 12, 13) == track_picks(slot, 12, 13)
