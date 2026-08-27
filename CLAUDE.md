# Fantasy Winner

A pre-computed VBD value board plus an offline draft-night tier tracker.
League **"Down Goes Just Win Baby!"** (Yahoo 890969), 12 teams, head-to-head.
Draft: **Thu Sep 3 2026, 11:00pm EDT**, 60-second pick clock, live standard
(snake). Note the architecture doc says "Wed" — Sep 3 2026 is a **Thursday**.

## Draft order arrives 30 minutes before the draft

So **nothing built ahead of time may depend on the draft slot.** `league.toml`
has no `draft_slot`; slot is a runtime flag (`fw-track --slot N`,
`fw-sheet --slot N`) and snake pick math is derived from it plus `teams`.
`board.csv` is slot-agnostic and gets built days early.

The T-30 routine, in order:

1. Learn the slot and the full order.
2. Paste the 12 team names, in draft-position order, into `data/draft_order.txt`
   — one per line. **Optional**: if the file is absent the tracker labels
   opponents by seat number and everything else still works. Never let this
   step block getting the tracker up.
3. `fw-sheet --slot N` — regenerates the printable page. Offline, sub-second.
4. `fw-track --slot N` — tracker comes up knowing which picks are yours.

As insurance, pre-render all 12 slot variants of the sheet the night before, so
on the night you are opening a file rather than running a command.

Confirmed: **12 teams, plain snake, no third-round reversal** — so pick math is
uniform every round, and 8 starters + 5 bench = **13 rounds, 156 picks**. Slot 1
waits 22 picks between turns; slot 6 never waits more than 12.

## We see the full draft order, not just our slot

Under plain snake, pick number → team is arithmetic, so every pick you mark is
attributed to a team for free — no extra typing on the clock. The tracker
accumulates all 12 rosters and uses them to sharpen the cliff warning from
*"this tier will probably empty"* to *"4 teams pick before you, 3 have no RB,
and this tier has 2 left."*

Opponent **needs** are computed from their roster so far. Opponent *tendencies*
are not modelled — this is a brand-new league with no completed season (every
team 0-0-0, no Record Book history), so there is literally nothing to fit a
behavioural model on. A made-up one would be worse than the positional-need read.

Team names live in `league.toml` under `[teams]` purely so the tracker prints
"Balls to the LaFleur needs RB" rather than "seat 8 needs RB" — faster to parse
at 11pm on a 60-second clock. We are "Just Win Baby".

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

## Schedule

All times EDT. "Evening N" from the architecture doc is not used here — real
dates only, because the draft is at 11pm and off-by-one days matter.

| Date | Day | Work |
|---|---|---|
| Aug 26 | Wed | ✅ scaffold, `league.toml` from real Yahoo settings. Install ponytail + gstack. |
| Aug 27 | Thu | `scoring.py` + golden tests. Verify the 40-yd bonus question. |
| Aug 28 | Fri | `sources.py` + committed fixtures. Runs on the local machine, not in a web container. |
| Aug 29 | Sat | `board.py` — ADP→points fit, VBD, tiers. Review hard. |
| Aug 30 | Sun | `track.py` — the draft-night REPL. |
| Aug 31 | Mon | `track.py` polish: team attribution, needs-aware cliff warnings. |
| Sep 1  | Tue | `sheet.py`, pre-render all 12 slot variants, clean-clone reproducibility run. |
| Sep 2  | Wed | Yahoo mock draft at a real 60s clock. Target: decide in under 30s. |
| Sep 3  | Thu | **Draft day.** Freeze code. Refresh ADP, regenerate board, print. T-30 routine at 10:30pm. **Draft 11:00pm.** |

Sep 3 is a full working day — the draft is at 11pm, not 11am. But the last
network-dependent step (the ADP refresh) happens that day, so keep the previous
`board.csv` as a fallback and never overwrite a known-good board in place.

## Layout

| Path | What it is |
|---|---|
| `league.toml` | **The only config.** Scoring, roster, team count. No draft slot — see above. |
| `src/fw/scoring.py` | Stat line → fantasy points under our rules. Pure, no I/O. |
| `src/fw/sources.py` | FFC ADP + nflreadpy history/metadata → `data/raw/`. Only networked module. |
| `src/fw/board.py` | ADP + history → projected points → VBD → tiers → `data/board.csv`. |
| `src/fw/track.py` | Draft-night REPL. Stdlib only. |
| `src/fw/sheet.py` | `board.csv` + `--slot` → one-page printable HTML. Last line of defence. |

