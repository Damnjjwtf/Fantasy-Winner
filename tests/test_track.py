"""Tests for the draft-night tracker.

These pin the things that would actually hurt at 11pm: wrong pick attribution,
lost state, and any import that could block on a socket.
"""

import ast
import json
import tomllib
from pathlib import Path

import pytest

from fw.track import Draft, my_picks, next_pick_for, team_for_pick


@pytest.fixture(scope="module")
def rules():
    with open("league.toml", "rb") as fh:
        return tomllib.load(fh)


@pytest.fixture
def board():
    def row(name, pos, vbd, tier, adp):
        return {"player": name, "position": pos, "vbd": vbd, "tier": tier,
                "adp": adp, "proj_points": vbd + 100, "team": "FA"}
    return [
        row("Alpha Back", "RB", 200.0, 1, 1.0), row("Beta Back", "RB", 150.0, 2, 2.0),
        row("Gamma Back", "RB", 60.0, 3, 3.0), row("Alpha Wide", "WR", 190.0, 1, 4.0),
        row("Beta Wide", "WR", 140.0, 2, 5.0), row("Alpha Tight", "TE", 90.0, 1, 6.0),
        row("Alpha Arm", "QB", 80.0, 1, 7.0), row("Alpha D", "DEF", 40.0, 1, 8.0),
    ]


def _draft(board, rules, slot=7, tmp=None):
    d = Draft(board, rules, slot, [])
    if tmp is not None:
        import fw.track as t
        t.STATE = tmp / "state.json"
    return d


# ---- snake math ----------------------------------------------------------

def test_snake_reverses_every_round():
    """Plain snake, confirmed no third-round reversal: odd rounds 1..12, even 12..1."""
    assert [team_for_pick(p, 12) for p in range(1, 13)] == list(range(1, 13))
    assert [team_for_pick(p, 12) for p in range(13, 25)] == list(range(12, 0, -1))
    assert [team_for_pick(p, 12) for p in range(25, 37)] == list(range(1, 13))


def test_slot_one_waits_longest():
    """Slot 1 waits 22 picks between turns; the tracker's countdown depends on it."""
    picks = my_picks(1, 12, 13)
    assert picks[:4] == [1, 24, 25, 48]
    assert picks[1] - picks[0] == 23


def test_slot_twelve_gets_back_to_back():
    picks = my_picks(12, 12, 13)
    assert picks[:4] == [12, 13, 36, 37]


def test_every_team_gets_every_round():
    """156 picks, 12 teams, 13 each — no team may be short-changed."""
    counts = {s: 0 for s in range(1, 13)}
    for p in range(1, 157):
        counts[team_for_pick(p, 12)] += 1
    assert set(counts.values()) == {13}


def test_next_pick_lookahead():
    assert next_pick_for(7, 12, 13, 1) == 7
    assert next_pick_for(7, 12, 13, 8) == 18


# ---- state ---------------------------------------------------------------

def test_pick_is_attributed_to_the_right_team(board, rules, tmp_path):
    d = _draft(board, rules, slot=3, tmp=tmp_path)
    d.mark("Alpha Back")
    d.mark("Alpha Wide")
    d.mark("Beta Back")
    assert [r["player"] for r in d.roster_of(3)] == ["Beta Back"]
    assert [r["player"] for r in d.roster_of(1)] == ["Alpha Back"]


def test_undo_restores_previous_state(board, rules, tmp_path):
    d = _draft(board, rules, tmp=tmp_path)
    d.mark("Alpha Back")
    d.mark("Alpha Wide")
    assert d.undo() == "Alpha Wide"
    assert d.on_the_clock == 2
    assert any(r["player"] == "Alpha Wide" for r in d.available())


def test_undo_on_empty_is_safe(board, rules, tmp_path):
    assert _draft(board, rules, tmp=tmp_path).undo() is None


