#!/usr/bin/env python3
"""Append chosen items from parsed meetings to data/votes.csv and data/motions.csv.

    python3 scripts/add_votes.py picks.json [--cache DIR] [--in-progress]

picks.json maps each meeting's Granicus clip id to the items chosen from it:

    {
      "3587": {
        "R.3": {"synopsis": "...", "theme": "Homelessness; Housing"},
        "R.9": {"synopsis": "...", "theme": "FY Budget", "final": 12, "motions": [3, 4, 5],
                "votes": {"Meieran": "Nay"}, "type": "Resolution", "action": "Adopted as amended",
                "area": "Gresham", "note": "..."},
        "_note": "anything worth recording in meetings.csv"
      }
    }

For each item the script runs scripts/parse_minutes.py, takes the item's final vote (the last vote the
parser found under that item, or the index given in "final"), and appends one row to votes.csv. Every
other vote under the item goes to motions.csv (or only the indices listed in "motions"). A vote the parser
marked "review" is refused unless the pick says "reviewed": true, which records that a person read the
minutes for that vote and wrote any corrections into "votes". The meeting is marked done in meetings.csv
unless --in-progress is given. Rows already in the files are never duplicated.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import parse_minutes as pm

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NOT_IN_OFFICE = "Not in office"
COMMISSIONERS = [c["name"] for c in pm.COMMISSIONERS]

THEMES = [
    "FY Budget", "Housing", "Homelessness", "Public Safety", "Health & Social Services", "Budget & Taxes",
    "Transportation", "Environment & Energy", "Economic Development", "Land Use & Planning",
    "Parks & Recreation", "Arts & Culture", "Libraries", "Early Childhood & Education", "Civil Rights & Equity",
    "Business Regulation", "Labor & Workforce", "Elections", "Animal Services", "Government Operations",
    "Government Transparency",
]
TYPES = ["Ordinance", "Emergency ordinance", "Resolution", "Order", "Budget modification", "Supplemental budget",
         "Intergovernmental agreement", "Contract", "Settlement", "Appointment", "Motion", "Other"]
VOTE_COLS = ["date", "item", "doc_number", "title", "synopsis", "type", "action", "theme", "area", "minutes", "url"]
MOTION_COLS = ["date", "item", "seq", "item_title", "kind", "motion", "note", "theme", "area", "url"]
PROCEDURAL = re.compile(r"POSTPONE|CONTINUE|RECONSIDER|TABLE|SUSPEND|REFER|RECESS|WITHDRAW|RESCIND|CALL THE QUESTION|"
                        r"REORDER|EXTEND|UNANIMOUS CONSENT|FIRST READING", re.I)


def short_title(title):
    """Official title without the presenter list and time estimate."""
    t = re.split(r"\s+Presenters?\s*:|\s+Presenter\(s\)\s*:|\s+Sponsors?\s*:|\s+Speakers?\s*:", title)[0]
    t = re.sub(r"\s*\(\s*\d+\s*(?:min|minutes|hours?)\.?\s*\)\s*$", "", t)
    t = re.sub(r"^\s*(?:-\s*)?(?:POSTPONED|CORRECTED TITLE)\s*[-:]\s*", "", t, flags=re.I)
    return t.strip().rstrip(".").strip() + "."


def infer_type(title, outcome):
    t, o = title.upper(), outcome.upper()
    if "SUPPLEMENTAL BUDGET" in t:
        return "Supplemental budget"
    if re.search(r"BUDGET MODIFICATION|BUD\s?MOD", t):
        return "Budget modification"
    if "ORDINANCE" in t or "ORDINANCE" in o:
        return "Emergency ordinance" if re.search(r"EMERGENCY", t + " " + o) else "Ordinance"
    if "ORDER" in o and "ORDER" in t:
        return "Order"
    if re.search(r"SETTLEMENT", t):
        return "Settlement"
    if re.search(r"RESOLUTION", t + " " + o):
        return "Resolution"
    if re.search(r"INTERGOVERNMENTAL|\bIGA\b", t):
        return "Intergovernmental agreement"
    if re.search(r"CONTRACT|PROCUREMENT|PURCHASE|LEASE", t):
        return "Contract"
    if re.search(r"APPOINT|VACANCY", t):
        return "Appointment"
    return "Other"


def action_of(outcome, amended=False):
    o = outcome.upper()
    for word, label in (("FAIL", "Failed"), ("DEFEAT", "Failed"), ("DENIED", "Denied"), ("REJECT", "Failed"),
                        ("POSTPONED", "Postponed"), ("CONTINUED", "Continued"), ("TABLED", "Tabled"),
                        ("REFERRED", "Referred"), ("WITHDRAWN", "Withdrawn"), ("ADOPTED", "Adopted"),
                        ("RATIFIED", "Ratified"), ("APPOINTED", "Appointed"), ("ELECTED", "Appointed"),
                        ("SELECTED", "Appointed"), ("CONFIRMED", "Confirmed"), ("AUTHORIZED", "Approved"),
                        ("ACCEPTED", "Accepted"), ("ACKNOWLEDGED", "Accepted"), ("CARRIES", "Approved"),
                        ("PASSES", "Approved"), ("PASSED", "Approved"), ("APPROVED", "Approved")):
        if word in o:
            return label + (" as amended" if amended and label in ("Adopted", "Approved") else "")
    return "Approved"


def motion_text(ev):
    """The motion as the minutes put it: the last sentence before the vote that makes or names a motion."""
    before = re.sub(r"\s+", " ", ev["before"])
    sentences = re.split(r"(?<=[.?!])\s+", before)
    picked = [s for s in sentences if re.search(r"\bMOVE|MOTION|AMEND|BUDGET NOTE", s, re.I)]
    text = " ".join(picked[-2:]) if picked else ""
    text = re.sub(r"^.*?:\s*", "", text) if re.match(r"^[A-Z][a-z]", text) and ":" in text[:40] else text
    text = text[-400:].strip()
    return (text + " — " if text else "") + ev["outcome"].capitalize() + "."


def kind_of(text):
    if re.search(r"\bAMEND", text, re.I):
        return "Amendment"
    if PROCEDURAL.search(text):
        return "Procedural"
    return "Motion"


def fill(votes, date):
    pool = pm.in_office(date)
    return {n: (votes.get(n) or "Absent") if n in pool else NOT_IN_OFFICE for n in COMMISSIONERS}


def load_csv(path, cols):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def write_csv(path, cols, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("picks")
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    ap.add_argument("--in-progress", action="store_true")
    args = ap.parse_args()

    picks = json.loads(Path(args.picks).read_text(encoding="utf-8"))
    meetings = load_csv(DATA / "meetings.csv", None)
    by_clip = {m["clip"]: m for m in meetings}
    vcols = VOTE_COLS + COMMISSIONERS
    mcols = MOTION_COLS + COMMISSIONERS
    votes = load_csv(DATA / "votes.csv", vcols)
    motions = load_csv(DATA / "motions.csv", mcols)
    have_v = {(r["date"], r["item"]) for r in votes}
    have_m = {(r["date"], r["item"], r["seq"]) for r in motions}
    problems, added_v, added_m = [], 0, 0

    for clip, chosen in picks.items():
        meet = by_clip.get(clip)
        if not meet:
            problems.append(f"clip {clip} is not in meetings.csv")
            continue
        query = f"view_id=3&clip_id={clip}&doc_id={meet['minutes_doc']}" if meet["minutes_doc"] else None
        m = pm.analyze(clip, meet["date"], query, args.cache)
        items = {it["id"]: it for it in m["items"]}
        logged = 0
        for iid, p in chosen.items():
            if iid.startswith("_"):
                continue
            it = items.get(iid)
            if not it:
                problems.append(f"{meet['date']} {iid}: not on the agenda")
                continue
            evs = it["votes"]
            if not evs and "votes" not in p:
                problems.append(f"{meet['date']} {iid}: no vote found in the minutes; add \"votes\" and \"outcome\" by hand")
                continue
            fi = p.get("final", len(evs) - 1)
            ev = evs[fi] if evs else {"votes": {}, "basis": "review", "flags": [], "outcome": p.get("outcome", "")}
            if ev["basis"] == "review" and not p.get("reviewed"):
                problems.append(f"{meet['date']} {iid}: final vote needs review {ev['flags']} :: {ev.get('window', '')[:300]}")
                continue
            for k in p.get("theme", "").split("; "):
                if k not in THEMES:
                    problems.append(f"{meet['date']} {iid}: unknown theme {k!r}")
            date = p.get("date", meet["date"])
            vote = dict(ev["votes"])
            vote.update(p.get("votes", {}))
            title = p.get("title") or short_title(it["title"])
            amended = any(kind_of(motion_text(e)) == "Amendment" and not re.search(r"FAIL", e["outcome"]) for e in evs[:fi])
            row = {
                "date": date, "item": iid, "doc_number": p.get("doc_number", ""), "title": title,
                "synopsis": p["synopsis"], "type": p.get("type") or infer_type(it["title"], ev["outcome"]),
                "action": p.get("action") or action_of(ev["outcome"], amended), "theme": p["theme"],
                "area": p.get("area", "Countywide"), "minutes": m["minutes_url"] or "", "url": m["agenda_url"],
                **fill(vote, date),
            }
            if (date, iid) not in have_v:
                votes.append(row)
                have_v.add((date, iid))
                added_v += 1
            logged += 1
            wanted = p.get("motions", [i for i in range(len(evs)) if i != fi])
            for seq, i in enumerate(wanted, start=1):
                e = evs[i]
                if e["basis"] == "review" and str(i) not in p.get("reviewed_motions", {}) and not p.get("reviewed"):
                    problems.append(f"{meet['date']} {iid} motion {i}: needs review {e['flags']} :: {e['window'][:300]}")
                    continue
                mv = dict(e["votes"])
                mv.update(p.get("reviewed_motions", {}).get(str(i), {}))
                text = p.get("motion_text", {}).get(str(i)) or motion_text(e)
                mrow = {"date": date, "item": iid, "seq": str(seq), "item_title": title, "kind": kind_of(text),
                        "motion": text, "note": p.get("motion_notes", {}).get(str(i), ""), "theme": p["theme"],
                        "area": row["area"], "url": m["agenda_url"], **fill(mv, date)}
                if (date, iid, str(seq)) not in have_m:
                    motions.append(mrow)
                    have_m.add((date, iid, str(seq)))
                    added_m += 1
        if not args.in_progress:
            meet["status"] = "done"
            meet["items_logged"] = str(sum(1 for r in votes if r["url"].endswith(f"clip_id={clip}")))
        if chosen.get("_note"):
            meet["notes"] = chosen["_note"]

    if problems:
        print("Nothing written. Fix these first:\n  " + "\n  ".join(problems))
        return 1
    votes.sort(key=lambda r: (r["date"], r["item"]))
    motions.sort(key=lambda r: (r["date"], r["item"], int(r["seq"])))
    write_csv(DATA / "votes.csv", vcols, votes)
    write_csv(DATA / "motions.csv", mcols, motions)
    write_csv(DATA / "meetings.csv", list(meetings[0].keys()), meetings)
    print(f"Added {added_v} final votes and {added_m} motion votes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
