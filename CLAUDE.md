# Multnomah County Commission Votes — project notes

Read this before touching the data. It is the source of truth for how the site is built and how votes are logged; it lives in the repo so it survives between sessions. The site is a sibling of `Portland-City-Council-Votes/pdxcouncilvotes` and keeps the same design and specs.

## Goal

A public, searchable site of Multnomah County Board of Commissioners votes where visitors can:

1. Browse a spreadsheet-style view: date, item, a short plain-language synopsis, and how each commissioner voted.
2. Filter by **theme**, **year**, **commissioner** and how they voted, or show only split votes.
3. Explore by commissioner (photos, with an address box that finds your district) or by theme.

**Who (Sept 2026):** the five current commissioners — Chair Jessica Vega Pederson, Meghan Moyer (D1), Shannon Singleton (D2), Julia Brim-Edwards (D3), Vince Jones-Dixon (D4) — plus former D1 Commissioner Sharon Meieran, going back as far as each has served. Vega Pederson was the D3 commissioner 2017–2022 before becoming Chair and Meieran served 2017–2024, so the scope is **every Board meeting from January 2017 to the present**. Everyone else who sat on the Board in that time (Kafoury, Smith, Jayapal, Beason, Rosenbaum, Stegmann) has a column too, so tallies are complete, but only the six above get photos on the home page.

**Not in office:** a seat a commissioner didn't hold on the date of a vote is recorded as `Not in office` (never `Absent`). `add_votes.py` fills it from the terms in `assets/commissioners.json`; the validator rejects a vote recorded outside someone's term. The table hides columns that are entirely `Not in office` for the rows shown.

A static site served by GitHub Pages. No build step, no backend. **Note:** this repo is private; GitHub Pages for a private repo needs a paid plan, and the public "Report an error" links need the repo (or at least its Issues) to be public. The owner should decide.

## Layout

