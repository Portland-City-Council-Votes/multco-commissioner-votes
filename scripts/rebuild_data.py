#!/usr/bin/env python3
"""Rebuild data/votes.csv and data/motions.csv from scratch from every picks file in data/picks/.

    python3 scripts/rebuild_data.py [--cache DIR]

The picks files are the record of every editorial decision (which items were logged, their synopses,
themes and any vote corrections after reading the minutes). Run this after changing a picks file or the
parser; it resets every meeting to pending and replays the picks in order.
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from add_votes import COMMISSIONERS, MOTION_COLS, VOTE_COLS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    args = ap.parse_args()
    data = ROOT / "data"
    for name, cols in (("votes.csv", VOTE_COLS + COMMISSIONERS), ("motions.csv", MOTION_COLS + COMMISSIONERS)):
        with (data / name).open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(cols)
    with (data / "meetings.csv").open(newline="", encoding="utf-8") as f:
        meetings = list(csv.DictReader(f))
        fields = list(meetings[0].keys())
    for m in meetings:
        if m["status"] == "done":
            m["status"], m["items_logged"] = "pending", ""
    with (data / "meetings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(meetings)
    for picks in sorted((data / "picks").glob("*.json")):
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "add_votes.py"), str(picks), "--cache", args.cache])
        if res.returncode:
            print(f"Stopped at {picks.name}.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
