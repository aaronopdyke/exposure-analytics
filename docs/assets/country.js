/* Exposure Comparison — country selection shared by every page.
   The country is carried in the URL (?c=ISO3) so links are shareable; the
   last one visited is remembered for the session so a bare explorer.html /
   about.html link still opens somewhere sensible. */

window.EXPCMP = (function () {
  "use strict";

  const KEY = "expcmp_country";
  const FALLBACK = "MAR";

  function iso() {
    const m = /[?&]c=([A-Za-z]{3})(?:&|$)/.exec(location.search);
    let v = m ? m[1].toUpperCase() : null;
    if (!v) {
      try { v = sessionStorage.getItem(KEY); } catch (e) { /* private mode */ }
    }
    return v && /^[A-Z]{3}$/.test(v) ? v : FALLBACK;
  }

  /* Called once a page has its meta.json: remembers the country, stamps the
     footer line, keeps the country on every internal link, and fills the
     header switcher from the index of built countries. */
  function decorate(meta) {
    const code = meta.iso;
    try { sessionStorage.setItem(KEY, code); } catch (e) { /* ignore */ }

    document.querySelectorAll("[data-meta-line]").forEach((el) => {
      el.textContent = "Data built " + (meta.generated || "") +
        " · values in constant " + meta.deflator.target_year + " US$";
    });
    document.querySelectorAll("a[data-c]").forEach((a) => {
      a.setAttribute("href", a.getAttribute("href").split("?")[0] + "?c=" + code);
    });

    const sel = document.getElementById("country-sel");
    if (!sel) return;
    const name = meta.name || (meta.country || "").split(" (")[0];
    const fill = (list) => {
      sel.innerHTML = "";
      list.forEach((c) => {
        const o = document.createElement("option");
        o.value = c.iso;
        o.textContent = c.name;
        sel.appendChild(o);
      });
      sel.value = code;
      sel.classList.remove("hidden");
    };
    fill([{ iso: code, name: name }]);
    fetch("data/countries.json").then((r) => r.json()).then((list) => {
      if (list.some((c) => c.iso === code)) fill(list);
    }).catch(() => { /* keep the single-country fallback */ });
    sel.addEventListener("change", () => {
      location.href = location.pathname + "?c=" + sel.value;
    });
  }

  return { iso: iso, decorate: decorate };
})();
