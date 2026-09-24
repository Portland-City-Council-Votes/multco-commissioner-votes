#!/usr/bin/env python3
"""Check the data files against the schema in CLAUDE.md.

Run from the repo root:  python3 scripts/validate_data.py
Exits non-zero and prints every problem found if anything is wrong.
"""

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

from add_votes import MOTION_COLS, NOT_IN_OFFICE, THEMES, TYPES, VOTE_COLS

ROOT = Path(__file__).resolve().parent.parent
COMMISSIONERS = json.loads((ROOT / "assets" / "commissioners.json").read_text(encoding="utf-8"))
NAMES = [c["name"] for c in COMMISSIONERS]
VOTES = {"Yea", "Nay", "Absent", "Abstain"}
MEETING_COLS = ["date", "clip", "meeting", "minutes_doc", "status", "items_logged", "notes"]
MEETING_STATUSES = {"pending", "done", "cancelled"}
GRANICUS = re.compile(r"^https://multnomah\.granicus\.com/")
ITEM = re.compile(r"^(?:C|R|UC|B|PH|PN|E|S|WS)\.\d{1,2}[a-z]?$")


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def in_office(name, day):
    c = next(c for c in COMMISSIONERS if c["name"] == name)
    return any(t["start"] <= day and (not t["end"] or day <= t["end"]) for t in c["terms"])


def check_commissioners(errors):
    seen = set()
    for c in COMMISSIONERS:
        for key in ("name", "full_name", "slug", "terms"):
            if not c.get(key):
                errors.append(f"commissioners.json: {c.get('name')} is missing {key}")
        if c["name"] in seen:
            errors.append(f"commissioners.json: duplicate {c['name']}")
        seen.add(c["name"])
        for t in c["terms"]:
            if parse_date(t["start"]) is None or (t["end"] and parse_date(t["end"]) is None):
                errors.append(f"commissioners.json: {c['name']} has a bad term date {t}")
            if t["seat"] not in {"Chair", "District 1", "District 2", "District 3", "District 4"}:
                errors.append(f"commissioners.json: {c['name']} has unknown seat {t['seat']!r}")
        if c.get("photo") and not (ROOT / c["photo"]).exists():
            errors.append(f"commissioners.json: photo {c['photo']} not found")
    # No two people hold the same seat on the same day.
    spans = [(t["seat"], t["start"], t["end"] or "9999", c["name"]) for c in COMMISSIONERS for t in c["terms"]]
    for i, a in enumerate(spans):
        for b in spans[i + 1:]:
            if a[0] == b[0] and a[1] < b[2] and b[1] < a[2] and not (a[2] == b[1] or b[2] == a[1]):
                errors.append(f"commissioners.json: {a[3]} and {b[3]} overlap in {a[0]}")


def check_vote_cells(where, row, errors):
    """Each commissioner cell: a vote while in office, 'Not in office' otherwise. A blank is allowed only
    in motions.csv with a note saying why (the minutes contradict themselves)."""
    recorded = 0
    for name in NAMES:
        v = row[name]
        if in_office(name, row["date"]):
            if v == "" and row.get("note"):
                continue
            if v not in VOTES:
                errors.append(f"{where}: {name} was in office on {row['date']} but the vote is {v!r}")
            recorded += v in ("Yea", "Nay", "Abstain")
        elif v != NOT_IN_OFFICE:
            errors.append(f"{where}: {name} wasn't in office on {row['date']}; must be {NOT_IN_OFFICE!r}, not {v!r}")
    if recorded == 0:
        errors.append(f"{where}: nobody voted")


def check_votes(errors):
    path = ROOT / "data" / "votes.csv"
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        expected = VOTE_COLS + NAMES
        if reader.fieldnames != expected:
            errors.append(f"{path.name}: header must be exactly: {','.join(expected)}")
            return
        seen = set()
        for line, row in enumerate(reader, start=2):
            where = f"{path.name}:{line}"
            if None in row:
                errors.append(f"{where}: more fields than the header")
                continue
            if parse_date(row["date"]) is None:
                errors.append(f"{where}: date {row['date']!r} is not YYYY-MM-DD")
                continue
            if not ITEM.match(row["item"]):
                errors.append(f"{where}: item {row['item']!r} should look like R.3")
            for col in ("title", "synopsis", "action", "theme", "area"):
                if not row[col].strip():
                    errors.append(f"{where}: {col} is empty")
            bad = [t for t in row["theme"].split("; ") if t not in THEMES]
            if bad:
                errors.append(f"{where}: unknown theme(s) {bad}; see THEMES in scripts/add_votes.py")
            if row["type"] not in TYPES:
                errors.append(f"{where}: type {row['type']!r} not one of {TYPES}")
            if row["document"] and not row["document"].startswith("https://www.multco.us/"):
                errors.append(f"{where}: document should be a multco.us link (or blank)")
            if not GRANICUS.match(row["url"]) or (row["minutes"] and not GRANICUS.match(row["minutes"])):
                errors.append(f"{where}: url and minutes should point at multnomah.granicus.com")
            key = (row["date"], row["item"])
            if key in seen:
                errors.append(f"{where}: duplicate of {row['item']} on {row['date']}")
            seen.add(key)
            check_vote_cells(where, row, errors)


