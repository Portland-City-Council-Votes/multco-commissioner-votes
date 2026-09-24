// Home page: explore votes by commissioner or theme.

(function () {
  "use strict";

  const { loadAll, fetchJSON, themeIcon, el, fmtDate, dataLink, yearsServed } = window.MCV;

  // One card per seat: the Chair (elected countywide) and Districts 1–4. Current commissioners
  // and Sharon Meieran get photos; earlier members of the Board since 2017 are listed by name.
  const SEATS = ["Chair", "District 1", "District 2", "District 3", "District 4"];

  function renderCommissioners(commissioners) {
    const root = document.getElementById("commissioners");
    SEATS.forEach((seat) => {
      const holders = commissioners.filter((c) => (c.terms || []).some((t) => t.seat === seat));
      const featured = holders.filter((c) => c.featured && (c.terms[c.terms.length - 1].seat === seat || !c.current));
      const others = holders.filter((c) => !featured.includes(c));
      const up = featured.some((c) => c.current && c.next_election);
      const district = seat === "Chair" ? "Chair" : seat.replace("District ", "");
      const tile = (c) => {
        const bits = [c.full_name];
        if (!c.current) bits.push(`former ${seat} Commissioner, ${yearsServed({ terms: c.terms.filter((t) => t.seat === seat) })}`);
        if (c.current && c.next_election) bits.push(`seat on the ballot ${fmtDate(c.next_election)}`);
        return el("li", {},
          el("a", { class: "person" + (c.current && c.next_election ? " is-up" : "") + (c.current ? "" : " is-former"),
            href: dataLink("commissioner", c.name), "aria-label": `${bits.join(", ")}: see every vote` },
            c.photo ? el("img", { src: c.photo, alt: "", width: "150", height: "150", loading: "lazy" }) : null,
            el("span", { class: "person-name" }, c.full_name),
            el("span", { class: "person-meta" }, c.current ? `Since ${c.terms.find((t) => t.seat === seat).start.slice(0, 4)}` : `Former · ${yearsServed({ terms: c.terms.filter((t) => t.seat === seat) })}`),
            c.candidate ? el("span", { class: "cand-tag" }, c.candidate) : null));
      };
      root.append(el("div", { class: "district" + (seat === "Chair" ? " is-chair" : "") + (up ? " is-up" : ""), "data-district": district, tabindex: "-1" },
        el("h3", {}, seat === "Chair" ? "Chair · countywide" : seat,
          up ? el("span", { class: "up-tag" }, "On the ballot Nov. 3") : null),
        el("ul", { class: "people" }, featured.map(tile)),
        others.length ? el("p", { class: "earlier" }, "Also on the Board in this seat since 2017: ",
          others.map((c, i) => [i ? ", " : "",
            el("a", { href: dataLink("commissioner", c.name) }, c.full_name),
            ` (${yearsServed({ terms: c.terms.filter((t) => t.seat === seat) })})`])) : null
      ));
    });
  }

  // Point-in-polygon (ray casting) on [lon, lat] rings; holes are the rings after the first.
  function inRing(pt, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function inGeometry(pt, geom) {
    const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
    return polys.some(([outer, ...holes]) => inRing(pt, outer) && !holes.some((h) => inRing(pt, h)));
  }

  // Address -> location via OpenStreetMap Nominatim (limited to Multnomah County), then -> district.
  function setupDistrictFinder() {
    const form = document.getElementById("find-district");
    const input = document.getElementById("address");
    const out = document.getElementById("find-result");
    let districts = null;

    const highlight = (d) => {
      document.querySelectorAll(".district").forEach((box) => {
        const mine = String(box.dataset.district) === String(d);
        box.classList.toggle("is-mine", mine);
        const tag = box.querySelector(".mine-tag");
        if (mine && !tag) box.querySelector("h3").append(el("span", { class: "mine-tag" }, "Your district"));
        if (!mine && tag) tag.remove();
      });
    };

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const address = input.value.trim();
      if (!address) return;
      out.className = "find-result";
      out.textContent = "Looking up that address…";
      highlight(null);
      try {
        if (!districts) districts = await fetchJSON("assets/districts.json");
        const q = /oregon|\bor\b|\b97\d{3}\b/i.test(address) ? address : `${address}, Multnomah County, Oregon`;
        const url = "https://nominatim.openstreetmap.org/search?" + new URLSearchParams({
          q, format: "jsonv2", limit: "1", countrycodes: "us",
          viewbox: "-122.95,45.73,-121.80,45.42", bounded: "1",
        });
        const res = await fetch(url, { headers: { "Accept-Language": "en" } });
        if (!res.ok) throw new Error(`address search failed (${res.status})`);
        const [hit] = await res.json();
        if (!hit) {
          out.classList.add("is-error");
          out.textContent = "Couldn't find that address in Multnomah County. Try adding the street type (St, Ave), direction (NE, SE…) and city.";
          return;
        }
        const pt = [parseFloat(hit.lon), parseFloat(hit.lat)];
        const match = districts.features.find((f) => inGeometry(pt, f.geometry));
        if (!match) {
          out.classList.add("is-error");
          out.textContent = `${address} looks to be outside Multnomah County, so it isn't in a County Commission district.`;
          return;
        }
        const d = match.properties.district;
        out.classList.add("is-found");
        out.replaceChildren(`${address} is in `, el("strong", {}, `District ${d}`),
          ". Your district commissioner is highlighted below; the Chair represents the whole county.");
        highlight(d);
        const box = document.querySelector(`.district[data-district="${d}"]`);
        if (box) {
          box.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
          box.focus({ preventScroll: true });
        }
      } catch (err) {
        out.classList.add("is-error");
        out.textContent = "Address search isn't available right now (" + err.message + "). Please try again in a moment.";
      }
    });
  }

  function renderThemes(votes, motions) {
    const count = (list) => {
      const m = new Map();
      list.forEach((r) => r.themes.forEach((t) => m.set(t, (m.get(t) || 0) + 1)));
      return m;
    };
    const finals = count(votes);
    const extra = count(motions);
    const root = document.getElementById("themes");
    [...finals.entries()].sort((a, b) => b[1] - a[1]).forEach(([theme, n]) => {
      const m = extra.get(theme) || 0;
      const href = "data.html#" + new URLSearchParams(m ? { theme, show: "all" } : { theme }).toString();
      root.append(el("a", { class: "theme-card", href },
        el("span", { class: "theme-icon", html: themeIcon(theme, 32) }),
        el("span", { class: "theme-name" }, theme),
        el("span", { class: "theme-count" }, `${n} final vote${n === 1 ? "" : "s"}` + (m ? ` · ${m} on amendments/motions` : ""))));
    });
  }

  async function load() {
    let data;
    try {
      data = await loadAll();
    } catch (err) {
      document.getElementById("commissioners").replaceChildren(el("p", { class: "empty" }, "Couldn't load the vote data (" + err.message + ")."));
      return;
    }
    renderCommissioners(data.commissioners);
    setupDistrictFinder();
    renderThemes(data.votes, data.motions);
  }

  load();
})();