## League specifics that break generic tools

`league.toml` is transcribed verbatim from the Yahoo settings screens. Where it
and the architecture doc disagree, the config wins — the doc had several values
wrong.

- **No kicker.** Roster is QB/WR/WR/RB/RB/TE/W-R-T/DEF + 5 BN + 1 IR. No K
  position, no K baseline in VBD. 13 rounds, 156 picks.
- **Full PPR** (1.0/reception), 10 yards per point rushing and receiving.
- **The 40+ yard bonus is the biggest single edge.** Yahoo maintains BOTH
  any-play and TD-only variants as separate scoring categories:

  | any-play | TD-only |
  |---|---|
  | 40+ Yard Receptions *(Receiving 40 Yd Rec)* | 40+ Yard Reception Touchdowns *(Receiving 40 Yd TD)* |
  | 40+ Yard Rushing Attempts *(Rushing 40 Yd Att)* | 40+ Yard Passing Touchdowns *(Passing 40 Yd TD)* |

  Our settings screen reads "40+ Yard Receptions" and "40+ Yard Run" — the
  any-play names, verbatim, with no "Touchdowns" qualifier. So the bonus pays
  on **any 40+ yard run or reception, scoring or not**: a 44-yard catch that
  dies at the 5 still pays +2. `applies_to_td_only = false`.

  Worth ~12 points a season on a deep threat vs. a possession receiver who is
  otherwise identical — about a round of draft capital. If you ever want to
  double-check it, open a 2025 box score for a player with a long non-scoring
  catch and see whether the bonus is in his total; flipping the flag re-scores
  everything with no code change, and `test_same_line_under_td_only_reading`
  pins the delta.
- **Turnovers are punitive for QBs.** INT is -2 (not the doc's -1), and
  "Pick Sixes Thrown" -4 **stacks on top**, so a pick-six is -6. Combined with
  only 4 pts per passing TD, this depresses high-volume gunslinger QBs.
- **Easily-missed offensive categories:** Return TD 6, Offensive Fumble Return
  TD 6. Small, but free points the generic models drop.
- **DST is more generous than Yahoo default** at the top (0 PA = 10, 1-6 = 7,
  7-13 = 4) *and* less punitive in the middle (14-20 = 2, 28-34 = -2, both
  better than the doc claimed). Plus **Extra Point Returned 2**. No
  yards-allowed tiers. Net: elite DST is worth more here than consensus says.
- **No FAAB**, continual rolling waiver priority, no waiver time, unlimited
  acquisitions, weekly processing at Tuesday game time. (Track B — not before
  Sep 3.)
- Playoffs: 6 teams, weeks 15-17. Trade deadline Nov 28 2026.

## Data sources (free only)

- **ADP** — [Fantasy Football Calculator ADP REST API](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api).
  Free for personal use; **attribution required**; do not call frequently.
- **Historical stats + player metadata** — `nflreadpy` (returns Polars).
  `nfl_data_py` was archived Sep 2025 — do not use it.
- **Sleeper is NOT used.** It was in the original plan for player metadata, but
  `load_players()` already carries name/position/team/status and nflreadpy is a
  dependency anyway. Dropping it removed a network call, a rate limit and an
  attribution obligation for nothing lost. With FFC the only HTTP endpoint left,
  stdlib `urllib` covers it — no `httpx`.
- **The 40+ yard counts are free.** nflverse ships `rushing_40` / `receiving_40`
  as counts of 40+ yard plays — exactly what our any-play bonus pays on. No
  play-by-play derivation needed. Pick sixes DO need pbp (`interception` and
  `return_touchdown`), since player_stats carries only total interceptions.

## Environment note

nflverse data **is** reachable from Claude Code web containers, so history and
player metadata can be pulled and validated here. `fantasyfootballcalculator.com`
is **not** (egress proxy returns 403), so the ADP fetch must be run locally. The
ADP path is unit-tested against `tests/fixtures/adp_ppr_12team.json` and needs
no network.

## Out of scope before Sep 3

Live Yahoo draft polling, any LLM on the clock, browser automation for lineups,
and all of Track B (lineup optimizer, DST streamer, waiver tool, trade analyzer).
