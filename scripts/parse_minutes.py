#!/usr/bin/env python3
"""Read one Board meeting from the Granicus archive into structured items and votes.

    python3 scripts/parse_minutes.py <clip_id> [--json out.json] [--cache DIR] [--quiet]

Sources, all on multnomah.granicus.com (the Board Clerk's archive):
  * AgendaViewer.php?view_id=3&clip_id=N  – item numbers (C.1, R.3 ...) and official titles
  * MediaPlayer.php?view_id=3&clip_id=N   – video index: seconds into the recording when each item began
  * MinutesViewer.php?...&doc_id=...      – the official minutes (PDF, sometimes .docx)

The minutes come in three shapes over the years:
  * "summary" (late 2024 on): an action summary with named lists, "Ayes (4): ... Nays (1): ...".
  * "transcript" (2017-2024): near-verbatim captions. Votes appear as named roll calls
    ("Commissioner Meieran: AYE."), as "[UNANIMOUS AYES]" / "[CHORUS OF AYES]", or as a voice vote
    ("ALL THOSE IN FAVOR VOTE AYE. THE RESOLUTION IS ADOPTED."). Dissent shows up as a named roll call,
    or after "OPPOSED?" ("OPPOSED? Commissioner Smith: AYE." means Smith voted no), or in a bracketed note.

Each vote is tagged with a basis:
  * named      – every vote listed by name in the minutes
  * unanimous  – minutes say unanimous (or a voice vote with no opposition recorded); every member present is Yea
  * review     – anything else (opposition, abstention, recusal, someone leaving or arriving close to the item,
                 a roll call with names missing). These must be read by a person before they are logged.

Attendance: the opening paragraph lists who was present or excused and anyone who arrived or left, with
clock times. Item clock times come from the video index (meeting start + offset). A member who arrived or left
within 10 minutes of an item's start is flagged for review instead of guessed.
"""

import argparse
import html as htmllib
import json
import re
import subprocess
import sys
import urllib.parse
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://multnomah.granicus.com"
COMMISSIONERS = json.loads((ROOT / "assets" / "commissioners.json").read_text(encoding="utf-8"))

# Extra spellings seen in the minutes and captions.
ALIASES = {
    "Jones-Dixon": ["VJD", "Jones Dixon"],
    "Moyer": ["Moyers"],
    "Brim-Edwards": ["Brim Edwards", "Brim"],
    "Vega Pederson": ["Vega Peterson", "Vega-Pederson", "JVP", "Vega Oederson", "Pederson", "Peterson"],
    "Beason": ["Beasman", "Beasan", "Beeson", "Beesan", "Beesen"],
    "Stegmann": ["Stegman"],
    "Meieran": ["Meiran", "Meieren", "Maiaran"],
}


def loose(word):
    """Regex that tolerates the stray spaces PDF extraction puts inside words ("Steg mann")."""
    parts = []
    for ch in word:
        if ch in " -":
            parts.append(r"[\s\-]*")
        else:
            parts.append(re.escape(ch) + r"\s?")
    return "".join(parts)


NAME_RES = {}
for c in COMMISSIONERS:
    variants = [c["name"], c["full_name"]] + ALIASES.get(c["name"], [])
    NAME_RES[c["name"]] = re.compile(r"(?<![A-Za-z])(?:" + "|".join(loose(v) for v in sorted(variants, key=len, reverse=True)) + r")(?!(?-i:[a-z]))", re.I)


def in_office(date):
    """Commissioners holding a seat on this date (YYYY-MM-DD)."""
    out = []
    for c in COMMISSIONERS:
        if any(t["start"] <= date and (not t["end"] or date <= t["end"]) for t in c["terms"]):
            out.append(c["name"])
    return out


def names_in(text, pool):
    """Commissioners (from pool) mentioned in text, in order of first mention."""
    hits = []
    for n in pool:
        m = NAME_RES[n].search(text)
        if m:
            hits.append((m.start(), n))
    return [n for _, n in sorted(hits)]


# ---------------------------------------------------------------- fetching

