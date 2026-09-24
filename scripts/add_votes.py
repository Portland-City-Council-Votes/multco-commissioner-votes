#!/usr/bin/env python3
"""Append chosen items from parsed meetings to data/votes.csv and data/motions.csv.

    python3 scripts/add_votes.py picks.json [--cache DIR] [--in-progress]

picks.json maps each meeting's Granicus clip id to the items chosen from it:

    {
      "3587": {
        "R.3": {"synopsis": "...", "theme": "Homelessness; Housing"},
        "R.6": {"motions_only": true, "theme": "Public Safety"},
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
VOTE_COLS = ["date", "item", "doc_number", "document", "title", "synopsis", "type", "action", "theme", "area", "record",
             "minutes", "url"]
# How the minutes record the vote (shown on the site for anything but "named" and "unanimous").
RECORDS = ["named", "unanimous", "voice vote", "not itemized", "inferred", "partial", "by hand"]
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
    for word, label in (("NOT PASS", "Failed"), ("NOT CARRY", "Failed"), ("FAIL", "Failed"), ("DEFEAT", "Failed"), ("DENIED", "Denied"), ("REJECT", "Failed"),
                        ("POSTPONED", "Postponed"), ("CONTINUED", "Continued"), ("TABLED", "Tabled"),
                        ("REFERRED", "Referred"), ("WITHDRAWN", "Withdrawn"), ("ADOPTED", "Adopted"),
                        ("RATIFIED", "Ratified"), ("APPOINTED", "Appointed"), ("ELECTED", "Appointed"),
                        ("SELECTED", "Appointed"), ("CONFIRMED", "Confirmed"), ("AUTHORIZED", "Approved"),
                        ("ACCEPTED", "Accepted"), ("ACKNOWLEDGED", "Accepted"), ("CARRIES", "Approved"),
                        ("PASSES", "Approved"), ("PASSED", "Approved"), ("APPROVED", "Approved")):
        if word in o:
            return label + (" as amended" if amended and label in ("Adopted", "Approved") else "")
    return "Approved"


def outcome_text(ev):
    """The result sentence as the minutes word it (sentence case if the minutes are in capitals)."""
    w = re.sub(r"Page \d+ of \d+", " ", ev.get("window", ""))
    m = pm.OUTCOME.search(w)
    if m:
        # The whole sentence around the result ("The first reading is approved as amended").
        start = max(w.rfind(". ", 0, m.start()) + 2, w.rfind(": ", 0, m.start()) + 2, 0)
        end = w.find(".", m.end())
        raw = w[start:end if end != -1 else len(w)].strip()
        if not raw.startswith("The ") and " The " in raw:
            raw = raw[raw.index(" The ") + 1:]
        names = re.search(r"(?:Commissioner|Chair|Vice)[^.]*$", raw)
        if len(raw) > 160 or names:
            raw = m.group(0)
    else:
        raw = ev["outcome"]
    if raw.isupper():
        raw = raw.lower()
        raw = re.sub(r"\b(\d+[a-z]?)\b", lambda x: x.group(1).upper(), raw)
    return raw[0].upper() + raw[1:]


def motion_text(ev):
    """The motion as the minutes put it: the amendment label and the moves/seconds clauses before the vote."""
    before = re.sub(r"\s+", " ", re.sub(r"Page \d+ of \d+", " ", ev["before"]))
    label = re.findall(r"\b(Amendments? [0-9][\w]*(?:\s*-\s*[0-9][\w]*)?\.|[A-Z][\w ]{0,40} Amendments? - Amendments? [0-9][\w\- ]*\.)", before)
    moves = re.findall(r"(?:Commissioner|Vice[\s-]*Chair|Chair|Comm\.)\s[A-Z][\w\-]*(?:[\s-][A-Z][\w\-]*)?\s(?:moves|moved|motions|makes|proposes|passes the gavel)[^.]*\.", before)
    if not moves:
        sentences = re.split(r"(?<=[.?!])\s+", before)
        moves = [x for x in sentences if re.search(r"\bMOVE|MOTION|AMEND|BUDGET NOTE", x, re.I)][-2:]
    text = " ".join(([label[-1]] if label else []) + moves[-2:]).strip()
    text = re.sub(r"(?<=\w)- (?=[A-Z][a-z])", "-", text)[-400:]
    return (text + " — " if text else "") + outcome_text(ev) + "."


def kind_of(text):
    if re.search(r"\bAMEND", text, re.I):
        return "Amendment"
    if PROCEDURAL.search(text):
        return "Procedural"
    return "Motion"


def fill(votes, date):
    """Every commissioner column: the vote (a deliberate blank stays blank), 'Not in office' outside their term."""
    pool = pm.in_office(date)
    return {n: votes.get(n, "Absent") if n in pool else NOT_IN_OFFICE for n in COMMISSIONERS}


def _words(text):
    stop = {"the", "a", "an", "of", "and", "to", "for", "in", "on", "by", "with", "as", "at", "or", "from",
            "resolution", "ordinance", "order", "multnomah", "county", "oregon", "approving", "adopting"}
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in stop and len(w) > 1}


BOARD_DOCS = None


def match_document(date, title):
    """The adopted document (number, PDF link) whose title best matches this item on the same date, if any."""
    global BOARD_DOCS
    if BOARD_DOCS is None:
        path = DATA / "board_documents.json"
        BOARD_DOCS = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    want = _words(title)
    best, score = None, 0.0
    for d in BOARD_DOCS:
        if d["date"] != date or d["type"] == "Other":
            continue
        have = _words(d["title"])
        if not want or not have:
            continue
        sim = len(want & have) / len(want | have)
        if sim > score:
            best, score = d, sim
    return best if score >= 0.45 else None


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
            if p.get("manual"):
                # A vote typed in from the minutes by hand (a joint meeting whose minutes don't follow the agenda
                # format, or a transcript the parser can't follow, e.g. an item taken out of order). The pick must
                # give the outcome and every vote, and the synopsis or a note should say what the minutes show.
                # "manual_motions" lists any roll calls taken before the final vote, each with its motion text, outcome and votes.
                pre = [{"votes": mm["votes"], "basis": "named", "flags": [], "outcome": mm["outcome"], "motion": mm["motion"],
                        "note": mm.get("note", ""), "window": "", "before": ""} for mm in p.get("manual_motions", [])]
                it = {"id": iid, "title": p.get("title") or (it or {}).get("title", ""), "votes": pre + [{"votes": p["votes"], "basis": "named", "flags": [],
                                                                  "outcome": p["outcome"], "window": "", "before": ""}]}
            if not it:
                problems.append(f"{meet['date']} {iid}: not on the agenda")
                continue
            evs = it["votes"]
            if not evs and "votes" not in p:
                problems.append(f"{meet['date']} {iid}: no vote found in the minutes; add \"votes\" and \"outcome\" by hand")
                continue
            fi = p.get("final", len(evs) - 1)
            ev = evs[fi] if evs else {"votes": {}, "basis": "review", "flags": [], "outcome": p.get("outcome", "")}
            if ev["basis"] == "review" and not p.get("reviewed") and not p.get("motions_only"):
                problems.append(f"{meet['date']} {iid}: final vote needs review {ev['flags']} :: {ev.get('window', '')[:300]}")
                continue
            if not p.get("motions_only") and not p.get("synopsis"):
                problems.append(f"{meet['date']} {iid}: synopsis is required")
            for k in p.get("theme", "").split("; "):
                if k not in THEMES:
                    problems.append(f"{meet['date']} {iid}: unknown theme {k!r}")
            date = p.get("date", meet["date"])
            vote = {n: (v or "Absent") for n, v in ev["votes"].items()}
            vote.update(p.get("votes", {}))
            title = p.get("title") or short_title(it["title"])
            amended = any(kind_of(e.get("motion") or motion_text(e)) == "Amendment" and not re.search(r"FAIL|NOT PASS|NOT CARRY", e["outcome"]) for e in evs[:fi])
            if p.get("record"):
                record = p["record"]
            elif p.get("manual"):
                record = "by hand"
            elif any(f.startswith("roll call not itemized") for f in ev["flags"]):
                record = "not itemized"
            elif any(" named; others present filled in" in f for f in ev["flags"]) or (ev["basis"] == "review" and p.get("reviewed")
                                                                                      and any(v == "" for v in vote.values())):
                record = "inferred"
            elif ev["basis"] == "unanimous" and not re.search(r"UNANIM|CHORUS|ALL AYES|\[\s*AYES", ev.get("window", ""), re.I):
                record = "voice vote"
            elif ev["basis"] == "unanimous":
                record = "unanimous"
            else:
                record = "named"
            if any(v == "" for n, v in vote.items() if n in pm.in_office(date)):
                record = "partial"
            doc = match_document(date, title) if "document" not in p else None
            row = {
                "date": date, "item": iid, "title": title,
                "doc_number": p.get("doc_number", doc["number"] if doc else ""),
                "document": p.get("document", doc["url"] if doc else ""),
                "synopsis": p.get("synopsis", ""), "type": p.get("type") or infer_type(it["title"], ev["outcome"]),
                "action": p.get("action") or action_of(ev["outcome"], amended), "theme": p["theme"],
                "area": p.get("area", "Countywide"), "record": record,
                "minutes": m["minutes_url"] or "", "url": m["agenda_url"],
                **fill(vote, date),
            }
            if p.get("motions_only"):
                # An earlier reading or a tabled item: its roll calls go to motions.csv, the final vote is logged later.
                wanted = p.get("motions", list(range(len(evs))))
            else:
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
                mv = {n: (v or "Absent") for n, v in e["votes"].items()}
                mv.update(p.get("reviewed_motions", {}).get(str(i), {}))
                text = p.get("motion_text", {}).get(str(i)) or e.get("motion") or motion_text(e)
                mrow = {"date": date, "item": iid, "seq": str(seq), "item_title": title, "kind": kind_of(text),
                        "motion": text, "note": p.get("motion_notes", {}).get(str(i), e.get("note", "")), "theme": p["theme"],
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
