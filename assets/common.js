// Shared data loading for the home page, the full data page and the budget page.
// Exposes window.MCV.

(function () {
  "use strict";

  // RFC 4180 CSV parser: quoted fields, escaped quotes, newlines inside quotes.
  function parseCSV(text) {
    const out = [];
    let row = [];
    let field = "";
    let quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
        else if (c === '"') quoted = false;
        else field += c;
      } else if (c === '"') quoted = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field); out.push(row); row = []; field = "";
      } else field += c;
    }
    if (field !== "" || row.length) { row.push(field); out.push(row); }
    return out.filter((r) => r.some((v) => v.trim() !== ""));
  }

  function csvObjects(text) {
    const [header, ...body] = parseCSV(text);
    return {
      header,
      rows: body.map((cells) => Object.fromEntries(header.map((h, i) => [h, (cells[i] || "").trim()]))),
    };
  }

  // Themes and areas may hold several values separated by semicolons.
  const splitList = (value) => value.split(";").map((s) => s.trim()).filter(Boolean);

  async function fetchText(url) {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
    return res.text();
  }

  async function fetchJSON(url) {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
    return res.json();
  }

  // A seat someone didn't hold on the date of a vote. Not a vote, and never counted as absent.
  const NOT_IN_OFFICE = "Not in office";

  // The seat a commissioner held on a date (YYYY-MM-DD), or null if they weren't on the Board.
  function seatOn(c, date) {
    const t = (c.terms || []).find((t) => t.start <= date && (!t.end || date <= t.end));
    return t ? t.seat : null;
  }

  // "2017–2024" style span of a commissioner's time on the Board.
  function yearsServed(c) {
    const terms = c.terms || [];
    if (!terms.length) return "";
    const first = terms[0].start.slice(0, 4);
    const last = terms[terms.length - 1].end;
    return last ? (last.slice(0, 4) === first ? first : `${first}–${last.slice(0, 4)}`) : `${first}–present`;
  }

  // Loads votes, commissioners, news and motions. Commissioner columns follow
  // commissioners.json; any extra column in the CSV is appended after them.
  async function loadAll() {
    const [votesText, list, newsText, motionsText] = await Promise.all([
      fetchText("data/votes.csv"),
      fetchJSON("assets/commissioners.json"),
      fetchText("data/news.csv").catch(() => ""),
      fetchText("data/motions.csv").catch(() => ""),
    ]);
    const { header, rows } = csvObjects(votesText);
    const csvNames = header.slice(header.indexOf("url") + 1);
    const known = new Map(list.map((c) => [c.name, c]));
    const commissioners = list.filter((c) => csvNames.includes(c.name))
      .concat(csvNames.filter((n) => !known.has(n)).map((n) => ({ name: n, full_name: n, terms: [] })));

    const news = new Map();
    if (newsText) {
      csvObjects(newsText).rows.forEach((n) => {
        const key = `${n.date}|${n.item}`;
        if (!news.has(key)) news.set(key, []);
        news.get(key).push(n);
      });
    }

    function tally(r) {
      r.votes = commissioners.map((c) => ({ name: c.name, vote: r[c.name] }));
      r.tally = { Yea: 0, Nay: 0, Absent: 0, Abstain: 0 };
      r.votes.forEach((v) => { if (v.vote in r.tally) r.tally[v.vote]++; });
      r.split = r.tally.Yea > 0 && r.tally.Nay > 0;
      r.themes = splitList(r.theme);
      r.areas = splitList(r.area || "");
      r.year = r.date.slice(0, 4);
      return r;
    }

    const votes = rows.map((r) => {
      tally(r);
      r.kind = "Final vote";
      r.news = news.get(`${r.date}|${r.item}`) || [];
      r.haystack = [r.title, r.synopsis, r.item, r.doc_number, r.action, ...r.news.map((n) => n.headline)]
        .join(" ").toLowerCase();
      return r;
    });

    // Roll calls on amendments and other motions.
    const motions = motionsText ? csvObjects(motionsText).rows.map((r) => {
      tally(r);
      r.title = r.item_title;
      r.news = [];
      r.haystack = [r.motion, r.item_title, r.item, r.note].join(" ").toLowerCase();
      return r;
    }) : [];

    return { votes, motions, commissioners };
  }

  // Line icons for each theme (24x24, drawn with currentColor).
  const THEME_ICONS = {
    "Housing": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    "Homelessness": '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 4v16"/><path d="m9.5 20 2.5-5 2.5 5"/>',
    "Public Safety": '<path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.1 7.5 9.5 4.4-1.4 7.5-4.9 7.5-9.5V6L12 3Z"/><path d="m9 12 2 2 4-4"/>',
    "Transportation": '<rect x="5" y="3" width="14" height="14" rx="2"/><path d="M5 11h14"/><path d="M7 17v3M17 17v3"/><circle cx="8.5" cy="14" r=".6"/><circle cx="15.5" cy="14" r=".6"/>',
    "FY Budget": '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/><path d="M14 12.8c-.4-.5-1.1-.8-1.9-.8-1.1 0-1.9.6-1.9 1.4 0 1.9 3.9 1 3.9 2.9 0 .8-.8 1.4-2 1.4-.9 0-1.6-.3-2-.9M12.1 11v.9M12.1 17.7v.8"/>',
    "Budget & Taxes": '<circle cx="12" cy="12" r="9"/><path d="M15 8.5c-.6-.9-1.7-1.5-3-1.5-1.9 0-3 1-3 2.3 0 3.2 6 1.7 6 5 0 1.3-1.2 2.4-3 2.4-1.4 0-2.6-.6-3.2-1.6"/><path d="M12 5.5v1.5M12 17v1.5"/>',
    "Environment & Energy": '<path d="M5 19c0-8 5-13 14-14-1 9-6 14-14 14Z"/><path d="M5 19c3-4 6-7 10-9"/>',
    "Economic Development": '<path d="M3 20h18"/><path d="m4 15 5-5 4 3 7-7"/><path d="M15 6h5v5"/>',
    "Land Use & Planning": '<path d="M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20V6.5Z"/><path d="M9 4v13.5M15 6.5V20"/>',
    "Parks & Recreation": '<path d="M12 3 7 10h3l-4 6h12l-4-6h3l-5-7Z"/><path d="M12 16v5"/>',
    "Arts & Culture": '<path d="M12 3a9 9 0 1 0 0 18c1.2 0 1.8-.8 1.8-1.7 0-1.3-1.1-1.6-1.1-2.7 0-.9.7-1.6 1.6-1.6H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3Z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/>',
    "Health & Social Services": '<path d="M12 20s-7.5-4.4-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.6-7.5 10-7.5 10Z"/><path d="M12 10.5v5M9.5 13h5"/>',
    "Civil Rights & Equity": '<path d="M12 4v16M8 20h8"/><path d="M5 7h14"/><path d="m5 7-2.5 6a2.5 2.5 0 0 0 5 0L5 7ZM19 7l-2.5 6a2.5 2.5 0 0 0 5 0L19 7Z"/>',
    "Business Regulation": '<path d="M4 9h16l-1-4H5L4 9Z"/><path d="M5 9v11h14V9"/><path d="M10 20v-5h4v5"/>',
    "Government Operations": '<path d="M3 20h18M4 17h16"/><path d="M5 17v-7M9.5 17v-7M14.5 17v-7M19 17v-7"/><path d="M3 10h18L12 4 3 10Z"/>',
    "Government Transparency": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>',
    "Libraries": '<path d="M4 5.5C6.5 4.5 9.5 4.5 12 6c2.5-1.5 5.5-1.5 8-.5v13c-2.5-1-5.5-1-8 .5-2.5-1.5-5.5-1.5-8-.5v-13Z"/><path d="M12 6v13"/>',
    "Early Childhood & Education": '<circle cx="12" cy="6.5" r="2.5"/><path d="M7 21v-5.5a5 5 0 0 1 10 0V21"/><path d="M4 12.5 7 15M20 12.5 17 15"/>',
    "Labor & Workforce": '<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M9 7.5V5.5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5.5v2"/><path d="M3.5 12.5h17"/>',
    "Elections": '<path d="M5 11h14v9H5z"/><path d="M8 11V5h8v6"/><path d="m10 8 1.5 1.5L14 7"/>',
    "Animal Services": '<circle cx="7" cy="10" r="1.8"/><circle cx="17" cy="10" r="1.8"/><circle cx="10" cy="6" r="1.8"/><circle cx="14" cy="6" r="1.8"/><path d="M12 12c-2.8 0-5 3.2-5 5.3 0 1.4 1.2 2.2 2.6 2 .9-.1 1.6-.5 2.4-.5s1.5.4 2.4.5c1.4.2 2.6-.6 2.6-2 0-2.1-2.2-5.3-5-5.3Z"/>',
  };
  const DEFAULT_ICON = '<circle cx="12" cy="12" r="8"/>';

  function themeIcon(theme, size) {
    const s = size || 24;
    return `<svg class="icon" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${THEME_ICONS[theme] || DEFAULT_ICON}</svg>`;
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v == null || v === false) return;
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else node.setAttribute(k, v);
    });
    children.flat().forEach((c) => { if (c != null && c !== "") node.append(c); });
    return node;
  }

  const fmtDate = (iso, opts) => {
    const d = new Date(iso + "T12:00:00");
    return isNaN(d) ? iso : d.toLocaleDateString("en-US", opts || { year: "numeric", month: "short", day: "numeric" });
  };

  // Short seat label for column headers: "Chair", "D1" … "D4".
  const seatShort = (seat) => (seat || "").replace(/^District /, "D");

  // Error reports go to GitHub Issues through the form in .github/ISSUE_TEMPLATE/report-error.yml.
  const REPO = "https://github.com/Portland-City-Council-Votes/multco-commissioner-votes";
  function reportLink(vote) {
    const params = { template: "report-error.yml" };
    if (vote) {
      const what = vote.motion ? `${vote.kind}: "${vote.motion}" on ${vote.item_title}` : vote.title;
      const label = [vote.date, vote.item, vote.doc_number, what].filter(Boolean).join(" · ");
      params.title = "Report: " + [vote.date, vote.item, (vote.title || vote.item_title || "").slice(0, 70)].filter(Boolean).join(" ");
      params.vote = label.slice(0, 250);
    }
    return REPO + "/issues/new?" + new URLSearchParams(params).toString();
  }

  // Links into the full data page with a filter applied.
  const dataLink = (key, value) => "data.html#" + new URLSearchParams({ [key]: value }).toString();

  window.MCV = {
    parseCSV, splitList, loadAll, fetchJSON, themeIcon, el, fmtDate, dataLink, reportLink,
    seatOn, yearsServed, seatShort, NOT_IN_OFFICE, REPO,
  };
})();
