# Fantasy Winner

A pre-computed VBD value board plus an offline draft-night tier tracker.
Draft: **Wed Sep 3, 11:00pm EDT**, 60-second pick clock.

## Draft order arrives 30 minutes before the draft

So **nothing built ahead of time may depend on the draft slot.** `league.toml`
has no `draft_slot`; slot is a runtime flag (`fw-track --slot N`,
`fw-sheet --slot N`) and snake pick math is derived from it plus `teams`.
`board.csv` is slot-agnostic and gets built days early.

The T-30 routine, in order:

1. Learn the slot.
2. `fw-sheet --slot N` — regenerates the printable page. Offline, sub-second.
3. `fw-track --slot N` — tracker comes up knowing which picks are yours.

As insurance, pre-render all `teams` slot variants of the sheet the night
before, so on the night you are opening a file rather than running a command.

## The one rule

**Nothing on the draft-night path touches the network.** `src/fw/track.py` must
not import anything that can open a socket. The board is computed in advance and
read from `data/board.csv`. If a change would put an LLM call, an HTTP request,
or a multi-second computation between "it's my pick" and "here's the name" —
that change is wrong, regardless of how good the answer would be.

## Toolchain

Built with [gstack](https://github.com/garrytan/gstack) (role cadence:
Think → Plan → Build → Review → Test → Ship → Reflect) and
[ponytail](https://github.com/DietrichGebert/ponytail) (Ladder of Laziness —
does this need to exist → already here → stdlib → platform → installed dep →
one line → only then minimum working code).

Per evening: `/spec` → build → `/review` → `/qa` → `/ship`.

## Layout

| Path | What it is |
|---|---|
| `league.toml` | **The only config.** Scoring, roster, team count. No draft slot — see above. |
| `src/fw/scoring.py` | Stat line → fantasy points under our rules. Pure, no I/O. |
| `src/fw/sources.py` | FFC ADP + Sleeper metadata + nflreadpy history → `data/raw/`. |
| `src/fw/board.py` | ADP + history → projected points → VBD → tiers → `data/board.csv`. |
| `src/fw/track.py` | Draft-night REPL. Stdlib only. |
| `src/fw/sheet.py` | `board.csv` + `--slot` → one-page printable HTML. Last line of defence. |

## League specifics that break generic tools

- **No kicker.** No K position, no K baseline in VBD.
- **Full PPR** (1.0/reception) plus **+2 for 40+ yard rushing and receiving TDs** —
  this favours high-target and big-play players over generic-PPR consensus.
- **DST tiers are more generous than Yahoo default** at the top (0 points allowed
  = 10), which raises elite DST value.
- **No FAAB**, rolling waiver priority, unlimited acquisitions, weekly processing
  at Tuesday game time. (Track B concern — not before Sep 3.)

## Data sources (free only)

- **ADP** — [Fantasy Football Calculator ADP REST API](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api).
  Free for personal use; **attribution required**; do not call frequently.
- **Player metadata** — Sleeper public read-only API, no auth. Stay under 1000 req/min.
- **Historical stats** — `nflreadpy` (returns Polars). `nfl_data_py` was archived
  Sep 2025 — do not use it. ID joins via `nflreadpy.load_ff_playerids()`.

## Environment note

Claude Code web containers cannot reach these hosts (egress proxy returns 403 on
`fantasyfootballcalculator.com` and `api.sleeper.app`). Write and unit-test
ingest against `tests/fixtures/`; run real pulls locally.

## Out of scope before Sep 3

Live Yahoo draft polling, any LLM on the clock, browser automation for lineups,
and all of Track B (lineup optimizer, DST streamer, waiver tool, trade analyzer).
