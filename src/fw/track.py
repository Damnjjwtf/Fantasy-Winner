"""Draft-night tracker. Offline, stdlib only, resumable.

The one rule: nothing here may touch the network. No imports that can open a
socket, no LLM, no computation slow enough to notice. Between "it's my pick"
and "here's the name" there must be nothing but a dict lookup and a print.

`board.csv` is read once at startup. Every pick is appended to
`data/draft_state.json` and flushed to disk immediately, so a crash at pick 94
costs nothing — relaunch and you are back where you were.

Usage during the draft: type enough of a name to identify the player and press
Enter. That is the whole interaction. Team attribution is derived from the pick
number, so marking a pick costs the same keystrokes whether it was yours or a
rival's.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import sys
import tomllib
from pathlib import Path

BOARD = Path("data/board.csv")
STATE = Path("data/draft_state.json")
ORDER = Path("data/draft_order.txt")

# ANSI, used sparingly: at 11pm the eye should land on the cliff warning first.
BOLD, DIM, RED, YELLOW, GREEN, RESET = (
    "\033[1m", "\033[2m", "\033[31m", "\033[33m", "\033[32m", "\033[0m"
)


def load_board(path: Path) -> list[dict]:
    """Read the pre-computed board. Plain csv, no polars — this must start fast."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["vbd"] = float(r["vbd"])
        r["proj_points"] = float(r["proj_points"])
        r["tier"] = int(r["tier"])
        r["adp"] = float(r["adp"])
    return rows


def team_for_pick(pick: int, teams: int) -> int:
    """Which draft slot owns this overall pick number, under plain snake.

    Confirmed no third-round reversal, so the rule is uniform every round:
    odd rounds run 1..N, even rounds run N..1.
    """
    rnd, idx = divmod(pick - 1, teams)
    return idx + 1 if rnd % 2 == 0 else teams - idx


def my_picks(slot: int, teams: int, rounds: int) -> list[int]:
    return [p for p in range(1, teams * rounds + 1) if team_for_pick(p, teams) == slot]


def next_pick_for(slot: int, teams: int, rounds: int, after: int) -> int | None:
    return next((p for p in my_picks(slot, teams, rounds) if p >= after), None)


class Draft:
    """All draft state. Rebuilt from the pick list, so undo is just a pop."""

    def __init__(self, board: list[dict], rules: dict, slot: int, names: list[str]):
        self.board = board
        self.rules = rules
        self.slot = slot
        self.teams = rules["league"]["teams"]
        starters = rules["roster"]["starters"]
        self.rounds = sum(starters.values()) + rules["roster"]["bench"]
        self.starters = starters
        self.flex_eligible = rules["roster"]["flex_eligible"]
        self.names = names
        self.picks: list[str] = []
        self.by_key = {r["player"].lower(): r for r in board}

    # ---- state -----------------------------------------------------------
    @property
    def on_the_clock(self) -> int:
        return len(self.picks) + 1

    def drafted(self) -> set[str]:
        return {p.lower() for p in self.picks}

    def available(self) -> list[dict]:
        taken = self.drafted()
        return [r for r in self.board if r["player"].lower() not in taken]

    def roster_of(self, slot: int) -> list[dict]:
        out = []
        for i, name in enumerate(self.picks, start=1):
            if team_for_pick(i, self.teams) == slot:
                row = self.by_key.get(name.lower())
                if row:
                    out.append(row)
        return out

    def needs_of(self, slot: int) -> list[str]:
        """Unfilled starting slots for a team, FLEX resolved last."""
        have: dict[str, int] = {}
        for r in self.roster_of(slot):
            have[r["position"]] = have.get(r["position"], 0) + 1
        needs = []
        for pos, n in self.starters.items():
            if pos == "FLEX":
                continue
            short = n - have.get(pos, 0)
            for _ in range(max(0, short)):
                needs.append(pos)
                have[pos] = have.get(pos, 0) + 1
        spare = sum(have.get(p, 0) for p in self.flex_eligible) - sum(
            self.starters.get(p, 0) for p in self.flex_eligible
        )
        for _ in range(max(0, self.starters.get("FLEX", 0) - max(0, spare))):
            needs.append("FLEX")
        return needs

    def label(self, slot: int) -> str:
        if slot == self.slot:
            return "YOU"
        if self.names and slot <= len(self.names):
            return self.names[slot - 1]
        return f"seat {slot}"

    # ---- mutation --------------------------------------------------------
    def taken_match(self, text: str) -> dict | None:
        """The already-drafted player this text refers to, if any.

        Checked BEFORE fuzzy matching. Typing the name of someone already gone
        used to fall through to the fuzzy pass and return a different player
        entirely — "Alpha Back" once resolved to Beta Back, Alpha Wide and
        Alpha Arm. Had exactly one survived, it would have been marked with no
        confirmation, silently drafting the wrong man and leaving the board
        quietly wrong for the rest of the night.
        """
        q = text.strip().lower()
        if not q:
            return None
        for i, name in enumerate(self.picks, start=1):
            low = name.lower()
            if low.startswith(q) or q in low:
                row = dict(self.by_key.get(low, {"player": name}))
                row["_pick"] = i
                row["_owner"] = team_for_pick(i, self.teams)
                return row
        return None

    def resolve(self, text: str) -> list[dict]:
        """Match typed text to AVAILABLE players: prefix, then substring, then fuzzy.

        Fuzzy matching is a deliberate last resort — fingers slip on a 60-second
        clock — but it only runs when the text does not name someone already
        drafted, so a near-miss can never be silently converted into a real pick.
        """
        q = text.strip().lower()
        if not q:
            return []
        avail = self.available()
        for pool in (
            [r for r in avail if r["player"].lower().startswith(q)],
            [r for r in avail if q in r["player"].lower()],
            [r for r in avail if q in r["player"].lower().replace(".", "").replace("'", "")],
        ):
            if pool:
                return pool
        if self.taken_match(q):
            return []
        close = difflib.get_close_matches(q, [r["player"].lower() for r in avail], n=5, cutoff=0.6)
        return [r for r in avail if r["player"].lower() in close]

    def mark(self, player: str) -> None:
        self.picks.append(player)
        self.save()

    def undo(self) -> str | None:
        if not self.picks:
            return None
        gone = self.picks.pop()
        self.save()
        return gone

    def save(self) -> None:
        """Atomic write, flushed to disk. A crash must never cost a pick."""
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump({"slot": self.slot, "picks": self.picks}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATE)

    def load(self) -> None:
        if STATE.exists():
            data = json.loads(STATE.read_text())
            self.picks = data.get("picks", [])


