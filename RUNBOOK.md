# Draft night runbook

**Thu Sep 3 2026, 11:00pm EDT.** 60-second pick clock. 12 teams, plain snake,
13 rounds, 156 picks. You are **Just Win Baby**.

Nothing below step 2 touches the network. If the wifi dies after the ADP
refresh, everything still works.

---

## Before the day (do this once, on your own machine)

```bash
pip install -e ".[dev]"
pytest                                    # 72 tests, all must pass
```

## Sep 3, early — the last networked step

```bash
python -c "from fw.sources import fetch_adp; print(fetch_adp(2026, 12, 'ppr', force=True))"
python -m fw.board --adp data/raw/adp_2026_12team_ppr.json
```

`board.py` moves any existing board to `board.prev.csv` before writing. **If the
new board looks wrong, restore that file and draft from it** — a two-day-old
board beats no board.

Sanity-check before trusting it: top 5 overall and top 3 per position should be
*defensible*. Wild divergence from consensus means a bug, not alpha.

## Sep 3, evening — pre-render everything

```bash
python -m fw.sheet --all                  # 12 slot variants, sub-second
```

Print the ones for slots you might get, or all 12. **Paper is the last line of
defence.**

Optionally check the news for anyone on your board, then write the handful of
conclusions that change a pick into `data/notes.toml` (copy `notes.example.toml`):

```bash
python -m fw.news --feed <your RSS url>      # prints a notes.toml skeleton
```

It finds the mentions; you decide what they mean. Roster status (IR, PUP,
suspended) is already flagged automatically on the board — notes are for the
soft cases a feed cannot give you structured.

---

## T-30 — 10:30pm, when the order is posted

1. **Learn your slot and the full order.**
2. Paste the 12 team names in draft-position order into `data/draft_order.txt`,
   one per line. **Optional** — without it opponents show as seat numbers and
   nothing else changes. Never let this block you.
3. Open the pre-rendered sheet for your slot (already printed).
4. Start the tracker:

```bash
python -m fw.track --slot N
```

## During the draft

| Key | Does |
|---|---|
| type a name | mark drafted — prefix is enough, typos tolerated |
| `u` | undo last pick |
| `r` | redraw |
| `q` | quit (state already saved) |

Mark **every** pick, not just yours — team attribution is free from the pick
number, and opponent needs are what sharpen the cliff warnings.

State is saved after every pick. **If it crashes, just restart it** — you resume
exactly where you stopped. Nothing is lost.

## If something breaks

| Problem | Do this |
|---|---|
| Tracker won't start | Draft off the printed sheet. |
| Board looks wrong | `cp data/board.prev.csv data/board.csv` |
| Marked the wrong player | `u` |
| Typed someone already gone | It tells you who took them and when. |
| Laptop dies | Printed sheet. This is why it exists. |

## Reminders specific to this league

- **No kicker.** 8 starters + 5 bench.
- **+2 on any 40+ yard run or reception**, scoring or not — deep threats are
  worth more here than the room thinks.
- **QB turnovers hurt**: −2 per INT, and a pick six stacks to −6, against only
  4 points per passing TD.
- **Elite DST is ~49 points above streamer level** here. Worth a real pick,
  unlike most leagues.