def fetch(url, binary=False):
    out = subprocess.run(["curl", "-sSL", "--max-time", "120", "--retry", "3", url], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def cached(cache, name, producer):
    if cache:
        path = Path(cache) / name
        if path.exists() and path.stat().st_size > 200:
            return path.read_text(encoding="utf-8")
        text = producer()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return text
    return producer()


def minutes_document_url(minutes_query):
    """MinutesViewer redirects to a Google Docs viewer wrapping DocumentViewer.php; return the direct file URL."""
    out = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w", "%{redirect_url}", "--max-time", "60",
                          f"{BASE}/MinutesViewer.php?{minutes_query}"], capture_output=True, text=True)
    loc = out.stdout.strip()
    if "gview" in loc:
        loc = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["url"][0]
    if loc.startswith("/"):
        loc = BASE + loc
    return loc if "DocumentViewer.php" in loc else None


def ocr_pdf(data, max_pages=12):
    """Scanned minutes have no text layer: render the first pages and read them with tesseract.
    The action summary is always at the front, so the transcript pages after it aren't needed."""
    import io
    import tempfile
    import pypdfium2
    pdf = pypdfium2.PdfDocument(io.BytesIO(data))
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(min(len(pdf), max_pages)):
            img = Path(tmp) / f"p{i}.png"
            pdf[i].render(scale=2.5).to_pil().save(img)
            res = subprocess.run(["tesseract", str(img), "-", "--psm", "4"], capture_output=True, text=True)
            out.append(res.stdout)
    return "\n".join(out)


