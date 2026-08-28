"""board.csv + --slot -> a one-page printable sheet. The last line of defence.

If the laptop dies, the wifi dies, or the tracker somehow will not start, this
page is what you draft from. So it is deliberately static HTML with inline CSS
and no scripts: it renders in any browser, prints from any browser, and is
readable on paper under bad light at 11pm.

Slot is a runtime argument because the draft order arrives 30 minutes before the
draft. Rendering is offline and sub-second, so regenerating at T-30 is safe —
but `--all` pre-renders every slot the night before, so on the night you are
opening a file rather than running a command.
"""

from __future__ import annotations

import argparse
import csv
import html
import tomllib
from datetime import datetime
from pathlib import Path

BOARD = Path("data/board.csv")
NOTES = Path("data/notes.toml")
OUT = Path("data/sheet.html")

# Required by Fantasy Football Calculator's terms of use. It is printed on the
# sheet rather than buried in a source file, because that is where it is seen.
ATTRIBUTION = "ADP data provided by Fantasy Football Calculator · stats via nflverse"

POSITIONS = ("QB", "RB", "WR", "TE", "DEF")

CSS = """
:root { --ink:#111; --dim:#666; --rule:#ccc; --band:#f2f2f2;
        --avoid:#b00020; --target:#0a6e2e; }
* { box-sizing: border-box; }
body { font: 10px/1.28 -apple-system, "Helvetica Neue", Arial, sans-serif;
       color: var(--ink); margin: 0; padding: 10px 12px; }
h1 { font-size: 15px; margin: 0 0 1px; letter-spacing: -.2px; }
.sub { color: var(--dim); font-size: 9.5px; margin-bottom: 7px; }
.picks { font-weight: 700; }
.notes { border:1px solid var(--rule); border-left:3px solid var(--ink);
         padding:5px 7px; margin-bottom:8px; font-size:9.5px; }
.notes b { display:inline-block; min-width:118px; }
.avoid { color: var(--avoid); font-weight:700; }
.target { color: var(--target); font-weight:700; }
.grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 7px; }
.col h2 { font-size: 10.5px; margin: 0 0 3px; padding-bottom: 2px;
          border-bottom: 1.5px solid var(--ink); letter-spacing:.4px; }
table { width: 100%; border-collapse: collapse; }
td { padding: 1px 2px; vertical-align: baseline; }
.rk { color: var(--dim); width: 15px; text-align: right; }
.vb { text-align: right; color: var(--dim); width: 24px; font-variant-numeric: tabular-nums; }
.nm { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 96px; }
tr.tierstart td { border-top: 1px solid var(--rule); padding-top: 2.5px; }
tr.tierstart td.rk::before { content: ""; }
.tierlabel { font-size: 8px; color: var(--dim); letter-spacing: .3px; }
.band { background: var(--band); }
footer { margin-top: 8px; padding-top: 4px; border-top: 1px solid var(--rule);
         color: var(--dim); font-size: 8.5px; display:flex; justify-content:space-between; }
@page { size: letter portrait; margin: 8mm; }
@media print { body { padding: 0; } .noprint { display: none; } }
"""


def load_board(path: Path) -> list[dict]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["vbd"] = float(r["vbd"])
        r["tier"] = int(r["tier"])
        r["adp"] = float(r["adp"])
    return rows


def load_notes(path: Path = NOTES) -> dict[str, str]:
    """Hand-maintained flags. Absent file is normal, not an error.

    Deliberately not parsed from newsletters: ADP already absorbs published
    news within a day, nflverse carries injury status structured, and scraping
    the publishers would be a terms-of-use problem. What is left is a handful
    of judgements a person makes, so a person types them.
    """
    if not path.exists():
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh).get("notes", {})


def my_picks(slot: int, teams: int, rounds: int) -> list[int]:
    """Plain snake, no third-round reversal."""
    out = []
    for p in range(1, teams * rounds + 1):
        rnd, idx = divmod(p - 1, teams)
        if (idx + 1 if rnd % 2 == 0 else teams - idx) == slot:
            out.append(p)
    return out


def _column(rows: list[dict], notes: dict[str, str], limit: int) -> str:
    cells, last_tier = [], None
    for r in rows[:limit]:
        new_tier = r["tier"] != last_tier
        last_tier = r["tier"]
        note = notes.get(r["player"], "")
        cls = "avoid" if note.startswith("avoid") else "target" if note.startswith("target") else ""
        flag = f' <span class="{cls}">*</span>' if cls else ""
        cells.append(
            f'<tr class="{"tierstart" if new_tier else ""}">'
            f'<td class="rk">{r["pos_rank"]}</td>'
            f'<td class="nm">{html.escape(r["player"])}{flag}</td>'
            f'<td class="vb">{r["vbd"]:.0f}</td></tr>'
        )
    return "".join(cells)


def render(board: list[dict], rules: dict, slot: int, notes: dict[str, str],
           per_pos: int = 30) -> str:
    teams = rules["league"]["teams"]
    rounds = sum(rules["roster"]["starters"].values()) + rules["roster"]["bench"]
    picks = my_picks(slot, teams, rounds)

    cols = []
    for pos in POSITIONS:
        rows = sorted((r for r in board if r["position"] == pos),
                      key=lambda r: -r["vbd"])
        cols.append(
            f'<div class="col"><h2>{pos}</h2><table>{_column(rows, notes, per_pos)}</table></div>'
        )

    flagged = "".join(
        f'<div><b>{html.escape(k)}</b> '
        f'<span class="{"avoid" if v.startswith("avoid") else "target" if v.startswith("target") else ""}">'
        f'{html.escape(v)}</span></div>'
        for k, v in sorted(notes.items())
    )
    notes_block = f'<div class="notes">{flagged}</div>' if flagged else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(rules['league']['name'])} — slot {slot}</title>
<style>{CSS}</style></head><body>
<h1>{html.escape(rules['league']['name'])} · Slot {slot}</h1>
<div class="sub">
  {teams} teams · plain snake · {rounds} rounds · full PPR · +2 on any 40+ yd run/reception · no kicker<br>
  <span class="picks">Your picks:</span> {' · '.join(str(p) for p in picks)}
</div>
{notes_block}
<div class="grid">{''.join(cols)}</div>
<footer><span>{ATTRIBUTION}</span><span>generated {datetime.now():%Y-%m-%d %H:%M}</span></footer>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the printable draft sheet.")
    ap.add_argument("--slot", type=int, help="your draft position (1-based)")
    ap.add_argument("--all", action="store_true",
                    help="pre-render every slot, so T-30 is opening a file not running a command")
    ap.add_argument("--board", type=Path, default=BOARD)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--config", default="league.toml")
    args = ap.parse_args()

    with open(args.config, "rb") as fh:
        rules = tomllib.load(fh)
    teams = rules["league"]["teams"]
    board = load_board(args.board)
    notes = load_notes()

    if args.all:
        for slot in range(1, teams + 1):
            dest = args.out.with_name(f"sheet_slot{slot:02d}.html")
            dest.write_text(render(board, rules, slot, notes))
        print(f"wrote {teams} slot variants next to {args.out}")
        return

    if not args.slot:
        ap.error("give --slot N, or --all to pre-render every slot")
    if not 1 <= args.slot <= teams:
        ap.error(f"--slot must be between 1 and {teams}")
    args.out.write_text(render(board, rules, args.slot, notes))
    print(f"wrote {args.out} (slot {args.slot})")


if __name__ == "__main__":
    main()
