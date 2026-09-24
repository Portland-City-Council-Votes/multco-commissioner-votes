// Full data page: every vote in a filterable table.
// Filters live in the URL hash so the home page (and anyone) can link to a filtered view.

(function () {
  "use strict";

  const { loadAll, el, fmtDate, reportLink, seatOn, yearsServed, seatShort, NOT_IN_OFFICE } = window.MCV;
  const VOTE_ABBR = { Yea: "Y", Nay: "N", Absent: "A", Abstain: "Ab", [NOT_IN_OFFICE]: "·" };
  const FILTER_IDS = ["q", "theme", "year", "show", "commissioner", "vote", "sort", "contested"];
  const WIDE = ["Countywide"];

  const els = Object.fromEntries(
    FILTER_IDS.concat(["filters", "results", "summary", "banner"]).map((id) => [id, document.getElementById(id)])
  );

  let rows = [];
  let motions = [];
  let commissioners = [];

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
    els.banner.append(
      c.photo ? el("img", { src: c.photo, alt: "", width: "104", height: "104" }) : null,
      el("div", {},
        el("h2", {}, c.full_name),
        el("p", { class: "meta" }, seatsText(c),
          c.next_election ? el("span", { class: "up-tag" }, `Seat on the ballot ${fmtDate(c.next_election)}`) : null,
          c.candidate ? el("span", { class: "cand-tag" }, c.candidate) : null,
          c.profile ? [" · ", el("a", { href: c.profile, target: "_blank", rel: "noopener" }, "County profile")] : null),
        el("p", {}, `${counts.Yea} Yea · ${counts.Nay} Nay · ${counts.Absent} absent · ${counts.Abstain} abstain across the ${served} final votes logged while in office. ` +
          `On the losing side ${dissent} time${dissent === 1 ? "" : "s"}.`),
        mServed ? el("p", { class: "meta" },
          `On amendments and motions: ${mCounts.Yea} Yea, ${mCounts.Nay} Nay across ${mServed} roll calls.`) : null
      )
    );
  }

  // Short outlet names for thumbnails that have no preview image yet.
  const OUTLET_SHORT = { "Willamette Week": "WW", "Portland Mercury": "Mercury", "Portland Tribune": "Tribune", "Oregon Public Broadcasting": "OPB" };
  const outletShort = (name) => OUTLET_SHORT[name] || name;

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
          el("p", { class: "meta" }, [r.item, r.doc_number ? `No. ${r.doc_number}` : "", r.type, r.action].filter(Boolean).join(" · "),
            " · ", el("a", { href: r.url, target: "_blank", rel: "noopener" }, "Agenda"),
            r.minutes ? [" · ", el("a", { href: r.minutes, target: "_blank", rel: "noopener" }, "Minutes")] : null),
          el("a", { class: "report", href: reportLink(r), target: "_blank", rel: "noopener" }, "Report an error"),
        );
    if (!isMotion && r.news.length) {
      item.classList.add("has-news");
      item.prepend(el("ul", { class: "thumbs", "aria-label": "In the news" },
        r.news.map((n) => el("li", {},
          el("a", { class: "thumb", href: n.url, target: "_blank", rel: "noopener", title: `${n.headline} (${n.outlet})` },
            n.image
              ? el("img", { src: n.image, alt: "", loading: "lazy", referrerpolicy: "no-referrer" })
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
    shown.forEach((c, i) => {
      const v = r[c.name] || "";
      const seat = seatOn(c, r.date);
      const label = seat ? `${c.name} (${seatShort(seat)})` : c.name;
      const nio = v === NOT_IN_OFFICE;
      const cls = "v v-" + (nio ? "nio" : (v || "none").toLowerCase()) + (focus === c.name ? " is-focus" : "") +
        (i > 0 && shown[i - 1].current !== c.current ? " d-start" : "");
      const text = nio ? "not in office" : v || "no vote recorded";
      cells.push(el("td", { class: cls, "data-name": label, title: `${label}: ${text}` },
        el("span", { "aria-hidden": "true" }, VOTE_ABBR[v] || "–"),
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
    // Newest first; within a day keep final votes after the motions that led to them.
    list.sort((a, b) => (f.sort === "oldest" ? 1 : -1) * (a.date.localeCompare(b.date) ||
      (a.kind === "Final vote") - (b.kind === "Final vote") || (+a.seq || 0) - (+b.seq || 0)));

    const total = all.length;
    const noun = f.show === "motions" ? "amendment and motion votes" : f.show === "all" ? "votes (final, amendments and motions)" : "final votes";
    els.summary.textContent = total
      ? `Showing ${list.length} of ${total} ${noun}.`
      : "No votes have been added yet. Data collection is in progress.";

    els.results.replaceChildren();
    if (!total) return;
    if (!list.length) {
      els.results.append(el("p", { class: "empty" }, "No votes match these filters."));
      return;
    }

    // Only show commissioners who were on the Board for at least one row in view.
    const shown = commissioners.filter((c) => list.some((r) => r[c.name] && r[c.name] !== NOT_IN_OFFICE));
    const head = el("tr", {},
      el("th", { scope: "col", class: "c-date" }, "Date"),
      el("th", { scope: "col", class: "c-item" }, "Item"),
      el("th", { scope: "col", class: "c-tags" }, "Theme"),
      el("th", { scope: "col", class: "c-tally" }, "Yea–Nay"),
      shown.map((c, i) => {
        const seat = (c.terms || []).length ? c.terms[c.terms.length - 1].seat : "";
        return el("th", { scope: "col", class: "v-head" + (f.commissioner === c.name ? " is-focus" : "") +
            (i > 0 && shown[i - 1].current !== c.current ? " d-start" : "") + (c.current ? "" : " is-former"),
          title: `${c.full_name}, ${c.current ? "" : "former "}${seat === "Chair" ? "Chair" : seat + " Commissioner"} (${yearsServed(c)})` },
          el("span", { class: "v-name" }, c.name),
          seat ? el("span", { class: "v-district" }, c.current ? seatShort(seat) : "Former") : null);
      })
    );
    const table = el("table", { class: "votes" },
      el("caption", { class: "sr-only" }, "Board votes, one row per item, one column per commissioner"),
      el("thead", {}, head),
      el("tbody", {}, list.map((r) => renderRow(r, f.commissioner, shown)))
    );
    els.results.append(el("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": "Votes table" }, table),
      el("p", { class: "legend" }, "Y = Yea · N = Nay · A = absent or excused · Ab = abstained or recused · “·” = not on the Board at the time. Columns show only the commissioners who were on the Board for the votes listed."));
  }

  async function load() {
    try {
      ({ votes: rows, motions, commissioners } = await loadAll());
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