def document_text(url):
    data = fetch(url, binary=True)
    if data[:4] == b"%PDF":
        import io
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        if len(re.sub(r"\s", "", text)) < 200 * max(1, min(len(reader.pages), 3)):
            text = ocr_pdf(data)
        return text
    if data[:2] == b"PK":
        import io
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
        return htmllib.unescape(re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n")))
    raise ValueError(f"not a PDF or .docx: {url}")


# ---------------------------------------------------------------- agenda and video index

ITEM_ID = r"(?:C|R|UC|B|PH|PN|E|S|WS)\.?\s?\d{1,2}[a-z]?"


def norm_id(raw):
    m = re.match(r"([A-Z]+)\.?\s?(\d+[a-z]?)", raw.strip().upper())
    return f"{m.group(1)}.{m.group(2)}" if m else raw.strip()


def clean(text):
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def parse_agenda(page):
    """Items from the AgendaViewer page: id, title, section, documents."""
    items, section = [], ""
    cells = list(re.finditer(r'<td class\s*=\s*"numberspace">(.*?)</td>\s*<td>(.*?)</td>', page, re.S))
    for i, m in enumerate(cells):
        num, text = clean(m.group(1)), clean(m.group(2))
        if re.fullmatch(r"[IVX]+\.", num):
            section = text
            continue
        if not re.fullmatch(ITEM_ID, num, re.I):
            continue
        end = cells[i + 1].start() if i + 1 < len(cells) else len(page)
        docs = [{"name": clean(d.group(2)), "url": htmllib.unescape(d.group(1))}
                for d in re.finditer(r'<a href="(https://multnomah\.granicus\.com/MetaViewer\.php[^"]+)"[^>]*>(.*?)</a>', page[m.end():end], re.S)]
        items.append({"id": norm_id(num), "title": text, "section": section, "docs": docs})
    return items


def parse_index(page):
    """Seconds into the video when each agenda item began, keyed by item id."""
    out = {}
    for m in re.finditer(r'<div[^>]*class="index-point[^"]*"[^>]*time="(\d+)"[^>]*>(.*?)</div>', page, re.S):
        label = clean(m.group(2))
        idm = re.match(ITEM_ID, label, re.I)
        key = norm_id(idm.group(0)) if idm else label[:40]
        out.setdefault(key, int(m.group(1)))
    return out


# ---------------------------------------------------------------- attendance

TIME = r"(\d{1,2})\s?:\s?(\d\s?\d)\s*(a\.?\s?m\.?|p\.?\s?m\.?|am|pm)?"


def clock(date, h, m, ampm):
    h, m = int(h), int(re.sub(r"\s", "", m))
    ampm = (ampm or "").lower().replace(".", "").replace(" ", "")
    if ampm == "pm" and h < 12:
        h += 12
    if not ampm and h < 7:  # "1:39" with no am/pm during a daytime meeting
        h += 12
    return datetime.fromisoformat(date).replace(hour=h, minute=m)


def opening(text):
    """The opening paragraph of the minutes, up to the first agenda section."""
    flat = re.sub(r"\s+", " ", text[:6000])
    start = re.search(r"call\s?e\s?d\s+the\s+meeting|calls\s+the\s+meeting|convene|opened\s+the\s+meeting|meeting\s+to\s+order", flat, re.I)
    s = start.start() if start else 0
    s = max(0, flat.rfind(".", 0, s) + 1) if start else 0
    stop = re.search(r"CONSENT\s+(?:AGENDA|CALENDAR)|REGULAR\s+AGENDA|\[CAPTIONS|Chair [A-Z][a-z]+(?: [A-Z][a-z]+)?:|Also attending", flat[s:])
    return flat[s:s + (stop.start() if stop else 900)]


# A capitalized word in an attendance list that isn't a status word ("present", "excused", ...).
NAME_WORD = r"(?!(?:present|excused|was|were|are|is|in|person|and|with|attending|virtually)\b)[A-Z][\w-]*"


def parse_attendance(text, date):
    pool = in_office(date)
    para = opening(text)
    start = re.search(r"(?:order|convene[sd]?(?: the meeting)?)\s+at\s+" + TIME, para, re.I)
    start_time = clock(date, *start.groups()[-3:]) if start else None
    present, excused, changes = set(), set(), []
    positions = sorted((m.start(), n) for n in pool for m in NAME_RES[n].finditer(para))
    mention_excused = [False] * len(positions)
    for i, (pos, n) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(para)
        tail = para[pos:nxt]
        tail_end = re.split(r"(?<=[a-z0-9])\.\s+(?=[A-Za-z])", tail)[0] if not re.search(TIME, tail[:60]) else tail
        if re.search(r"\bexcused\b(?!\s+at)", tail_end, re.I) and not re.search(r"excused\s+at", tail, re.I):
            excused.add(n)
            mention_excused[i] = True
            continue
        present.add(n)
        for kind, pat in (("arrive", r"(?:arrived|arrives|joined|was present|present in person|rejoined)[^.]{0,40}?\bat\s+" + TIME),
                          ("leave", r"(?:excused|left|departed)\s+(?:the meeting\s+)?at\s+" + TIME),
                          ("arrive", r"(?:returned|rejoined)[^.]{0,40}?\bat\s+" + TIME)):
            for m in re.finditer(pat, tail, re.I):
                changes.append({"name": n, "kind": kind, "time": clock(date, *m.groups()[-3:]).strftime("%H:%M")})
    # "Vice-Chair Meieran and Commissioner Stegmann are excused": a name joined to the next by "and" or a comma
    # shares its status.
    for i in range(len(positions) - 2, -1, -1):
        (pos, n), (nxt, n2) = positions[i], positions[i + 1]
        if mention_excused[i + 1] and not mention_excused[i] and re.fullmatch(r"(?:" + NAME_WORD + r"\s+){0,2}?" + NAME_WORD + r"\s*(?:,|,?\s*and)\s*(?:(?:Vice[\s-]*Chair|Commissio\s?ners?|Comm\.)\s*)?(?:" + NAME_WORD + r"\s+)?",
                                                          para[pos:nxt], re.I):
            mention_excused[i] = True
            present.discard(n)
            excused.add(n)
            changes = [c for c in changes if c["name"] != n]
    # Named both ways ("... Smith present." then "Smith is excused today"): excused stands unless a later mention
    # says they were there after all.
    for n in present & excused:
        last_excused = max(i for i, (_, m) in enumerate(positions) if m == n and mention_excused[i])
        later = [i for i, (_, m) in enumerate(positions) if m == n and i > last_excused]
        back = any(re.search(r"\b(?:present|arrived|joined|returned|rejoined)\b", para[positions[i][0]:(positions[i + 1][0] if i + 1 < len(positions) else len(para))], re.I)
                   for i in later)
        (excused if back else present).discard(n)
    unknown = [n for n in pool if n not in present and n not in excused]
    return {"start": start_time.strftime("%H:%M") if start_time else None, "present": sorted(present),
            "excused": sorted(excused), "changes": changes, "unmentioned": unknown, "text": para}


def present_at(att, when, date, margin=600):
    """(members present, members whose status changed within `margin` seconds of `when` -> needs review)."""
    here = set(att["present"])
    close = set()
    arrivals = {c["name"] for c in att["changes"] if c["kind"] == "arrive"}
    here -= {n for n in arrivals if not any(c["kind"] == "leave" and c["name"] == n for c in att["changes"])}
    if when is None:
        return here | arrivals, set(c["name"] for c in att["changes"])
    for c in sorted(att["changes"], key=lambda c: c["time"]):
        t = datetime.fromisoformat(date).replace(hour=int(c["time"][:2]), minute=int(c["time"][3:]))
        if abs((t - when).total_seconds()) <= margin:
            close.add(c["name"])
        if t <= when:
            (here.add if c["kind"] == "arrive" else here.discard)(c["name"])
    return here, close


# ---------------------------------------------------------------- votes

VOTE_WORD = {"AYE": "Yea", "AYES": "Yea", "AYAE": "Yea", "EYE": "Yea", "YES": "Yea", "YEA": "Yea", "I": "Yea", "HI": "Yea",
             "NO": "Nay", "NAY": "Nay", "NOPE": "Nay",
             "ABSTAIN": "Abstain", "I ABSTAIN": "Abstain", "ABSTAINING": "Abstain", "RECUSE": "Abstain", "PRESENT": "Abstain"}
OUTCOME = re.compile(
    r"\b(?:IS|ARE|HAS BEEN|HAVE BEEN|WAS|WERE)\s+(?:HEREBY\s+|NOW\s+|UNANIMOUSLY\s+)?"
    r"(APPROVED|ADOPTED|POSTPONED|PASSED|DENIED|REJECTED|RATIFIED|AUTHORIZED|ACCEPTED|CONTINUED|TABLED|FAILED|DEFEATED|"
    r"CARRIED|WITHDRAWN|REFERRED|CONFIRMED|APPOINTED|ACKNOWLEDGED|CERTIFIED|ELECTED|SELECTED|RESCINDED|AFFIRMED|UPHELD|REVERSED)\b"
    r"|\b(?:MOTION|AMENDMENTS?|BUDGET NOTES?|RESOLUTION|ORDINANCE|ITEM|RECONSIDERATION)"
    r"(?:\s+#?\s?[0-9][\w]*(?:\s*(?:-|through|and|&)\s*[0-9][\w]*)?)?(?:\s+(?:AS AMENDED|TO [A-Z ]{1,40}?))?"
    r"\s+(PASS|PASSES|CARRIES|FAILS|PASSED|FAILED|FAIL)\b(?:\s+AS AMENDED)?|\bIT (PASSES|FAILS)\b"
    r"|\b(?:DOES|DID) NOT (PASS|CARRY)\b"
    r"|\bTHAT (PASSES|FAILS)\b|\bPASSES UNANIMOUSLY\b|\bIT(?:'S| IS)\s+(APPROVED|ADOPTED)\b"
    r"|\b(?:RESOLUTION|ORDINANCE|BUDGET MODIFICATION|AGREEMENT)\s+(ADOPTED|APPROVED)\b",
    re.I)
TRIGGER = re.compile(r"IN FAVOR|ROLL\s?CALL|\[\s*UNANIM|\[\s*CHORUS|\[\s*AYES|\bAYES\s*(?:\(\s*\d+\s*\))?\s*:", re.I)
SPEAKER_VOTE = re.compile(
    r"(?:(?:Commissioner|Comm\.?|Chair|Vice[\s\-]*Chair|Vice)\s+)?([A-Z][A-Za-z\-\s]{1,30}?)\s*[:;]\s*(?:[:;]\s*)?"
    r"(?:(?:AND|SO|WELL|YES),?\s+)?(?:(?:I\s+VOTE|I'LL\s+VOTE|I\s+WILL\s+VOTE|MY\s+VOTE\s+IS)\s+)?"
    r"(AYE|AYES|AYAE|EYE|YES|YEA|NO|NAY|I ABSTAIN|ABSTAIN(?:ING)?|RECUSE|PRESENT)\b", re.I)


LIST_LABEL = r"(?:Ayes?|Nays?|Nos|Noes|No|Excused|Absent|Abstain(?:s|ed|ing)?|Recused?)"


def summary_votes(block, pool):
    """Named lists: 'Ayes (4): ...', 'Nays (1): ...', 'Excused (1): ...'. Returns (votes, problems)."""
    votes, problems, seen = {}, [], {}
    head = r"\s*(?:\(\s*(\d+)\s*\)\s*[:;]?|[:;])"
    for label, count, names in re.findall(r"\b(" + LIST_LABEL + r")" + head + r"\s*(.*?)(?=\b" + LIST_LABEL + r"\s*(?:\(\s*\d+\s*\)|[:;])|$)", block, re.I | re.S):
        key = label.lower()
        v = ("Yea" if key.startswith("aye") else "Nay" if key in ("nay", "nays", "nos", "noes", "no")
             else "Absent" if key in ("excused", "absent") else "Abstain")
        # The list ends at the first sentence that isn't a name ("The resolution is adopted.").
        names_part = re.split(r"\.\s+(?=The |R\.|C\.|Consent|Motion|Amendment|[A-Z][a-z]+ (?:was|is|were|are)\b)"
                              r"|(?=\b(?:Commissioner|Chair|Vice[\s-]*Chair)\s[A-Za-z\-]+(?:\s[A-Z][a-z]+)?\s(?:moves|motions|seconds|passes|makes|proposes)\b)", names)[0]
        found = names_in(names_part, pool)
        if count and int(count) != len(found):
            problems.append(f"minutes say {label} ({count}) but name {len(found)}: {', '.join(found)}")
        for n in found:
            if n in seen and seen[n] != v:
                problems.append(f"minutes list {n} as both {seen[n]} and {v}")
            seen[n] = v
            votes[n] = v
    return votes, problems


DOTTED_VOTE = re.compile(r"(?:(?:COMMISSIONER|COMM\.|CHAIR|VICE[\s\-]*CHAIR)\s+)?([A-Z][A-Z\-\s]{2,30}?)\.\s+(AYE|NO|NAY|YES|ABSTAIN)\b[.,]?")


def transcript_votes(window, pool):
    """Votes stated in a transcript window. Returns (votes, notes, opposed_speakers)."""
    votes, notes = {}, []
    # Some 2023 captions read the roll as "MEIERAN. AYE. JAYAPAL. NO."
    for m in DOTTED_VOTE.finditer(window):
        who = names_in(m.group(1), pool)
        if who:
            votes[who[0]] = VOTE_WORD[m.group(2).upper()]
    opp = re.search(r"OPPOSED|ALL THOSE AGAINST|ANY NAYS|ANY NOS", window, re.I)
    for m in SPEAKER_VOTE.finditer(window):
        who = names_in(m.group(1), pool)
        if not who:
            continue
        v = VOTE_WORD.get(re.sub(r"\s+", " ", m.group(2).upper()), None)
        if opp and m.start() > opp.start():
            notes.append(f"{who[0]} answered '{m.group(2)}' after the call for opposition")
            v = "Nay" if v == "Yea" else v
        if v:
            votes[who[0]] = v
    for b in re.findall(r"\[([^\]]{0,160})\]", window):
        if re.search(r"NAY|\bNO\b|ABSTAIN|RECUS|OPPOS|EXCUSED|NOT PRESENT|WASN.?T|DID NOT", b, re.I):
            notes.append(f"bracket: [{b.strip()}]")
    return votes, notes


def find_votes(segment, pool, fmt):
    """Split an item's text into vote events."""
    events, pos = [], 0
    flat = re.sub(r"\s+", " ", segment)
    if fmt == "summary":
        # Each "Ayes (n): ..." list is one roll call, whether or not a result sentence follows it.
        starts = [m.start() for m in re.finditer(r"\bAyes?\s*(?:\(\s*\d+\s*\)\s*[:;]?|[:;])", flat, re.I)]
        last = 0
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else len(flat)
            chunk = flat[s:e]
            o = OUTCOME.search(chunk)
            # The motion text sits between the previous roll call's list and this one.
            prev = flat[last:s]
            prev = prev[re.search(r"^.*?(?:[.;]\s|$)", prev).end():] if last else prev
            # Keep the rest of the result sentence ("... is approved as amended.").
            stop = chunk.find(".", o.end()) if o else -1
            cut = (stop + 1 if 0 <= stop - o.end() < 80 else o.end()) if o else 600
            events.append({"window": chunk[:cut],
                           "before": prev[-700:], "outcome": o.group(0).upper() if o else "VOTE RECORDED"})
            last = s + (o.end() if o else min(len(chunk), 400))
        return events
    while True:
        t = TRIGGER.search(flat, pos)
        if not t:
            break
        o = OUTCOME.search(flat, t.end())
        if not o or o.start() - t.start() > 2500:
            # "[UNANIMOUS AYES]" with no result sentence before the next item: still a (unanimous) vote.
            u = re.compile(r"\[\s*(?:UNANIM|CHORUS OF AYES)[^\]]*\]").search(flat, t.start(), t.end() + 200)
            if u and not re.search(r"ROLL\s?CALL|IN FAVOR", flat[u.end():u.end() + 400], re.I):
                events.append({"window": flat[t.start():u.end()], "before": flat[max(0, t.start() - 700):t.start()],
                               "outcome": "UNANIMOUS AYES (NO RESULT SENTENCE)"})
                pos = u.end()
                continue
            pos = t.end()
            continue
        # Pull in trailing roll-call lines that come after the outcome sentence start (e.g. "Chair: AYE. THE ... IS ADOPTED").
        end = o.end()
        window = flat[t.start():end]
        before = flat[max(0, t.start() - 700):t.start()]
        events.append({"window": window, "before": before, "outcome": o.group(0).upper()})
        pos = end
    return events


def classify(ev, here, close, pool, fmt, unknown=()):
    w = ev["window"]
    if fmt == "summary":
        votes, notes = summary_votes(w, pool)
        close = set()  # named lists say who voted; arrival and departure times don't matter
    else:
        votes, notes = transcript_votes(w, pool)
    unanimous = bool(re.search(r"UNANIM|CHORUS OF AYES|\[\s*AYES\s*\]", w, re.I))
    failed = bool(re.search(r"FAIL|DEFEAT|DENIED|REJECTED|NOT PASS|NOT CARRY", ev["outcome"]))
    flags = list(notes)
    if fmt != "summary" and re.search(r"[:;?]\s*(?:NO|NAY|NOPE)\b(?!\s+(?:QUESTIONS?|COMMENTS?|MORE|FURTHER|ONE|PUBLIC|TESTIMONY))|\bNAYS?\b|VOTES? NO\b|VOTING NO\b|\bOPPOSED\b[^?]|\bNO[,.]\s*(?:COMMISSIONER|CHAIR|VICE)", w, re.I):
        flags.append("the vote passage contains a no vote or opposition")
    ghosts = sorted(n for n in votes if n not in here and n not in unknown)
    if ghosts and fmt != "summary":
        # Captions sometimes keep the regular Chair's name on whoever is presiding.
        flags.append("named as voting but not present by the minutes' attendance: " + ", ".join(ghosts))
    named_all = bool(votes) and all(n in votes for n in here)
    if named_all and any(v == "Nay" for v in votes.values()):
        # A roll call that names everyone present already records the no votes.
        flags = [f for f in flags if "no vote or opposition" not in f]
    if close and not named_all:
        flags.append("attendance changed within 10 minutes of this item: " + ", ".join(sorted(close)))
    missing = [n for n in unknown if n not in votes]
    if missing and fmt != "summary":
        flags.append("the minutes' attendance doesn't mention " + ", ".join(missing))
    if fmt == "summary" and votes:
        missing = sorted(n for n in here if n not in votes)
        if missing:
            flags.append("present but not named in this roll call: " + ", ".join(missing))
    if votes and (len(votes) >= len(here) or fmt == "summary"):
        basis = "named"
        for n in here:
            votes.setdefault(n, "Absent" if fmt != "summary" else "")
    elif votes and unanimous and all(v == "Yea" for v in votes.values()) and not any("no vote" in f for f in flags):
        # "[UNANIMOUS AYES] Chair Vega Pederson: AYE." -- the Chair's own aye repeated after a unanimous roll call.
        basis = "unanimous"
        votes = {n: "Yea" for n in here}
    elif (len(votes) == 1 and list(votes.values()) == ["Yea"] and not any("no vote" in f for f in flags)
          and re.search(r"\[\s*ROLL\s?CALL(?:\s+VOTE)?\s*\]\s*(?:Chair|Vice[\s-]*Chair|Commissioner|Comm\.)?\s*[A-Za-z\-]+(?:\s[A-Za-z\-]+)?\s*:\s*(?:AYE|YES|YEA)\b", w, re.I)):
        # "[ROLL CALL VOTE] Chair Kafoury: AYE. THE RESOLUTION IS ADOPTED." -- the presiding officer's own aye
        # after a roll call the captions don't itemize.
        basis = "unanimous"
        votes = {n: "Yea" for n in here}
        flags.append("roll call not itemized in minutes; no dissent recorded")
    elif votes:
        # A voice vote where only the dissenters are named: everyone else present said aye.
        basis = "review"
        flags.append("only " + ", ".join(f"{n} ({v})" for n, v in sorted(votes.items())) + " named; others present filled in as Yea")
        for n in here:
            votes.setdefault(n, "Yea")
    elif failed:
        basis = "review"
        flags.append("outcome failed without named votes")
    else:
        basis = "unanimous"
        votes = {n: "Yea" for n in here}
        if not unanimous and not re.search(r"IN FAVOR", w, re.I):
            flags.append("roll call not itemized in minutes; no dissent recorded")
        if re.search(r"OPPOSED\?\s*(?:\[[^\]]*\]\s*)?(?:Commissioner|Chair|Vice)", w, re.I):
            flags.append("someone spoke after the call for opposition")
    for n in pool:
        votes.setdefault(n, "Absent")
    if flags and any(not f.startswith("roll call not itemized") for f in flags):
        basis = "review"
    ev.update({"votes": votes, "basis": basis, "flags": flags})
    return ev


def segments(text, items):
    """Slice the minutes into one chunk per agenda item, following the agenda's order."""
    flat = text
    heads = []
    for it in items:
        pat = re.compile(r"(?m)^\s*" + it["id"].replace(".", r"\.?\s?") + r"(?![0-9])")
        start = heads[-1][1] + 1 if heads else 0
        m = pat.search(flat, start) or pat.search(flat)
        if not m:
            # Some transcripts have the clerk read the item: "BOARD CLERK: R.8, RESOLUTION ..."
            inline = re.compile(r"BOARD CLERK:\s*R?" + it["id"].replace(".", r"\.?\s?") + r"(?![0-9])", re.I)
            m = inline.search(flat, start) or inline.search(flat)
        if m:
            heads.append((it["id"], m.start()))
    heads.sort(key=lambda h: h[1])
    out = {}
    for i, (iid, s) in enumerate(heads):
        e = heads[i + 1][1] if i + 1 < len(heads) else len(flat)
        out[iid] = flat[s:e]
    return out


def analyze(clip, date, minutes_query=None, cache=None):
    def page(url):
        # Some joint meetings' agendas are PDFs behind an external document viewer; treat them as having no
        # itemized agenda (their votes are entered by hand).
        try:
            return fetch(url)
        except subprocess.CalledProcessError:
            return "<!-- could not fetch " + url + " -->" + " " * 200
    agenda_html = cached(cache, f"ag/{clip}.html", lambda: page(f"{BASE}/AgendaViewer.php?view_id=3&clip_id={clip}"))
    index_html = cached(cache, f"mp/{clip}.html", lambda: page(f"{BASE}/MediaPlayer.php?view_id=3&clip_id={clip}"))
    items = parse_agenda(agenda_html)
    index = parse_index(index_html)
    doc_url = None

    def get_minutes():
        nonlocal doc_url
        doc_url = minutes_document_url(minutes_query)
        if not doc_url:
            raise ValueError("no minutes document")
        return document_text(doc_url)

    # A meeting with no minutes posted (some joint appointment hearings) has only its agenda.
    text = cached(cache, f"mins/{clip}.txt", get_minutes) if minutes_query else ""
    summary_part = text.split("CAPTIONS")[0] if re.search(r"\bAyes\s*\(\s*\d", text[:20000], re.I) else None
    fmt = "summary" if summary_part else "transcript"
    body = summary_part if summary_part else text
    pool = in_office(date)
    att = parse_attendance(text, date)
    start = datetime.fromisoformat(f"{date}T{att['start']}") if att["start"] else None
    first_offset = min(index.values()) if index else 0
    # Some agendas number items differently from the minutes (a special meeting's "PN.1" is "R.1" in the
    # minutes). Add any item the minutes head that the agenda doesn't list, titled from the minutes.
    known = {it["id"] for it in items}
    for hm in re.finditer(r"(?m)^\s*((?:C|R|UC|PH|PN|B)\.?\s?\d{1,2})\s+(\S.*(?:\n(?!\s*\n).*){0,4})", body):
        iid = norm_id(hm.group(1))
        if iid not in known and fmt == "summary":
            title = re.split(r"\n\s*\n|(?:Commissioner|Vice|Chair)\s[\w\s-]+moves", hm.group(2))[0]
            items.append({"id": iid, "title": re.sub(r"\s+", " ", title).strip(), "section": "from minutes", "docs": []})
            known.add(iid)
    segs = segments(body, items)
    out_items = []
    # Without a video index, estimate when each item's vote happened from where the item ends in the
    # transcript, interpolating between the call to order and adjournment (wider margin for the estimate).
    end_m = re.search(r"adjourn(?:ed|s)?[^.\n]{0,40}?\bat\s+" + TIME + r"|ADJOURNMENT\s*[\-–—:]\s*" + TIME, text, re.I)
    end_time = None
    if end_m:
        g = end_m.groups()
        try:
            end_time = clock(date, *(g[:3] if g[0] else g[3:]))
        except ValueError:  # a typo like "6:75 p.m."
            end_time = None
    starts = sorted(set(index.values()))
    for it in items:
        seg = segs.get(it["id"], "")
        seg_pos = text.find(seg) if seg else -1
        flat = re.sub(r"\s+", " ", seg)

        def when_at(frac):
            """Estimated clock time at a point `frac` (0-1) of the way through this item, and the review margin."""
            if start and it["id"] in index:
                t0 = index[it["id"]]
                later = [x for x in starts if x > t0]
                t1 = later[0] if later else t0 + 900
                return start + timedelta(seconds=t0 + frac * (t1 - t0) - first_offset), 600
            if start and end_time and end_time > start and seg_pos >= 0 and fmt == "transcript":
                pos = seg_pos + frac * len(seg)
                return start + (end_time - start) * (pos / max(1, len(text))), 1200
            return None, 600

        item_when, _ = when_at(0)
        here0, _ = present_at(att, item_when, date)
        evs = []
        for ev in find_votes(seg, pool, fmt):
            frac = max(0, flat.find(ev["window"][:80])) / max(1, len(flat))
            when, margin = when_at(frac)
            here, close = present_at(att, when, date, margin)
            ev["clock"] = when.strftime("%H:%M") if when else None
            evs.append(classify(ev, here, close, pool, fmt, att["unmentioned"]))
        out_items.append({**it, "clock": item_when.strftime("%H:%M") if item_when else None, "found": bool(seg),
                          "present": sorted(here0), "votes": evs})
    return {"clip": clip, "date": date, "format": fmt, "pool": pool, "attendance": att,
            "agenda_url": f"{BASE}/AgendaViewer.php?view_id=3&clip_id={clip}",
            "minutes_url": f"{BASE}/MinutesViewer.php?{minutes_query}" if minutes_query else None,
            "items": out_items}


def show(m):
    a = m["attendance"]
    print(f"== {m['date']} clip {m['clip']} ({m['format']})  start {a['start']}  present {a['present']}  excused {a['excused']}"
          + (f"  changes {a['changes']}" if a["changes"] else "") + (f"  UNMENTIONED {a['unmentioned']}" if a["unmentioned"] else ""))
    for it in m["items"]:
        print(f"  {it['id']:5} {it['clock'] or '     '} {'' if it['found'] else '[not in minutes] '}{it['title'][:150]}")
        for ev in it["votes"]:
            tally = {}
            for n, v in ev["votes"].items():
                if n in m["pool"]:
                    tally.setdefault(v, []).append(n)
            short = " ".join(f"{k}:{','.join(v)}" for k, v in sorted(tally.items()) if k in ("Nay", "Abstain", "Absent"))
            print(f"        -> {ev['outcome']:<22} {ev['basis']:<9} {short}" + (f"  FLAGS {ev['flags']}" if ev["flags"] else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--date", required=True)
    ap.add_argument("--minutes", help="MinutesViewer query string (view_id=3&clip_id=..&doc_id=..)")
    ap.add_argument("--cache")
    ap.add_argument("--json")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    m = analyze(args.clip, args.date, args.minutes, args.cache)
    if args.json:
        Path(args.json).write_text(json.dumps(m, indent=1), encoding="utf-8")
    if not args.quiet:
        show(m)


if __name__ == "__main__":
    sys.exit(main())
