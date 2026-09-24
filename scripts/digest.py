#!/usr/bin/env python3
"""Print a compact review digest for meetings, or the minutes' text for chosen items.

    python3 scripts/digest.py <clip> [<clip> ...] [--cache DIR] [--all]
    python3 scripts/digest.py <clip> --text R.2 R.5 [--cache DIR]

The digest lists each regular-agenda item with every vote the parser found: the result, the basis
(named / unanimous / review), anyone not voting Yea, and any flags. Votes marked "review" also print
the passage they came from. Consent items are shown only when a vote on them was split (--all shows them).
--text prints the minutes' own summary text for the given items (summary-format years), or the
transcript passage, which is what synopses should be written from.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import parse_minutes as pm
from add_votes import short_title

ROOT = Path(__file__).resolve().parent.parent


def meeting(clip):
    with (ROOT / "data" / "meetings.csv").open(newline="", encoding="utf-8") as f:
        return next(r for r in csv.DictReader(f) if r["clip"] == clip)


def digest(clip, cache, show_all):
    r = meeting(clip)
    q = f"view_id=3&clip_id={clip}&doc_id={r['minutes_doc']}"
    m = pm.analyze(clip, r["date"], q, cache)
    a = m["attendance"]
    changes = [(c["name"], c["kind"], c["time"]) for c in a["changes"]]
    print(f"### {clip} {r['date']} {r['meeting']} [{m['format']}] present={','.join(a['present'])} "
          f"excused={','.join(a['excused'])}" + (f" changes={changes}" if changes else ""))
    for it in m["items"]:
        consent = it["id"].startswith("C.")
        split = any(v in ("Nay", "Abstain") for ev in it["votes"] for n, v in ev["votes"].items() if n in m["pool"])
        if consent and not split and not show_all:
            continue
        clock = f" @{it['clock']} present={','.join(it['present'])}" if it.get("clock") and any(ev["basis"] == "review" for ev in it["votes"]) else ""
        print(f"  {it['id']:5} {short_title(it['title'])[:230]}{clock}")
        for i, ev in enumerate(it["votes"]):
            others = " ".join(f"{n}={v}" for n, v in ev["votes"].items() if n in m["pool"] and v != "Yea")
            flags = ("  FLAGS:" + "; ".join(ev["flags"])[:220]) if ev["flags"] else ""
            print(f"      [{i}] {ev['outcome'][:26]:26} {ev['basis']:9} {others}{flags}")
            if ev["basis"] == "review" and not consent:
                print("          >> " + ev["window"][:500])


def item_text(clip, ids, cache):
    r = meeting(clip)
    pm.analyze(clip, r["date"], f"view_id=3&clip_id={clip}&doc_id={r['minutes_doc']}", cache)
    text = (Path(cache) / "mins" / f"{clip}.txt").read_text(encoding="utf-8")
    summary = re.search(r"\bAyes\s*\(\s*\d", text[:20000], re.I)
    t = text.split("CAPTIONS")[0] if summary else text
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    for iid in ids:
        pat = re.compile(r"(?m)^\s*" + iid.replace(".", r"\.?\s?") + r"(?![0-9])")
        m = pat.search(t)
        if not m:
            print(f"--- {iid} not found")
            continue
        nxt = re.compile(r"(?m)^\s*(?:C|R|UC|PH|PN|B)\.?\s?\d+(?![0-9])|^ADJOURNMENT").search(t, m.end())
        end = nxt.start() if nxt else m.start() + 3000
        print(f"--- {clip} {iid}\n" + re.sub(r"Page \d+ of \d+\n?", "", t[m.start():end])[:6000 if not summary else 3500])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--text", nargs="+")
    args = ap.parse_args()
    if args.text:
        item_text(args.clips[0], args.text, args.cache)
    else:
        for c in args.clips:
            try:
                digest(c, args.cache, args.all)
            except Exception as e:  # e.g. a meeting whose minutes link serves something else
                print(f"### {c} could not be read: {type(e).__name__}: {e}"[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
