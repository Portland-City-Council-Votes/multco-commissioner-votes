// Full data page: every vote in a filterable table.
// Filters live in the URL hash so the home page (and anyone) can link to a filtered view.

(function () {
  "use strict";

  const { loadAll, el, fmtDate, reportLink, seatOn, yearsServed, seatShort, NOT_IN_OFFICE } = window.MCV;
  const VOTE_ABBR = { Yea: "Y", Nay: "N", Absent: "A", Abstain: "Ab", [NOT_IN_OFFICE]: "" };
  const FILTER_IDS = ["q", "theme", "year", "show", "commissioner", "vote", "sort", "contested"];
  const WIDE = ["Countywide"];
  // How the minutes recorded a vote, when it isn't a roll call with every name.
  const RECORD_NOTE = {
    "voice vote": "Voice vote: the minutes record no dissent, so everyone present is shown voting yes.",
    "not itemized": "The minutes note a roll call but don't list the votes; no dissent is recorded, so everyone present is shown voting yes.",
    "inferred": "The minutes name only some votes; the other commissioners present are shown voting yes, since no other dissent is recorded.",
    "partial": "The minutes don't record every commissioner's vote on this item; unrecorded votes are left blank.",
    "by hand": "Entered by hand from the minutes' text (the parser couldn't follow this passage); the synopsis says what the minutes show.",
  };

  const els = Object.fromEntries(
    FILTER_IDS.concat(["filters", "results", "summary", "banner"]).map((id) => [id, document.getElementById(id)])
  );

  let rows = [];
  let motions = [];
  let commissioners = [];
  // Easter egg: a made-up 4/20/2020 vote. It lives only here (not in the CSVs), is labeled as not
  // real, and is left out of every count, tally and commissioner summary.
  let egg = null;
  function makeEgg() {
    const date = "2020-04-20";
    const r = {
      date, item: "R.420", doc_number: "", document: "", record: "", minutes: "", egg: true,
      title: "Ordinance Declaring Green the Official Best Color of M&M’s.",
      synopsis: "Declares green the best color of M&M’s. Adopted unanimously.",
      type: "Ordinance", action: "Adopted", theme: "Arts & Culture", area: "Countywide",
      url: "https://youtu.be/dQw4w9WgXcQ", kind: "Final vote",
      news: [{ outlet: "The Candy Dish Gazette", headline: "In a sweet 5–0 vote, Multnomah County crowns green the best M&M",
        url: "https://youtu.be/dQw4w9WgXcQ", image: "" }],
    };
    commissioners.forEach((c) => { r[c.name] = seatOn(c, date) ? "Yea" : NOT_IN_OFFICE; });
    r.votes = commissioners.map((c) => ({ name: c.name, vote: r[c.name] }));
    r.tally = { Yea: r.votes.filter((v) => v.vote === "Yea").length, Nay: 0, Absent: 0, Abstain: 0 };
    r.split = false;
    r.themes = [r.theme];
    r.areas = [r.area];
    r.year = "2020";
    r.haystack = [r.title, r.synopsis, r.item, r.action, r.news[0].headline, "m&ms mms easter egg"].join(" ").toLowerCase();
    return r;
  }
  const SEAT_ORDER = ["Chair", "District 1", "District 2", "District 3", "District 4"];
  const lastSeat = (c) => ((c.terms || [])[c.terms.length - 1] || {}).seat || "";
  // One column per commissioner per seat they held: someone who moved from a district to the Chair
  // (Vega Pederson) has a column under each seat, and each shows only the votes cast from that seat.
  const seatColumns = (c) => [...new Set((c.terms || []).map((t) => t.seat))].map((seat) => {
    const terms = c.terms.filter((t) => t.seat === seat);
    return { c, seat, terms, current: c.current && seat === lastSeat(c), end: terms[terms.length - 1].end || "9999" };
  });

  function fillSelect(select, options) {
    options.forEach(([value, label]) => select.add(new Option(label, value)));
  }

  function uniqueSorted(lists) {
    return [...new Set(lists.flat())].sort((a, b) => a.localeCompare(b));
  }

  function readFilters() {
    return {
      q: els.q.value.trim().toLowerCase(),
      theme: els.theme.value,
      year: els.year.value,
      show: els.show.value,
      commissioner: els.commissioner.value,
      vote: els.vote.value,
      sort: els.sort.value,
      contested: els.contested.checked,
    };
  }

  function matches(r, f) {
    if (f.q && !r.haystack.includes(f.q)) return false;
    if (f.theme && !r.themes.includes(f.theme)) return false;
    if (f.year && r.year !== f.year) return false;
    if (f.contested && !r.split) return false;
    if (f.commissioner && r[f.commissioner] === NOT_IN_OFFICE) return false;
    if (f.vote) {
      const pool = f.commissioner ? r.votes.filter((v) => v.name === f.commissioner) : r.votes;
      if (!pool.some((v) => v.vote === f.vote)) return false;
    }
    return true;
  }

  function writeHash(f) {
    const params = new URLSearchParams();
    Object.entries(f).forEach(([k, v]) => {
      if (k === "q") v = els.q.value.trim();
      if (k === "sort" && v === "newest") return;
      if (v === true) params.set(k, "1");
      else if (v) params.set(k, v);
    });
    const hash = params.toString();
    history.replaceState(null, "", hash ? "#" + hash : location.pathname + location.search);
  }

  function readHash() {
    const params = new URLSearchParams(location.hash.slice(1));
    // Older links used "councilor"; treat it the same.
    if (params.has("councilor") && !params.has("commissioner")) params.set("commissioner", params.get("councilor"));
    FILTER_IDS.forEach((id) => {
      const node = els[id];
      if (!params.has(id)) {
        if (node.type === "checkbox") node.checked = false;
        else node.value = id === "sort" ? "newest" : "";
        return;
      }
      if (node.type === "checkbox") node.checked = params.get(id) === "1";
      else if (node.tagName === "SELECT" && ![...node.options].some((o) => o.value === params.get(id))) return;
      else node.value = params.get(id);
    });
  }

  function tallyText(t) {
    const parts = [`${t.Yea}–${t.Nay}`];
    if (t.Absent) parts.push(`${t.Absent} absent`);
    if (t.Abstain) parts.push(`${t.Abstain} abstain`);
    return parts.join(", ");
  }

  function pool(show) {
    if (show === "motions") return motions;
    if (show === "all") return rows.concat(motions);
    return rows;
  }

  function seatsText(c) {
    return (c.terms || []).map((t) => `${t.seat === "Chair" ? "Chair" : t.seat + " Commissioner"} ${yearsServed({ terms: [t] })}`).join(" · ");
  }

  function renderBanner(f) {
    const c = commissioners.find((x) => x.name === f.commissioner);
    els.banner.hidden = !c;
    els.banner.replaceChildren();
    if (!c) return;
    const counts = { Yea: 0, Nay: 0, Absent: 0, Abstain: 0 };
    let served = 0;
    let dissent = 0;
    rows.forEach((r) => {
      const v = r[c.name];
      if (!v || v === NOT_IN_OFFICE) return;
      served++;
      if (v in counts) counts[v]++;
      // Voted against the outcome: Nay on something that passed, or Yea on something that failed.
      const passed = r.tally.Yea > r.tally.Nay;
      if ((v === "Nay" && passed) || (v === "Yea" && !passed && r.tally.Nay > 0)) dissent++;
    });
    const mCounts = { Yea: 0, Nay: 0 };
    let mServed = 0;
    motions.forEach((r) => {
      const v = r[c.name];
      if (!v || v === NOT_IN_OFFICE) return;
      mServed++;
      if (v in mCounts) mCounts[v]++;
    });
    els.banner.append(...[
      c.photo ? el("img", { src: c.photo, alt: "", width: "104", height: "104" }) : null,
      el("div", {},
        el("h2", {}, c.full_name),
        el("p", { class: "meta" }, seatsText(c),
          c.next_election ? el("span", { class: "up-tag" }, `Seat on the ballot ${fmtDate(c.next_election)}`) : null,
          c.not_running ? el("span", { class: "cand-tag is-leaving" }, "Not seeking reelection") : null,
          c.candidate ? el("span", { class: "cand-tag" }, c.candidate) : null,
          c.profile ? [" · ", el("a", { href: c.profile, target: "_blank", rel: "noopener" }, "County profile")] : null),
        el("p", {}, `${counts.Yea} Yea · ${counts.Nay} Nay · ${counts.Absent} absent · ${counts.Abstain} abstain across the ${served} final votes logged while in office. ` +
          `On the losing side ${dissent} time${dissent === 1 ? "" : "s"}.`),
        mServed ? el("p", { class: "meta" },
          `On amendments and motions: ${mCounts.Yea} Yea, ${mCounts.Nay} Nay across ${mServed} roll calls.`) : null
      )
    ].filter(Boolean));
  }

  // Short outlet names for thumbnails that have no preview image yet.
  const OUTLET_SHORT = { "Willamette Week": "WW", "Portland Mercury": "Mercury", "Portland Tribune": "Tribune", "Oregon Public Broadcasting": "OPB", "NW Labor Press": "Labor Press", "Lake Oswego Review": "LO Review", "Street Roots": "Street Roots", "The Candy Dish Gazette": "Candy Dish" };
  const outletShort = (name) => OUTLET_SHORT[name] || name;
  // A news image that won't load (moved, or blocked by the outlet) falls back to the outlet badge.
  const thumbImage = (n) => {
    const img = el("img", { src: n.image, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => img.replaceWith(el("span", { class: "thumb-badge", "aria-hidden": "true" }, outletShort(n.outlet))));
    return img;
  };

  function renderRow(r, focus, shown) {
    const isMotion = r.kind !== "Final vote";
    const item = isMotion
      ? el("td", { class: "c-item" },
          el("span", { class: "kind kind-" + r.kind.toLowerCase() }, r.kind),
          el("p", { class: "motion" }, r.motion),
          r.note ? el("p", { class: "note" }, r.note) : null,
          el("p", { class: "meta" }, "On: ",
            el("a", { href: r.url, target: "_blank", rel: "noopener" }, r.item_title),
            r.item ? ` (${r.item})` : ""),
          el("a", { class: "report", href: reportLink(r), target: "_blank", rel: "noopener" }, "Report an error"))
      : el("td", { class: "c-item" },
          el("a", { href: r.document || r.url, class: "item-title", target: "_blank", rel: "noopener" }, r.title),
          r.synopsis ? el("p", { class: "synopsis" }, r.synopsis) : null,
          RECORD_NOTE[r.record] ? el("p", { class: "record-note" }, RECORD_NOTE[r.record]) : null,
          el("p", { class: "meta" }, [r.item, r.doc_number ? `No. ${r.doc_number}` : "", r.type, r.action].filter(Boolean).join(" · "),
            " · ", el("a", { href: r.url, target: "_blank", rel: "noopener" }, "Agenda"),
            r.minutes ? [" · ", el("a", { href: r.minutes, target: "_blank", rel: "noopener" }, "Minutes")] : null),
          r.egg ? el("p", { class: "record-note" }, "Easter egg · not a real vote, and not counted anywhere on this site.")
            : el("a", { class: "report", href: reportLink(r), target: "_blank", rel: "noopener" }, "Report an error"),
        );
    if (!isMotion && r.news.length) {
      item.classList.add("has-news");
      item.prepend(el("ul", { class: "thumbs", "aria-label": "In the news" },
        r.news.map((n) => el("li", {},
          el("a", { class: "thumb", href: n.url, target: "_blank", rel: "noopener", title: `${n.headline} (${n.outlet})` },
            n.image
              ? thumbImage(n)
              : el("span", { class: "thumb-badge", "aria-hidden": "true" }, outletShort(n.outlet)),
            el("span", { class: "thumb-caption" }, n.headline),
            el("span", { class: "thumb-outlet" }, n.outlet))))));
    }
    const tags = (list, cls) => list.map((t) => el("span", { class: "tag " + cls }, t));
    const cells = [
      el("td", { class: "c-date" }, el("time", { datetime: r.date }, fmtDate(r.date))),
      item,
      el("td", { class: "c-tags" }, tags(r.themes, "tag-theme"),
        tags(r.areas.filter((n) => !WIDE.includes(n)), "tag-place")),
      el("td", { class: "c-tally" + (r.split ? " is-split" : "") }, tallyText(r.tally)),
    ];
    shown.forEach((col, i) => {
      const { c, seat } = col;
      const v = seatOn(c, r.date) === seat ? r[c.name] || "" : NOT_IN_OFFICE;
      const label = `${c.name} (${seatShort(seat)})`;
      const nio = v === NOT_IN_OFFICE;
      const cls = "v v-" + (nio ? "nio" : (v || "none").toLowerCase()) + (focus === c.name ? " is-focus" : "") +
        (i > 0 && shown[i - 1].seat !== seat ? " d-start" : "");
      const text = nio ? "not in office" : v || "no vote recorded";
      cells.push(el("td", { class: cls, "data-name": label, title: `${label}: ${text}` },
        el("span", { "aria-hidden": "true" }, v in VOTE_ABBR ? VOTE_ABBR[v] : "–"),
        el("span", { class: "sr-only" }, text)
      ));
    });
    return el("tr", { class: (r.split ? "is-split" : "") + (isMotion ? " is-motion" : "") }, cells);
  }

  function render() {
    const f = readFilters();
    writeHash(f);
    renderBanner(f);
    const all = pool(f.show);
    const list = all.filter((r) => matches(r, f));
    const counted = list.length;
    if (egg && f.show !== "motions" && matches(egg, f)) list.push(egg);
    // Newest first; within a day keep final votes after the motions that led to them.
    list.sort((a, b) => (f.sort === "oldest" ? 1 : -1) * (a.date.localeCompare(b.date) ||
      (a.kind === "Final vote") - (b.kind === "Final vote") || (+a.seq || 0) - (+b.seq || 0)));

    const total = all.length;
    const noun = f.show === "motions" ? "amendment and motion votes" : f.show === "all" ? "votes (final, amendments and motions)" : "final votes";
    els.summary.textContent = total
      ? `Showing ${counted} of ${total} ${noun}.`
      : "No votes have been added yet. Data collection is in progress.";

    els.results.replaceChildren();
    if (!total) return;
    if (!list.length) {
      els.results.append(el("p", { class: "empty" }, "No votes match these filters."));
      return;
    }

    // Only show a seat column if its commissioner held that seat for at least one row in view.
    // Columns are grouped by seat (Chair, then Districts 1–4): the current holder first, then the
    // former holders, most recent first.
    const shown = commissioners.flatMap(seatColumns)
      .filter(({ c, seat }) => list.some((r) => seatOn(c, r.date) === seat && r[c.name] && r[c.name] !== NOT_IN_OFFICE))
      .sort((a, b) => SEAT_ORDER.indexOf(a.seat) - SEAT_ORDER.indexOf(b.seat) ||
        b.current - a.current || b.end.localeCompare(a.end));
    const head = el("tr", {},
      el("th", { scope: "col", class: "c-date" }, "Date"),
      el("th", { scope: "col", class: "c-item" }, "Item"),
      el("th", { scope: "col", class: "c-tags" }, "Theme"),
      el("th", { scope: "col", class: "c-tally" }, "Yea–Nay"),
      shown.map(({ c, seat, terms, current }, i) =>
        el("th", { scope: "col", class: "v-head" + (f.commissioner === c.name ? " is-focus" : "") +
            (i > 0 && shown[i - 1].seat !== seat ? " d-start" : "") + (current ? "" : " is-former"),
          title: `${c.full_name}, ${current ? "" : "former "}${seat === "Chair" ? "Chair" : seat + " Commissioner"} (${yearsServed({ terms })})` },
          el("span", { class: "v-name" }, c.name),
          el("span", { class: "v-district" }, current ? seatShort(seat) : ["Former", el("br"), seatShort(seat)])))
    );
    const table = el("table", { class: "votes" },
      el("caption", { class: "sr-only" }, "Board votes, one row per item, one column per commissioner"),
      el("thead", {}, head),
      el("tbody", {}, list.map((r) => renderRow(r, f.commissioner, shown)))
    );
    els.results.append(el("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": "Votes table" }, table),
      el("p", { class: "legend" }, "Y = Yea · N = Nay · A = absent or excused · Ab = abstained or recused · – = not recorded in the minutes · empty = not on the Board (or not yet in that seat) at the time. Columns show only the commissioners who were on the Board for the votes listed, grouped by seat; a commissioner who held two seats has a column under each."));
  }

  async function load() {
    try {
      ({ votes: rows, motions, commissioners } = await loadAll());
      egg = makeEgg();
    } catch (err) {
      els.summary.textContent = "Couldn't load the vote data (" + err.message + ").";
      return;
    }
    fillSelect(els.theme, uniqueSorted(rows.concat(motions).map((r) => r.themes)).map((t) => [t, t]));
    fillSelect(els.year, [...new Set(rows.concat(motions).map((r) => r.year))].sort().reverse().map((y) => [y, y]));
    fillSelect(els.commissioner, commissioners.map((c) => {
      const seat = (c.terms || []).length ? c.terms[c.terms.length - 1].seat : "";
      return [c.name, `${c.full_name} (${c.current ? "" : "former "}${seat}${c.current ? "" : ", " + yearsServed(c)})`];
    }));
    readHash();
    render();
  }

  els.filters.addEventListener("input", render);
  els.filters.addEventListener("submit", (e) => e.preventDefault());
  els.filters.addEventListener("reset", () => setTimeout(render));
  window.addEventListener("hashchange", () => { readHash(); render(); });
  load();
})();