def test_state_survives_a_crash(board, rules, tmp_path):
    """A crash mid-draft must cost nothing — the whole point of saving per pick."""
    import fw.track as t
    t.STATE = tmp_path / "state.json"
    d = Draft(board, rules, 7, [])
    d.mark("Alpha Back")
    d.mark("Alpha Wide")

    revived = Draft(board, rules, 7, [])
    revived.load()
    assert revived.picks == ["Alpha Back", "Alpha Wide"]
    assert revived.on_the_clock == 3


def test_drafted_players_leave_the_pool(board, rules, tmp_path):
    d = _draft(board, rules, tmp=tmp_path)
    d.mark("Alpha Back")
    assert all(r["player"] != "Alpha Back" for r in d.available())


# ---- matching ------------------------------------------------------------

def test_prefix_match_is_enough(board, rules, tmp_path):
    d = _draft(board, rules, tmp=tmp_path)
    assert [r["player"] for r in d.resolve("alpha b")] == ["Alpha Back"]


def test_ambiguous_prefix_returns_all_candidates(board, rules, tmp_path):
    """Ambiguity must be surfaced, never silently resolved to the first hit."""
    d = _draft(board, rules, tmp=tmp_path)
    assert len(d.resolve("alpha")) > 1


def test_typo_still_finds_the_player(board, rules, tmp_path):
    """Fingers slip on a 60-second clock."""
    d = _draft(board, rules, tmp=tmp_path)
    assert any(r["player"] == "Alpha Tight" for r in d.resolve("alpha tigth"))


def test_already_drafted_players_are_unmatchable(board, rules, tmp_path):
    d = _draft(board, rules, tmp=tmp_path)
    d.mark("Alpha Back")
    assert d.resolve("alpha back") == []


# ---- needs ---------------------------------------------------------------

def test_needs_start_as_full_starting_lineup(board, rules, tmp_path):
    d = _draft(board, rules, tmp=tmp_path)
    needs = d.needs_of(7)
    assert needs.count("RB") == 2 and needs.count("WR") == 2
    assert "QB" in needs and "TE" in needs and "DEF" in needs and "FLEX" in needs
    assert "K" not in needs, "this league has no kicker"


def test_filling_a_slot_clears_that_need(board, rules, tmp_path):
    d = _draft(board, rules, slot=1, tmp=tmp_path)
    d.mark("Alpha Arm")
    assert "QB" not in d.needs_of(1)


# ---- the one rule --------------------------------------------------------

def test_tracker_imports_nothing_that_can_reach_the_network():
    """The one rule: draft night never touches the network.

    Asserted mechanically rather than by discipline, because this is the single
    constraint whose violation would be invisible until it mattered most.
    """
    tree = ast.parse(Path("src/fw/track.py").read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    banned = {"socket", "http", "urllib", "requests", "httpx", "ssl", "ftplib",
              "smtplib", "asyncio", "subprocess", "nflreadpy", "polars", "fw"}
    assert not (found & banned), f"track.py must stay offline, found: {found & banned}"


def test_typing_a_taken_player_never_marks_someone_else(board, rules, tmp_path):
    """The nastiest failure this tracker could have.

    Typing a drafted player's name once fuzzy-matched to entirely different
    players. With one survivor it would have been marked without confirmation:
    the wrong man drafted, silently, and the board wrong from then on.
    """
    d = _draft(board, rules, tmp=tmp_path)
    d.mark("Alpha Back")
    assert d.resolve("Alpha Back") == []
    assert d.resolve("alpha back") == []


def test_taken_player_is_reported_with_who_took_them(board, rules, tmp_path):
    """Better than 'no match': tells you the pick was already accounted for."""
    d = _draft(board, rules, slot=7, tmp=tmp_path)
    d.mark("Alpha Back")
    gone = d.taken_match("alpha back")
    assert gone["player"] == "Alpha Back"
    assert gone["_pick"] == 1 and gone["_owner"] == 1


def test_fuzzy_still_works_for_a_genuine_typo(board, rules, tmp_path):
    """The taken-player guard must not disable typo tolerance."""
    d = _draft(board, rules, tmp=tmp_path)
    d.mark("Alpha Back")
    assert any(r["player"] == "Alpha Tight" for r in d.resolve("alpha tigth"))