def check_motions(errors):
    path = ROOT / "data" / "motions.csv"
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        expected = MOTION_COLS + NAMES
        if reader.fieldnames != expected:
            errors.append(f"{path.name}: header must be exactly: {','.join(expected)}")
            return
        seen = set()
        for line, row in enumerate(reader, start=2):
            where = f"{path.name}:{line}"
            if parse_date(row["date"]) is None:
                errors.append(f"{where}: date {row['date']!r} is not YYYY-MM-DD")
                continue
            if row["kind"] not in {"Amendment", "Procedural", "Motion"}:
                errors.append(f"{where}: kind {row['kind']!r} not Amendment/Procedural/Motion")
            if not row["motion"].strip() or not row["item_title"].strip():
                errors.append(f"{where}: motion and item_title are required")
            bad = [t for t in row["theme"].split("; ") if t not in THEMES]
            if bad:
                errors.append(f"{where}: unknown theme(s) {bad}")
            key = (row["date"], row["item"], row["seq"])
            if key in seen:
                errors.append(f"{where}: duplicate roll call {key}")
            seen.add(key)
            check_vote_cells(where, row, errors)


def check_meetings(errors):
    path = ROOT / "data" / "meetings.csv"
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != MEETING_COLS:
            errors.append(f"{path.name}: header must be exactly: {','.join(MEETING_COLS)}")
            return
        seen = set()
        for line, row in enumerate(reader, start=2):
            where = f"{path.name}:{line}"
            if parse_date(row["date"]) is None:
                errors.append(f"{where}: date {row['date']!r} is not YYYY-MM-DD")
            if not row["clip"].isdigit() or row["clip"] in seen:
                errors.append(f"{where}: clip must be a unique number")
            seen.add(row["clip"])
            if row["status"] not in MEETING_STATUSES:
                errors.append(f"{where}: status {row['status']!r} not one of {sorted(MEETING_STATUSES)}")
            if row["status"] == "done" and not row["items_logged"].isdigit():
                errors.append(f"{where}: a done meeting needs items_logged (a number, 0 is fine)")


def check_news(errors):
    path = ROOT / "data" / "news.csv"
    with (ROOT / "data" / "votes.csv").open(newline="", encoding="utf-8") as f:
        keys = {(r["date"], r["item"]) for r in csv.DictReader(f)}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["date", "item", "outlet", "headline", "url", "image"]:
            errors.append(f"{path.name}: header must be exactly: date,item,outlet,headline,url,image")
            return
        seen = set()
        for line, row in enumerate(reader, start=2):
            where = f"{path.name}:{line}"
            if (row["date"], row["item"]) not in keys:
                errors.append(f"{where}: {row['date']} {row['item']} is not in votes.csv")
            if not row["headline"].strip() or not row["outlet"].strip():
                errors.append(f"{where}: headline and outlet are required")
            if not row["url"].startswith("https://"):
                errors.append(f"{where}: url must start with https://")
            if "oregonlive.com" in row["url"] and not row["url"].endswith("?outputType=amp"):
                errors.append(f"{where}: OregonLive links must end with ?outputType=amp")
            if row["image"] and not row["image"].startswith("https://"):
                errors.append(f"{where}: image must be an https:// URL (or blank)")
            if (row["date"], row["item"], row["url"]) in seen:
                errors.append(f"{where}: duplicate link")
            seen.add((row["date"], row["item"], row["url"]))


def main():
    errors = []
    check_commissioners(errors)
    check_votes(errors)
    check_motions(errors)
    check_meetings(errors)
    check_news(errors)
    if errors:
        print("\n".join(errors[:200]))
        print(f"\n{len(errors)} problem(s) found.")
        return 1
    print("Data files look good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