# ---- display -------------------------------------------------------------

def cliff_report(d: Draft, max_warnings: int = 2, min_drop: float = 12.0) -> list[str]:
    """Positions where waiting until your next turn will actually cost you.

    This is the whole reason the tracker knows the full draft order: instead of
    "this tier will probably empty" it can say which teams pick before you and
    which of them still need the position.

    Three filters, all of which exist because the first version fired five red
    warnings at pick 1 and was therefore useless:

    * **Only positions you need.** At an empty roster every team "needs"
      everything, so opponent need alone separates nothing.
    * **Only material drops.** A cliff matters if the value below it is much
      worse. An elite singleton tier is not a cliff — you can only take one
      player regardless, so being told it is scarce changes no decision.
    * **At most two, worst first.** More than that is a wall of red at 11pm,
      and a warning you learn to ignore is worse than no warning.
    """
    nxt = next_pick_for(d.slot, d.teams, d.rounds, d.on_the_clock + 1)
    if nxt is None:
        return []
    between = [p for p in range(d.on_the_clock, nxt) if team_for_pick(p, d.teams) != d.slot]
    if not between:
        return []

    my_needs = set(d.needs_of(d.slot))
    if "FLEX" in my_needs:
        my_needs |= set(d.flex_eligible)
    if not my_needs:
        my_needs = {"QB", "RB", "WR", "TE", "DEF"}

    slots_ahead = [team_for_pick(p, d.teams) for p in between]
    needs_cache = {s: set(d.needs_of(s)) for s in set(slots_ahead)}
    avail = d.available()

    found = []
    for pos in ("RB", "WR", "TE", "QB", "DEF"):
        if pos not in my_needs:
            continue
        pool = [r for r in avail if r["position"] == pos]
        if not pool:
            continue
        top_tier = min(r["tier"] for r in pool)
        in_tier = [r for r in pool if r["tier"] == top_tier]
        below = [r for r in pool if r["tier"] != top_tier]
        if not below:
            continue
        # The drop is what you actually lose by missing this tier.
        drop = min(r["vbd"] for r in in_tier) - max(r["vbd"] for r in below)
        if drop < min_drop:
            continue
        hungry = [s for s in slots_ahead
                  if pos in needs_cache[s] or "FLEX" in needs_cache[s]]
        if len(in_tier) > len(hungry):
            continue
        found.append((drop, pos, top_tier, len(in_tier), len(hungry), len(between)))

    lines = []
    for drop, pos, tier, left, hungry, ahead in sorted(found, reverse=True)[:max_warnings]:
        lines.append(
            f"{RED}{BOLD}CLIFF{RESET} {pos} T{tier}: {RED}{left} left{RESET}, "
            f"{hungry}/{ahead} picks ahead need it, "
            f"next tier is {RED}-{drop:.0f}{RESET}"
        )
    return lines