| Path | What it is |
|---|---|
| `index.html`, `assets/home.js` | Home: seat cards (Chair, Districts 1–4) with photos, "find your district" address box, themes. Seats on the Nov. 3, 2026 ballot (Chair, D2) are ringed in red; candidates for Chair get a tag. |
| `data.html`, `assets/data.js` | Full table of every vote with filters in the URL hash (`#commissioner=Meieran&year=2019&contested=1`). |
| `budget.html`, `assets/budget.js`, `data/budget.json` | Budget page (see Budget below). |
| `assets/common.js`, `assets/style.css` | Shared loading (`window.MCV`), theme icons, styles. |
| `assets/commissioners.json`, `assets/commissioners/` | Names, seat terms (`terms[]` with start/end dates — these drive `Not in office`), official County portraits, `next_election`, `candidate`. |
| `assets/districts.json` | Commissioner district boundaries (Multnomah County GIS, 2020 redistricting: `services5.arcgis.com/x7DNZL1YqNQVNykA/.../Commissioner_Districts_2020/FeatureServer/0`, the layer behind the County's district look-up app). |
| `data/meetings.csv` | Every Board meeting in the Granicus archive since Jan 2017 that could carry a vote: `date,clip,meeting,minutes_doc,status,items_logged,notes`. `clip` is the Granicus clip id. |
| `data/votes.csv` | One row per major item with a final vote. |
| `data/motions.csv` | Other roll calls under logged items (amendments, budget notes, procedural motions, earlier readings). |
| `data/picks/<year>.json` | **The editorial record**: for each meeting (by clip), which items were logged, their synopsis/theme, and any vote corrections made after reading the minutes. The CSVs are generated from these. |
| `data/board_documents.json` | The County's list of adopted ordinances/resolutions/orders (2020 on) from multco.us/services/board-documents; used to fill `doc_number` and `document`. Refresh with `scripts/fetch_board_documents.py`. |
| `data/news.csv` | News coverage: `date,item,outlet,headline,url,image`. |
| `scripts/parse_minutes.py` | Reads one meeting from Granicus into items and votes (see below). |
| `scripts/add_votes.py` | Applies a picks file: appends rows to votes/motions, marks meetings done. |
| `scripts/rebuild_data.py` | Regenerates votes/motions from all picks files. |
| `scripts/validate_data.py` | Schema and consistency checks; CI runs it. Run before every commit that touches `data/`. |

**Cache busting:** bump the `?v=` tag in all three HTML files whenever CSS/JS changes.

Preview locally with `python3 -m http.server`.

## Where the data comes from

Everything is on **multnomah.granicus.com** (the Board Clerk's archive; `ViewPublisher.php?view_id=3` lists every meeting since 2010):

- `AgendaViewer.php?view_id=3&clip_id=N` — item numbers (C.1, R.3, UC.1, PN.1…) and titles, plus links to each item's documents (APRs, ordinances, exhibits).
- `MediaPlayer.php?view_id=3&clip_id=N` — the video index: seconds into the recording when each item started (used to tell who was in the room for a voice vote; missing for recent meetings).
- `MinutesViewer.php?view_id=3&clip_id=N&doc_id=…` — redirects (via a Google viewer we can't reach) to `DocumentViewer.php?file=…pdf`; the parser follows it directly. A few are `.docx`; a few are scans with no text layer (OCR'd with tesseract — `apt-get install tesseract-ocr`, `pip install pypdf pypdfium2`).
- Mar 8, 2018 (clip 1687): Granicus's minutes link serves the agenda; minutes not found yet.

**Network:** the environment must allow `multnomah.granicus.com`, `www.multco.us` (Board documents, photos), `services5.arcgis.com`, and news sites for thumbnails.

### How the minutes record votes (read this before trusting any vote)

- **Late 2024 on ("summary")**: an action summary before the captions, with named lists — `Ayes (4): …`, `Nays/Nos (1): …`, `Excused (1): …`. These are authoritative. They contain typos: counts that don't match the names, a name in both lists, truncated names ("Commissioner Sing"), names run together. The parser flags every one; resolve them by reading the list and record a `motion_notes`/synopsis note saying what the minutes say.
- **2017–2024 ("transcript")**: near-verbatim captions. Votes appear as:
  - named roll calls — `Commissioner Meieran: AYE.`, or without titles `Meieran: NO Beason: YES`;
  - `[UNANIMOUS AYES]`, `[CHORUS OF AYES]`, `[ROLL CALL VOTE]` — unanimous among those present;
  - voice votes — `ALL THOSE IN FAVOR VOTE AYE. THE RESOLUTION IS ADOPTED.` Dissent shows up after `OPPOSED?`: **`OPPOSED? Commissioner Smith: AYE.` means Smith voted no.**
  - bracketed notes: `[AYES; COMMISSIONER MEIERAN ABSTAINED]`, `[Commissioner Smith was excused for the vote.]`.
  - a bare `[ROLL CALL]` with no names and no dissent is recorded as unanimous among those present; the parser tags it "roll call not itemized".
- **Attendance**: the opening paragraph lists who was present/excused and arrival/departure times. For a voice or unanimous vote, "present" = at the start, adjusted by arrivals/departures before the item's start time (meeting start + video-index offset). Anyone who arrived or left within 10 minutes of the item is flagged for review rather than guessed.

- **Attendance lists**: "Vice-Chair Meieran and Commissioner Stegmann are excused" marks both excused (a name joined to the next by "and" or a comma shares its status). Always check the opening paragraph yourself when a commissioner is shown present but never speaks or votes; the parser's attendance is a starting point, not the record.

The parser marks each vote `named`, `unanimous` or `review`. `add_votes.py` refuses a `review` vote unless the pick says `"reviewed": true` (with corrections in `"votes"`) or, for motions, lists it in `"reviewed_motions"`. **Never mark something reviewed without reading the passage in the minutes.**

## What counts as "major"

**Include:** ordinances (log at final adoption: second reading, or first reading if by emergency); policy resolutions and plans; budget approval (May) and adoption (June), tax levies, fee schedules, non-represented salary adjustments; supplemental budgets and budget modifications of about $10 million or more or that create/cut programs notably; collective bargaining agreement ratifications; consents to department-director appointments; legislative agendas; legislative-vacancy appointments (joint meetings); IGAs, contracts, franchises and property sales/purchases that are large or policy-significant; settlements of $1 million or more; items postponed indefinitely by a vote (that's a decision); and **any vote that isn't unanimous**, whatever it is.

**Skip:** proclamations, notices of intent to apply for grants (unless very large), advisory-board appointments, liquor license recommendations, small budget modifications and reclassifications, routine property/right-of-way acquisitions, tax-foreclosed property sales, service-district (Dunthorpe-Riverdale, Mid-County Lighting) budgets, briefings (no vote), and settlements under $1 million — unless the vote was split.

First readings and earlier readings: don't log a final vote; if they had amendment roll calls, log them with `"motions_only": true` so they appear in motions.csv. The County's library district budget/levy votes (Board acting as the district) are logged under FY Budget; Libraries.

## Schema

`data/votes.csv`: `date,item,doc_number,document,title,synopsis,type,action,theme,area,minutes,url,` + one column per commissioner in `assets/commissioners.json` order.

- **item**: agenda number (`R.3`). **doc_number/document**: the adopted resolution/ordinance number and its PDF on multco.us, matched automatically from `data/board_documents.json` (set by hand in the pick when the agenda wording differs).
- **title**: the agenda title without the presenter list.
- **synopsis**: one or two neutral sentences saying only what the agenda, minutes or adopted document support. No outside knowledge, no inferred motives. Name dissenters when the vote was split.
- **type**: Ordinance, Emergency ordinance, Resolution, Order, Budget modification, Supplemental budget, Intergovernmental agreement, Contract, Settlement, Appointment, Motion, Other.
- **action**: Adopted, Approved, Adopted/Approved as amended, Failed, Postponed, Postponed indefinitely, Appointed, …
- **theme**: from `THEMES` in `scripts/add_votes.py`, `; `-separated. Add a theme only when nothing fits.
- **area**: `Countywide` unless the title names a place (Gresham, Troutdale, a Portland address…).
- **record**: how the minutes record the vote — `named` (every vote named), `unanimous` (minutes say unanimous), `voice vote` (no dissent recorded), `not itemized` (a roll call is noted without names; no dissent recorded), `inferred` (some votes named; others present shown as Yea), `partial` (some votes unrecorded — those cells are blank), `by hand` (entered from the transcript; the synopsis says what the minutes show). The site explains every value except named/unanimous. **Unitemized roll calls can hide splits** (Aug 31, 2023 has a failed motion recorded only as "( ROLL CALL )"), which is why they're labelled.
- **url**: the Granicus agenda page; **minutes**: the Granicus minutes link.
- **commissioner columns**: `Yea`, `Nay`, `Absent` (includes excused), `Abstain` (includes recused), or `Not in office`. In motions.csv a blank is allowed only with a `note` explaining what the minutes say.

`data/motions.csv`: `date,item,seq,item_title,kind,motion,note,theme,area,url,` + commissioners. `motion` quotes the minutes (movers/seconders, amendment number, result sentence).

## How to log a batch of meetings

1. Print digests (see `digest.py` pattern in `scripts/parse_minutes.py`'s `show()`): `python3 scripts/parse_minutes.py <clip> --date YYYY-MM-DD --minutes 'view_id=3&clip_id=<clip>&doc_id=<minutes_doc>' --cache .cache`.
2. Read the summary/transcript passage for every item you'll log (and every flagged vote). Decide what's major.
3. Add the meeting to `data/picks/<year>.json` (an empty `{}` marks a meeting with nothing major as done).
   - When the parser can't follow a transcript (items taken out of order, votes run together), enter the item by hand: `"manual": true` with `"outcome"` and every `"votes"`, plus `"manual_motions"` (a list of `{"motion", "outcome", "votes"}`) for roll calls taken before the final vote. The record becomes `by hand` unless `"record"` says otherwise.
4. `python3 scripts/add_votes.py data/picks/<year>.json --cache .cache` (or `scripts/rebuild_data.py`), then `python3 scripts/validate_data.py`, commit, push. Small commits.

## Budget

`data/budget.json` holds each adopted budget's headline figures and breakdowns, every figure citing its page in the County's adopted budget documents. Add a year only after checking each number on the cited page.

## Progress

`data/meetings.csv` is the source of truth. As of Sept 24, 2026:

- **Done:** 2026 (Jan 8 – Sept 17), 2025, 2024, 2023, 2022 and 2021, all meetings.
- **Done:** 2020 as well.
- **Done:** 2019 as well (almost all voice votes: "ALL THOSE IN FAVOR, VOTE AYE"; recorded as voice vote).
- **Done:** 2018 as well. Voice votes with dissent read "OPPOSED? Commissioner Smith: AYE" (= Smith voted no). The Jan 29, 2018 Senate District 19 joint appointment was a weighted multi-candidate roll call; Yea there means a vote for the appointee (Rob Wagner).
- **Next:** 2017 (Jan 19 on).
- 2020 minutes: most roll calls are named; "Chair Kafoury: AND I VOTE AYE", "EYE", "Vega Pederson: : AYE" and "Maiaran" are handled. Dec 17, 2020 has several roll calls with members missing (the Chair's connection dropped and Vice-Chair Jayapal presided); those are recorded as partial.
- 2021 minutes sometimes print a full five-name roll call even when a commissioner was excused (Apr 15, 2021: Jayapal appears only in the roll calls), and sometimes list as excused a commissioner who speaks and votes throughout (Oct 21 and Nov 18, 2021: Stegmann). When the parser flags "named as voting but not present", search the minutes for that commissioner's other remarks: if they speak, trust the roll call; if they appear only in roll calls, record them Absent and say so in the synopsis.
- 2022 captions: Vega Pederson's aye is often spelled "AYAE"; "[ROLL CALL VOTE] Chair Kafoury: AYE." is an unitemized roll call (the parser now treats a lone presiding-officer aye after a roll-call marker that way); some captions keep "Chair Kafoury" as the speaker label on days she was excused and Vice-Chair Stegmann presided, so the parser flags votes by anyone the attendance lists as absent.
- Known minutes errors are recorded in notes (e.g., Aug 6, 2026 special meeting; June 12, 2025 budget; Oct 31, 2025 special meeting lists the excused Chair among the Ayes).
