"""RSS/Atom -> which of YOUR players are in the news. Runs locally, pre-draft.

Not on the draft-night path. Nothing imports this from track.py.

What this does and does not do
------------------------------
It fetches a feed, finds headlines that mention players on your board, and
prints a ready-to-paste `notes.toml` skeleton. It does NOT decide what the news
means. That boundary is deliberate: matching names to a feed is mechanical and
worth automating; judging whether "questionable, limited in practice" changes a
pick is not, and a machine-written note you did not think about is worse than
no note at all.

Why RSS rather than scraping article pages: a feed is published for
consumption, so there is no terms-of-use problem, the format is standardised,
and the stdlib parses it. Scraping a publisher's article HTML is none of those.

Both RSS 2.0 and Atom are handled, since feeds differ and you should not have to
care which one yours is.
"""

from __future__ import annotations

import argparse
import csv
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BOARD = Path("data/board.csv")

# Atom namespace; RSS 2.0 has none, so lookups try both shapes.
_ATOM = "{http://www.w3.org/2005/Atom}"


def normalize_name(name: str) -> str:
    """Same key as sources.normalize_name — duplicated to keep this standalone."""
    base = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    for suffix in (" jr", " sr", " ii", " iii", " iv", " v"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    return "".join(ch for ch in base if ch.isalnum())


def parse_feed(xml_text: str) -> list[dict]:
    """Extract (title, summary, link) from an RSS 2.0 or Atom document."""
    root = ET.fromstring(xml_text)
    items = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
    out = []
    for it in items:
        def text(*tags: str) -> str:
            for tag in tags:
                el = it.find(tag)
                if el is not None and (el.text or "").strip():
                    return el.text.strip()
            return ""

        link = text("link", f"{_ATOM}link")
        if not link:
            el = it.find(f"{_ATOM}link")
            link = el.get("href", "") if el is not None else ""
        out.append({
            "title": text("title", f"{_ATOM}title"),
            "summary": text("description", f"{_ATOM}summary", f"{_ATOM}content"),
            "link": link,
        })
    return out


def load_board_names(path: Path) -> list[tuple[str, str, str]]:
    """(display name, normalised key, position) for everyone on the board."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [(r["player"], normalize_name(r["player"]), r["position"])
            for r in rows if r.get("position") != "DEF"]


def match(entries: list[dict], players: list[tuple[str, str, str]]) -> dict[str, list[dict]]:
    """Map each mentioned player to the entries mentioning them.

    Matching is on the normalised full name only. Surnames alone would be far
    noisier than useful — a feed full of Smiths and Browns would flag half the
    board and you would stop reading the output, which is the same failure the
    cliff warnings had.
    """
    hits: dict[str, list[dict]] = {}
    for e in entries:
        blob = normalize_name(f"{e['title']} {e['summary']}")
        for display, key, _pos in players:
            if len(key) >= 8 and key in blob:
                hits.setdefault(display, []).append(e)
    return hits


def fetch(url: str, timeout: int = 30) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Find board players mentioned in a news feed. Pre-draft only.")
    ap.add_argument("--feed", help="RSS/Atom URL")
    ap.add_argument("--file", type=Path, help="a saved feed file, instead of --feed")
    ap.add_argument("--board", type=Path, default=BOARD)
    args = ap.parse_args()

    if not args.feed and not args.file:
        ap.error("give --feed URL or --file path")

    xml_text = args.file.read_text() if args.file else fetch(args.feed)
    entries = parse_feed(xml_text)
    players = load_board_names(args.board)
    hits = match(entries, players)

    print(f"# {len(entries)} feed entries, {len(hits)} board players mentioned")
    if not hits:
        print("# nothing on your board is in this feed.")
        return
    print("#\n# Paste the lines that change a pick into data/notes.toml, with your\n"
          "# own wording. Prefix with 'avoid' or 'target' to colour the flag.\n")
    print("[notes]")
    for player, es in sorted(hits.items()):
        for e in es[:2]:
            print(f'#   {e["title"]}')
            if e["link"]:
                print(f'#   {e["link"]}')
        print(f'# "{player}" = ""\n')


if __name__ == "__main__":
    main()
