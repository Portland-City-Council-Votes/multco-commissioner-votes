#!/usr/bin/env python3
"""Save the County's list of adopted Board documents to data/board_documents.json.

    python3 scripts/fetch_board_documents.py

Reads https://www.multco.us/services/board-documents (ordinances, resolutions, orders and
proclamations from 2020 on), every page, and records each document's date, number, title, type
and PDF link, merged with the documents already saved. add_votes.py uses the list to fill in doc_number and document for each logged vote.
The site is slow; expect a few minutes.
"""

import html
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://www.multco.us/services/board-documents?page={}"


def fetch(url):
    out = subprocess.run(["curl", "-sSL", "--max-time", "120", "--retry", "3", url], capture_output=True, check=True)
    return out.stdout.decode("utf-8", "replace")


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def rows_from(page):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        tds = [clean(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        link = re.search(r'href="(/file/[^"]+)"', tr)
        if len(tds) < 4:
            continue
        try:
            day = datetime.strptime(tds[0], "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            day = ""
        rows.append({"date": day, "number": tds[1], "title": re.sub(r"\s*\([\d.]+ [KM]B\)$", "", tds[2]),
                     "type": tds[3], "url": "https://www.multco.us" + html.unescape(link.group(1)) if link else ""})
    return rows


def main():
    first = fetch(URL.format(0))
    last = max([int(n) for n in re.findall(r"\?page=(\d+)", first)] or [0])
    key = lambda r: (r["date"], r["number"], r["url"])
    seen = {}
    for r in rows_from(first):
        seen.setdefault(key(r), r)
    for i in range(1, last + 1):
        page = rows_from(fetch(URL.format(i)))
        fresh = [r for r in page if key(r) not in seen]
        if not fresh:
            # Since Nov 2026 the site ignores ?page= and serves page 0 every time; stop instead of
            # saving the same 30 rows 25 times.
            print(f"Page {i} repeats earlier rows; stopping (the site's pager may be broken).", file=sys.stderr)
            break
        for r in fresh:
            seen[key(r)] = r
    # Merge with the saved list so a short or failed fetch never drops documents already recorded.
    path = ROOT / "data" / "board_documents.json"
    if path.exists():
        for r in json.loads(path.read_text(encoding="utf-8")):
            seen.setdefault(key(r), r)
    rows = sorted((r for r in seen.values() if r["date"]), key=lambda r: (r["date"], r["number"]))
    path.write_text(json.dumps(rows, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(rows)} documents ({rows[0]['date']} to {rows[-1]['date']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
