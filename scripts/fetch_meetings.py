#!/usr/bin/env python3
"""Add new Board meetings from the Granicus archive to data/meetings.csv.

    python3 scripts/fetch_meetings.py            # update data/meetings.csv
    python3 scripts/fetch_meetings.py --dry-run  # only report

Reads the Board Clerk's archive (ViewPublisher.php?view_id=3), keeps meetings from 2017 on that can
carry a vote (regular and special meetings, public and budget hearings, joint meetings, legislative
vacancy appointments) and skips briefings, work sessions, ceremonies, proclamation signings, TSCC
hearings and public notices. A meeting not yet in the CSV is added as `pending`; a pending meeting
whose minutes have since been posted gets its minutes_doc filled in. Nothing else is changed.

Minutes are usually posted a few weeks after a meeting, so a pending meeting with no minutes_doc
is waiting on the Clerk, not on us.
"""

import argparse
import csv
import html
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEETINGS = ROOT / "data" / "meetings.csv"
URL = "https://multnomah.granicus.com/ViewPublisher.php?view_id=3"
COLS = ["date", "clip", "meeting", "minutes_doc", "status", "items_logged", "notes"]
SKIP = re.compile(r"briefing|work ?session|worksession|ceremony|proclamation|TSCC|years of service|recognition|"
                  r"award|retreat|listening|swearing|public notice|city/county joint", re.I)


def fetch(url):
    out = subprocess.run(["curl", "-sSL", "--max-time", "300", "--retry", "3", "-A", "Mozilla/5.0", url],
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8", "replace")


def listing(page):
    """(date, clip, name, minutes_doc) for every archived meeting on the page."""
    for row in re.findall(r"<tr>(.*?)</tr>", page, re.S):
        name = re.search(r'headers="Name"[^>]*>(.*?)</td>', row, re.S)
        clip = re.search(r"clip_id=(\d+)", row)
        date = re.search(r"([A-Z][a-z]{2}) +(\d{1,2}), (\d{4})", row)
        if not (name and clip and date):
            continue
        name = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", name.group(1)))).strip()
        when = datetime.strptime(" ".join(date.groups()), "%b %d %Y").date().isoformat()
        doc = re.search(r"MinutesViewer\.php\?[^\"']*doc_id=([\w-]+)", row)
        yield when, clip.group(1), name, doc.group(1) if doc else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with MEETINGS.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_clip = {r["clip"]: r for r in rows}

    added, filled = [], []
    for date, clip, name, doc in listing(fetch(URL)):
        if date < "2017-01-01" or SKIP.search(name):
            continue
        row = by_clip.get(clip)
        if row is None:
            row = {"date": date, "clip": clip, "meeting": name, "minutes_doc": doc,
                   "status": "cancelled" if re.search(r"cancel", name, re.I) else "pending",
                   "items_logged": "", "notes": "" if doc else "No minutes posted yet."}
            rows.append(row)
            by_clip[clip] = row
            added.append(row)
        elif row["status"] == "pending" and doc and not row["minutes_doc"]:
            row["minutes_doc"] = doc
            if row["notes"] == "No minutes posted yet.":
                row["notes"] = ""
            filled.append(row)

    for r in added:
        print(f"added   {r['date']} clip {r['clip']} {r['meeting']}" + ("" if r["minutes_doc"] else "  (no minutes yet)"))
    for r in filled:
        print(f"minutes {r['date']} clip {r['clip']} {r['meeting']}")
    ready = [r for r in rows if r["status"] == "pending" and r["minutes_doc"]]
    waiting = [r for r in rows if r["status"] == "pending" and not r["minutes_doc"]]
    print(f"{len(added)} added, {len(filled)} with new minutes; {len(ready)} pending meeting(s) ready to log, "
          f"{len(waiting)} waiting on minutes.")

    if not args.dry_run and (added or filled):
        rows.sort(key=lambda r: (r["date"], int(r["clip"])))
        with MEETINGS.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