def render(d: Draft, per_pos: int = 6) -> str:
    pick = d.on_the_clock
    total = d.teams * d.rounds
    if pick > total:
        return f"{BOLD}Draft complete.{RESET} {total} picks.\n"

    rnd = (pick - 1) // d.teams + 1
    owner = team_for_pick(pick, d.teams)
    mine = owner == d.slot
    nxt = next_pick_for(d.slot, d.teams, d.rounds, pick + (1 if mine else 0))

    out = ["", "=" * 78]
    head = f"Pick {pick}/{total}  (round {rnd}.{(pick - 1) % d.teams + 1})  ->  {d.label(owner)}"
    out.append(f"{GREEN}{BOLD}>>> YOUR PICK <<<  {head}{RESET}" if mine
               else f"{BOLD}{head}{RESET}")
    if nxt and not mine:
        out.append(f"{DIM}your next pick: {nxt} ({nxt - pick} away){RESET}")
    out.append("=" * 78)

    for line in cliff_report(d):
        out.append(line)

    roster = d.roster_of(d.slot)
    needs = d.needs_of(d.slot)
    have = ", ".join(f"{r['position']} {r['player']}" for r in roster) or "(empty)"
    out.append(f"{BOLD}You:{RESET} {have}")
    out.append(f"{BOLD}Need:{RESET} {' '.join(needs) if needs else 'starters full - best available'}")
    out.append("-" * 78)

    avail = d.available()
    for pos in ("QB", "RB", "WR", "TE", "DEF"):
        pool = [r for r in avail if r["position"] == pos][:per_pos]
        if not pool:
            continue
        cells, last_tier = [], None
        for r in pool:
            sep = " | " if last_tier is not None and r["tier"] != last_tier else "  "
            marker = f"{YELLOW}T{r['tier']}{RESET}"
            cells.append(f"{sep}{marker} {r['player'][:17]} {DIM}{r['vbd']:.0f}{RESET}")
            last_tier = r["tier"]
        out.append(f"{BOLD}{pos:3}{RESET}" + "".join(cells))
    out.append("-" * 78)
    return "\n".join(out)


# ---- repl ----------------------------------------------------------------

HELP = """
  <name>   mark a player drafted (prefix is enough)
  u        undo the last pick
  r        redraw
  ?        this help
  q        quit (state is already saved)
"""


def repl(d: Draft) -> None:
    print(render(d))
    while True:
        try:
            raw = input(f"{BOLD}pick {d.on_the_clock}> {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nsaved.")
            return

        if not raw or raw == "r":
            print(render(d))
            continue
        if raw == "q":
            print("saved.")
            return
        if raw == "?":
            print(HELP)
            continue
        if raw == "u":
            gone = d.undo()
            print(f"{YELLOW}undid: {gone}{RESET}" if gone else "nothing to undo")
            print(render(d))
            continue

        hits = d.resolve(raw)
        if not hits:
            gone = d.taken_match(raw)
            if gone:
                print(f"{YELLOW}{gone['player']} already went at pick {gone['_pick']} "
                      f"to {d.label(gone['_owner'])}{RESET}")
            else:
                print(f"{RED}no match for {raw!r}{RESET}")
            continue
        if len(hits) > 1:
            # Ambiguity is resolved by number rather than more typing, because
            # retyping a longer name is the slowest thing you can do on a clock.
            print(f"{YELLOW}which?{RESET}")
            for i, r in enumerate(hits[:9], start=1):
                print(f"  {i}. {r['position']:3} {r['player']}  (vbd {r['vbd']:.0f}, T{r['tier']})")
            choice = input("number (enter to cancel)> ").strip()
            if not choice.isdigit() or not 1 <= int(choice) <= len(hits[:9]):
                print("cancelled")
                continue
            hit = hits[int(choice) - 1]
        else:
            hit = hits[0]

        owner = d.label(team_for_pick(d.on_the_clock, d.teams))
        d.mark(hit["player"])
        print(f"{GREEN}{hit['player']} -> {owner}{RESET}")
        print(render(d))


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline draft-night tracker.")
    ap.add_argument("--slot", type=int, required=True, help="your draft position (1-based)")
    ap.add_argument("--board", type=Path, default=BOARD)
    ap.add_argument("--config", default="league.toml")
    ap.add_argument("--reset", action="store_true", help="discard saved state and start over")
    args = ap.parse_args()

    with open(args.config, "rb") as fh:
        rules = tomllib.load(fh)
    teams = rules["league"]["teams"]
    if not 1 <= args.slot <= teams:
        sys.exit(f"--slot must be between 1 and {teams}")
    if not args.board.exists():
        sys.exit(f"no board at {args.board} — run fw-board first")

    # Optional: the real draft order arrives 30 minutes before the draft. Without
    # it opponents are labelled by seat and everything else still works, so a
    # fumbled paste at T-25 can never stop the tracker coming up.
    names = [ln.strip() for ln in ORDER.read_text().splitlines() if ln.strip()] \
        if ORDER.exists() else []
    if names and len(names) != teams:
        print(f"{YELLOW}warning: {ORDER} has {len(names)} names, expected {teams} — "
              f"falling back to seat numbers{RESET}")
        names = []

    if args.reset and STATE.exists():
        STATE.unlink()

    d = Draft(load_board(args.board), rules, args.slot, names)
    d.load()
    if d.picks:
        print(f"{YELLOW}resumed at pick {d.on_the_clock} ({len(d.picks)} already marked){RESET}")
    repl(d)


if __name__ == "__main__":
    main()
