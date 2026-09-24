// Budget page: adopted budget figures from data/budget.json, plus the Board's budget votes.

(function () {
  "use strict";

  const { loadAll, fetchJSON, el, fmtDate, NOT_IN_OFFICE } = window.MCV;
  const root = document.getElementById("budget");
  let budget, data;

  const money = (n) => {
    if (n >= 1e9) return `$${(n / 1e9).toFixed(2).replace(/\.?0+$/, "")}B`;
    if (n >= 1e6) return `$${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
    return `$${Math.round(n / 1e3)}K`;
  };
  const full = (n) => "$" + n.toLocaleString("en-US");
  const pct = (n, total) => {
    const p = (n / total) * 100;
    return p < 1 ? "<1%" : `${Math.round(p)}%`;
  };

  function statTile(label, value, note) {
    return el("div", { class: "stat" },
      el("span", { class: "stat-label" }, label),
      el("span", { class: "stat-value" }, money(value)),
      note ? el("span", { class: "stat-note" }, note) : null);
  }

  // Horizontal bar chart: one hue, sorted largest first, value and share at each bar's tip.
  function barChart(id, title, lede, section, describe) {
    const entries = Object.entries(section.items).sort((a, b) => b[1] - a[1]);
    const max = entries[0][1];
    const tip = el("div", { class: "bar-tip", role: "status" });
    tip.hidden = true;
    const rows = entries.map(([name, value]) => {
      const share = pct(value, section.total);
      const label = `${name}: ${full(value)} (${share} of ${money(section.total)})`;
      const bar = el("div", { class: "bar", style: `--w:${Math.max(0.4, (value / max) * 100).toFixed(2)}%` });
      const row = el("li", { class: "bar-row", tabindex: "0", "aria-label": label },
        el("span", { class: "bar-name" }, name),
        el("span", { class: "bar-track" }, bar,
          el("span", { class: "bar-value" }, `${money(value)} · ${share}`)),
        describe && describe[name] ? el("span", { class: "bar-desc" }, describe[name]) : null);
      const show = (x, y) => {
        tip.hidden = false;
        tip.textContent = label;
        tip.style.left = `${x}px`;
        tip.style.top = `${y}px`;
      };
      row.addEventListener("mousemove", (e) => {
        const box = row.parentElement.getBoundingClientRect();
        show(e.clientX - box.left + 14, e.clientY - box.top + 14);
      });
      row.addEventListener("mouseleave", () => { tip.hidden = true; });
      row.addEventListener("focus", () => show(0, row.offsetTop + row.offsetHeight));
      row.addEventListener("blur", () => { tip.hidden = true; });
      return row;
    });
    const table = el("table", { class: "mini-table" },
      el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Category"),
        el("th", { scope: "col" }, "Amount"), el("th", { scope: "col" }, "Share"))),
      el("tbody", {}, entries.map(([name, value]) => el("tr", {},
        el("th", { scope: "row" }, name), el("td", {}, full(value)), el("td", {}, pct(value, section.total))))),
      el("tfoot", {}, el("tr", {}, el("th", { scope: "row" }, "Total"), el("td", {}, full(section.total)), el("td", {}, "100%"))));
    return el("section", { class: "chart-card", "aria-labelledby": id },
      el("h2", { id }, title),
      el("p", { class: "section-lede" }, lede),
      el("div", { class: "bars-wrap" }, el("ul", { class: "bars" }, rows), tip),
      el("details", { class: "as-table" }, el("summary", {}, "Show as a table"), table),
      el("p", { class: "chart-source" }, "Source: ", section._source, "."));
  }

  function voteChips(r, commissioners) {
    return el("ul", { class: "chips" }, commissioners.filter((c) => r[c.name] !== NOT_IN_OFFICE).map((c) => {
      const v = r[c.name] || "";
      return el("li", { class: "chip v-" + (v || "none").toLowerCase(), title: `${c.full_name}: ${v || "no vote recorded"}` },
        `${c.name} `, el("strong", {}, { Yea: "Y", Nay: "N", Absent: "A", Abstain: "Ab" }[v] || "–"));
    }));
  }

  function tallyText(r) {
    const t = r.tally;
    return [`${t.Yea}–${t.Nay}`, t.Absent ? `${t.Absent} absent` : "", t.Abstain ? `${t.Abstain} abstaining` : ""]
      .filter(Boolean).join(", ");
  }

  function votesSection(year) {
    const { votes, motions, commissioners } = data;
    const find = (ref) => ref && votes.find((r) => r.date === ref.date && r.item === ref.item);
    const approval = find(year.approval);
    const adopt = find(year.adoption);
    const related = year.adoption ? motions.filter((r) => r.date === year.adoption.date && r.item === year.adoption.item) : [];
    const amendments = related.filter((r) => r.kind === "Amendment");
    const splitAmend = amendments.filter((r) => r.split).length;

    const card = (heading, r) => r ? el("div", { class: "vote-card" },
      el("h3", {}, heading),
      el("p", { class: "meta" }, `${fmtDate(r.date)} · `, el("strong", {}, tallyText(r))),
      r.synopsis ? el("p", {}, r.synopsis) : null,
      voteChips(r, commissioners)) : null;

    return el("section", { class: "chart-card", "aria-labelledby": "h-votes" },
      el("h2", { id: "h-votes" }, "How the Board voted"),
      el("p", { class: "section-lede" }, "The Board first meets as the Budget Committee to approve the Chair’s proposed budget in the spring, sends it to the Tax Supervising and Conservation Commission, then adopts it in June."),
      el("div", { class: "vote-cards" },
        card("Approved as the Budget Committee", approval),
        card("Adopted", adopt)),
      related.length ? el("p", {},
        `Before adopting it, the Board took ${related.length} more roll calls on this budget, ${amendments.length} of them on amendments (${splitAmend} split). Chips: Y = Yea, N = Nay, A = absent, Ab = abstained. `,
        el("a", { href: "data.html#" + new URLSearchParams({ theme: "FY Budget", year: year.adoption.date.slice(0, 4), show: "all" }).toString() }, "See every budget vote that year")) : null);
  }

  function render(fy) {
    const year = budget.years.find((y) => y.fy === fy) || budget.years[0];
    document.querySelectorAll("#years button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.fy === year.fy)));
    try { history.replaceState(null, "", "#" + encodeURIComponent(year.fy)); } catch (e) { /* ignore */ }
    const h = year.headline;
    root.replaceChildren(
      el("section", { class: "headline", "aria-label": `${year.fy} at a glance` },
        el("p", { class: "period" }, `${year.fy} · ${year.period} · adopted ${fmtDate(year.adopted)}`),
        el("div", { class: "stats-row" },
          statTile("Total budget", h.total_budget, "All funds. Counts money moving between County funds more than once, as budget law requires."),
          statTile("Department spending", h.department_spending, `What the ${Object.keys(year.expenses_by_department.items).length} departments are budgeted to spend, before contingency and reserves. ${h.fte.toLocaleString("en-US")} full-time-equivalent positions.`),
          statTile("General Fund spending", h.general_fund_spending, "The County’s most flexible money, mostly property and business income taxes."))),
      barChart("h-spend", "Where the money goes", "Spending by department, all funds. Nondepartmental includes the Chair’s and commissioners’ offices, debt payments and pass-through funding.",
        year.expenses_by_department),
      barChart("h-gf", "The General Fund", "The General Fund pays for core services such as the Sheriff’s Office and jails, public health and community justice. This is its spending by department.",
        year.general_fund_by_department),
      barChart("h-gf-in", "Where General Fund money comes from", "General Fund resources by category. Beginning working capital is money carried over from the prior year.",
        year.general_fund_resources),
      barChart("h-in", "Where all County money comes from", "Resources for all County funds, including money carried over from the prior year and money moving between funds.",
        year.county_resources),
      votesSection(year));
    document.getElementById("sources").replaceChildren("Figures: Multnomah County ",
      el("a", { href: year.source_page }, `${year.fy} adopted budget page`), " and ",
      el("a", { href: year.source_section }, "Financial Summaries, adopted budget volume 1"),
      ". Votes come from the Board’s meeting minutes; see the full data for every roll call.");
  }

  async function load() {
    try {
      [budget, data] = await Promise.all([fetchJSON("data/budget.json"), loadAll()]);
    } catch (err) {
      root.replaceChildren(el("p", { class: "empty" }, "Couldn't load the budget (" + err.message + ")."));
      return;
    }
    const years = document.getElementById("years");
    budget.years.forEach((y) => {
      const b = el("button", { type: "button", role: "radio", "data-fy": y.fy, "aria-checked": "false" }, y.fy);
      b.addEventListener("click", () => render(y.fy));
      years.append(b);
    });
    render(decodeURIComponent(location.hash.slice(1)));
  }

  load();
})();
