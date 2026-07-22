/* Exposure Comparison — explorer.
   One map for seven exposure models on WB ADM1 (single-model choropleth or
   two-model difference), metric = value (constant latest-year US$) or floor
   area (m2), class = total / urban / rural, plus a composition breakdown
   chart under the map (urban/rural, res/non-res, res/com/ind) scoped to the
   country or a clicked ADM1 unit. Availability driven by data/<ISO>/meta.json.
   Values for Overture/GBA/Microsoft are estimated (floor area x GEM UCC). */

(function () {
  "use strict";

  const ISO = "MAR";
  const MODEL_ORDER = ["gar15", "giri", "gem2023", "gem2026", "overture", "gba", "msb"];
  const SEG_COLORS = ["#17406D", "#009DD9", "#A5C249", "#0BD0D9"];

  const RAMP_SEQ = ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"];
  // ColorBrewer RdBu (colorblind-safe): red = A higher, blue = B higher
  const RAMP_DIV = ["#b2182b", "#ef8a62", "#fddbc7", "#f7f7f7", "#d1e5f0", "#67a9cf", "#2166ac"];
  const NODATA = "#e1e0d9";

  const fmtUsd = (v) => {
    if (v == null || !isFinite(v)) return "–";
    const a = Math.abs(v), s = v < 0 ? "−" : "";
    if (a >= 1e9) return s + "$" + (a / 1e9).toFixed(a >= 1e10 ? 0 : 1) + "B";
    if (a >= 1e6) return s + "$" + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
    if (a >= 1e3) return s + "$" + (a / 1e3).toFixed(0) + "k";
    return s + "$" + a.toFixed(0);
  };
  const fmtArea = (v) => {
    if (v == null || !isFinite(v)) return "–";
    const a = Math.abs(v), s = v < 0 ? "−" : "";
    if (a >= 1e9) return s + (a / 1e9).toFixed(2) + " Bm²";
    if (a >= 1e6) return s + (a / 1e6).toFixed(1) + " Mm²";
    if (a >= 1e3) return s + (a / 1e3).toFixed(0) + "k m²";
    return s + a.toFixed(0) + " m²";
  };
  const fmtPct = (v) => (v == null || !isFinite(v)) ? "–" :
    (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(0) + "%";

  const S = {  // UI state
    mode: "single", metric: "value", cls: "total",
    model: "gar15", giriSub: "total", a: "gar15", b: "giri", diff: "abs",
    scopeCode: null,           // breakdown chart scope (null = country)
    breakAbs: false,           // breakdown: share (false) vs absolute (true)
    grow: false,               // vintage adjustment: grow to target year
  };

  let META = null, FEATURES = null, map = null, hoverPopup = null;

  // ---------- availability ----------
  function colFor(mk, metric, cls, giriSub) {
    const m = META.models[mk];
    if (metric === "value") {
      if (!m.value) return null;
      if (mk === "giri") {
        if (cls !== "total") return null;
        return (giriSub && giriSub !== "total") ? m.sub[giriSub] : m.value.total;
      }
      return m.value[cls] || null;
    }
    return m.floor ? (m.floor[cls] || null) : null;
  }
  // nominal USD columns get the constant-dollar sibling for display
  const dispCol = (c) => (c && S.metric === "value")
    ? c + META.deflator.adj_suffix : c;
  const available = (mk) => colFor(mk, S.metric, S.cls, "total") != null;
  const fmt = () => (S.metric === "value" ? fmtUsd : fmtArea);
  const usdYear = () => META.deflator.target_year;
  const label = (mk) => META.models[mk].label +
    (S.metric === "value" && META.models[mk].estimated_value ? " (est.)" : "");
  // vintage growth factor: data-driven (CWON capital path for value, GHSL
  // built-up-volume rate for floor area); 1 when the toggle is off
  const growFactor = (mk) => {
    if (!S.grow || !META.vintages) return 1;
    const g = S.metric === "value" ? META.vintages.value_growth
                                   : META.vintages.floor_growth;
    return (g.factors && g.factors[mk]) || 1;
  };

  // ---------- data ----------
  Promise.all([
    fetch("data/" + ISO + "/meta.json").then((r) => r.json()),
    fetch("data/" + ISO + "/adm1.geojson").then((r) => r.json()),
  ]).then(([meta, geo]) => {
    META = meta;
    FEATURES = geo;
    document.querySelectorAll("[data-meta-line]").forEach((el) => {
      el.textContent = "Data built " + (meta.generated || "") +
        " · values in constant " + usdYear() + " US$";
    });
    // brand carries the country name from the data build, not hardcoded
    const short = (meta.country || "").split(" (")[0];
    document.querySelectorAll(".brand span").forEach((el) => {
      if (short) el.textContent = "· " + short;
    });
    initMap(geo);
    wireControls();
    refresh();
  }).catch((e) => {
    document.getElementById("model-note").textContent =
      "Failed to load data (" + e + "). If previewing locally, serve over http.";
  });

  // ---------- map ----------
  function initMap(geo) {
    map = new maplibregl.Map({
      container: "map",
      bounds: bbox(geo),
      fitBoundsOptions: { padding: 30 },
      style: {
        version: 8,
        sources: {
          carto: {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors © CARTO",
          },
        },
        layers: [{ id: "base", type: "raster", source: "carto" }],
      },
      dragRotate: false, attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    // refit if the flex layout settles after map construction (initial
    // zoom was computed against a not-yet-final container size)
    new ResizeObserver(() => map.resize()).observe(document.getElementById("map"));

    map.on("load", () => {
      // diagonal hatch for the Western Sahara (ESH) unit
      const c = document.createElement("canvas");
      c.width = c.height = 12;
      const x = c.getContext("2d");
      x.strokeStyle = "rgba(90,88,70,0.85)";
      x.lineWidth = 1.6;
      for (const o of [-6, 0, 6, 12]) {
        x.beginPath(); x.moveTo(o, 12); x.lineTo(o + 12, 0); x.stroke();
      }
      map.addImage("hatch", x.getImageData(0, 0, 12, 12), { pixelRatio: 2 });

      map.addSource("adm1", { type: "geojson", data: geo, promoteId: "code" });
      map.addLayer({ id: "adm1-fill", type: "fill", source: "adm1",
        paint: { "fill-color": NODATA, "fill-opacity": 0.82 } });
      map.addLayer({ id: "adm1-esh", type: "fill", source: "adm1",
        filter: ["==", ["get", "esh"], true],
        paint: { "fill-pattern": "hatch", "fill-opacity": 0.5 } });
      map.addLayer({ id: "adm1-line", type: "line", source: "adm1",
        paint: { "line-color": "#4a4a42", "line-width":
          ["case", ["boolean", ["feature-state", "hover"], false], 2.2, 0.7] } });
      map.addLayer({ id: "adm1-sel", type: "line", source: "adm1",
        filter: ["==", ["get", "code"], "__none__"],
        paint: { "line-color": "#0F6FC6", "line-width": 3 } });

      map.fitBounds(bbox(geo), { padding: 30, duration: 0 });

      let hovered = null;
      map.on("mousemove", "adm1-fill", (ev) => {
        const f = ev.features[0];
        if (hovered !== null) map.setFeatureState({ source: "adm1", id: hovered }, { hover: false });
        hovered = f.id;
        map.setFeatureState({ source: "adm1", id: hovered }, { hover: true });
        map.getCanvas().style.cursor = "pointer";
        showHover(ev.lngLat, f.properties);
      });
      map.on("mouseleave", "adm1-fill", () => {
        if (hovered !== null) map.setFeatureState({ source: "adm1", id: hovered }, { hover: false });
        hovered = null;
        map.getCanvas().style.cursor = "";
        if (hoverPopup) { hoverPopup.remove(); hoverPopup = null; }
      });
      map.on("click", "adm1-fill", (ev) => {
        const p = ev.features[0].properties;
        S.scopeCode = (S.scopeCode === p.code) ? null : p.code;
        map.setFilter("adm1-sel",
          ["==", ["get", "code"], S.scopeCode || "__none__"]);
        renderBreakdown();
        showDetail(ev.lngLat, p);
      });
      refresh();
    });
  }

  function bbox(geo) {
    let w = 180, s = 90, e = -180, n = -90;
    const scan = (cs) => cs.forEach((ring) => ring.forEach(([x, y]) => {
      w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y);
    }));
    geo.features.forEach((f) => {
      const g = f.geometry;
      if (g.type === "Polygon") scan(g.coordinates);
      else g.coordinates.forEach(scan);
    });
    return [[w, s], [e, n]];
  }

  // ---------- rendering ----------
  function valuesFor(colA, colB, mkA, mkB) {
    const fa = growFactor(mkA), fb = growFactor(mkB);
    return FEATURES.features.map((f) => {
      const p = f.properties;
      let v = null;
      if (S.mode === "single") v = p[colA] * fa;
      else if (colA != null && colB != null) {
        const a = p[colA] * fa, b = p[colB] * fb;
        v = S.diff === "abs" ? a - b : (b > 0 ? (100 * (a - b)) / b : null);
      }
      return { code: p.code, name: p.name, v: v };
    });
  }

  function refresh() {
    if (!META) return;
    syncControls();
    if (!map || !map.getLayer || !map.getLayer("adm1-fill")) return;

    let rows, colors;
    if (S.mode === "single") {
      const col = dispCol(colFor(S.model, S.metric, S.cls, S.giriSub));
      rows = valuesFor(col, null, S.model, null);
      colors = paintSequential(rows);
    } else {
      const ca = dispCol(colFor(S.a, S.metric, S.cls, "total"));
      const cb = dispCol(colFor(S.b, S.metric, S.cls, "total"));
      rows = valuesFor(ca, cb, S.a, S.b);
      colors = paintDiverging(rows);
    }
    const match = ["match", ["get", "code"]];
    rows.forEach((r, i) => { match.push(r.code, colors[i]); });
    match.push(NODATA);
    map.setPaintProperty("adm1-fill", "fill-color", match);
    renderTotals();
    renderBreakdown();
  }

  function quantBins(vals, k) {
    const s = vals.slice().sort((a, b) => a - b);
    const bins = [];
    for (let i = 1; i < k; i++) {
      bins.push(s[Math.min(s.length - 1, Math.floor((i * s.length) / k))]);
    }
    return [...new Set(bins)];
  }

  function paintSequential(rows) {
    const pos = rows.filter((r) => r.v > 0).map((r) => r.v);
    const bins = pos.length ? quantBins(pos, 6) : [];
    const ramp = RAMP_SEQ.slice(RAMP_SEQ.length - (bins.length + 1));
    const colors = rows.map((r) => {
      if (!(r.v > 0)) return NODATA;
      let i = 0;
      while (i < bins.length && r.v >= bins[i]) i++;
      return ramp[i];
    });
    legendSequential(bins, ramp);
    return colors;
  }

  function paintDiverging(rows) {
    const vals = rows.map((r) => r.v).filter((v) => v != null && isFinite(v));
    const m = Math.max(1e-9, ...vals.map(Math.abs));
    const edges = [-m * 5 / 7, -m * 3 / 7, -m / 7, m / 7, m * 3 / 7, m * 5 / 7];
    const ramp = RAMP_DIV.slice().reverse();   // red = positive (A higher)
    const colors = rows.map((r) => {
      if (r.v == null || !isFinite(r.v)) return NODATA;
      let i = 0;
      while (i < edges.length && r.v >= edges[i]) i++;
      return ramp[i];
    });
    legendDiverging(edges, ramp);
    return colors;
  }

  function metricLabel() {
    const cls = S.cls === "total" ? "" : " · " + S.cls;
    const grown = S.grow ? " · grown to " + usdYear() : "";
    return (S.metric === "value"
      ? "value, constant " + usdYear() + " US$" : "floor area") + cls + grown;
  }

  function legendSequential(bins, ramp) {
    const f = fmt();
    const lab = (i) => {
      if (i === 0) return "≤ " + f(bins[0]);
      if (i === bins.length) return "> " + f(bins[bins.length - 1]);
      return f(bins[i - 1]) + " – " + f(bins[i]);
    };
    document.getElementById("legend").innerHTML =
      "<h4>" + label(S.model) + " — " + metricLabel() + "</h4>" +
      (bins.length ? ramp.map((c, i) =>
        '<div class="row"><span class="sw" style="background:' + c + '"></span>' + lab(i) + "</div>"
      ).join("") : "<div class='row'>no data</div>") +
      '<div class="row"><span class="sw" style="background:' + NODATA + '"></span>none / n.a.</div>' +
      eshNote();
  }

  function legendDiverging(edges, ramp) {
    const f = S.diff === "pct" ? fmtPct : fmt();
    const lab = (i) => {
      if (i === 0) return "≤ " + f(edges[0]);
      if (i === edges.length) return "> " + f(edges[edges.length - 1]);
      return f(edges[i - 1]) + " – " + f(edges[i]);
    };
    document.getElementById("legend").innerHTML =
      "<h4>" + label(S.a) + " − " + label(S.b) + " — " + metricLabel() +
      (S.diff === "pct" ? " (% of B)" : "") + "</h4>" +
      ramp.map((c, i) =>
        '<div class="row"><span class="sw" style="background:' + c + '"></span>' + lab(i) + "</div>"
      ).join("") +
      '<div class="row" style="margin-top:2px">red = A higher · blue = B higher</div>' +
      eshNote();
  }

  const eshNote = () =>
    '<div class="esh-note">▨ Western Sahara: WB "non-determined legal status" ' +
    "unit, shown whole (never subdivided).</div>";

  // ---------- side panel ----------
  function renderTotals() {
    const el = document.getElementById("totals-bars");
    const f = fmt();
    const rows = MODEL_ORDER.map((mk) => {
      const col = dispCol(colFor(mk, S.metric, S.cls, "total"));
      return { mk: mk, label: label(mk),
               v: col ? META.totals[col] * growFactor(mk) : null };
    });
    const mx = Math.max(1e-9, ...rows.map((r) => r.v || 0));
    el.innerHTML = rows.map((r) => {
      const na = r.v == null;
      const sel = (S.mode === "single" && r.mk === S.model);
      return '<div class="tbar' + (na ? " na" : "") + (sel ? " sel" : "") +
        '" data-mk="' + r.mk + '"><div class="lbl"><b>' + r.label + "</b><span>" +
        (na ? "n.a." : f(r.v)) + '</span></div><div class="track"><div class="fill" style="width:' +
        (na ? 0 : Math.max(2, (100 * r.v) / mx)) + '%"></div></div></div>';
    }).join("");
    el.querySelectorAll(".tbar:not(.na)").forEach((b) => {
      b.addEventListener("click", () => {
        S.mode = "single";
        S.model = b.dataset.mk;
        refresh();
      });
    });
    document.getElementById("totals-title").textContent =
      "Country totals — " + metricLabel();
    const note = document.getElementById("model-note");
    if (S.mode === "single") {
      const m = META.models[S.model];
      note.textContent = m.note + (S.cls !== "total" && m.split_note
        ? " (" + m.split_note + ")" : "");
    } else {
      note.textContent = "Difference of " + label(S.a) + " minus " +
        label(S.b) + ". Mind vintages and value definitions (see About).";
    }
  }

  // ---------- breakdown chart ----------
  function scopeProps() {
    if (!S.scopeCode) return { name: "Country total", get: (c) => META.totals[c] };
    const f = FEATURES.features.find((x) => x.properties.code === S.scopeCode);
    return { name: f.properties.name, get: (c) => f.properties[c] };
  }

  function renderBreakdown() {
    const wrap = document.getElementById("breakdown-bars");
    if (!wrap || !META) return;
    const sc = scopeProps();
    const f = fmt();
    document.getElementById("breakdown-title").innerHTML =
      "Composition — " + metricLabel() + " · <b>" + sc.name + "</b>";
    document.getElementById("scope-reset").classList.toggle("hidden", !S.scopeCode);
    document.querySelectorAll("#break-seg button").forEach((b) =>
      b.classList.toggle("on", (b.dataset.break === "abs") === S.breakAbs));

    const rows = MODEL_ORDER.map((mk) => {
      const bd = (META.models[mk].breakdown || {})[S.metric];
      if (!bd) return null;
      const segs = bd.map(([col, name]) => ({
        name: name, v: (sc.get(dispCol(col)) || 0) * growFactor(mk) }));
      const tot = segs.reduce((s, x) => s + x.v, 0);
      return { mk: mk, label: label(mk), segs: segs, tot: tot };
    }).filter((r) => r && r.tot > 0);
    const mx = Math.max(1e-9, ...rows.map((r) => r.tot));

    wrap.innerHTML = rows.map((r) => {
      const width = S.breakAbs ? (100 * r.tot / mx) : 100;
      const segsHtml = r.segs.map((sg, i) => {
        const pct = 100 * sg.v / r.tot;
        const txt = sg.name + " " + (S.breakAbs ? f(sg.v) : pct.toFixed(0) + "%");
        return '<div class="bseg" title="' + sg.name + ": " + f(sg.v) + " (" +
          pct.toFixed(0) + '%)" style="width:' + pct + "%;background:" +
          SEG_COLORS[i % SEG_COLORS.length] + '">' +
          (pct > 14 ? "<span>" + txt + "</span>" : "") + "</div>";
      }).join("");
      // per-row key: phones hide the in-bar labels and show this instead
      const keyHtml = r.segs.map((sg, i) => {
        const pct = 100 * sg.v / r.tot;
        return '<span class="bkey-item"><span class="dot" style="background:' +
          SEG_COLORS[i % SEG_COLORS.length] + '"></span>' + sg.name + " " +
          (S.breakAbs ? f(sg.v) : pct.toFixed(0) + "%") + "</span>";
      }).join("");
      return '<div class="brow"><div class="blabel">' + r.label +
        '</div><div class="btrack"><div class="bfill" style="width:' + width +
        '%">' + segsHtml + '</div></div><div class="btot">' +
        f(r.tot) + '</div></div><div class="bkey">' + keyHtml + "</div>";
    }).join("") || '<div class="note">No models expose a breakdown for this metric.</div>';
  }

  // ---------- popups ----------
  function rowHtml(lab, val, f) {
    return "<tr><td>" + lab + "</td><td>" + f(val) + "</td></tr>";
  }

  function showHover(lngLat, p) {
    const f = fmt();
    let html = "<h4>" + p.name + " — " + metricLabel() + "</h4><table>";
    if (S.mode === "compare") {
      const ca = dispCol(colFor(S.a, S.metric, S.cls, "total"));
      const cb = dispCol(colFor(S.b, S.metric, S.cls, "total"));
      const av = p[ca] * growFactor(S.a), bv = p[cb] * growFactor(S.b);
      html += rowHtml("A · " + label(S.a), av, f) +
              rowHtml("B · " + label(S.b), bv, f) +
              rowHtml("Δ (A − B)", av - bv, f) +
              rowHtml("A / B", bv > 0 ? (av / bv).toFixed(2) + "×" : null,
                      (x) => x == null ? "–" : x);
    } else {
      MODEL_ORDER.forEach((mk) => {
        const col = dispCol(colFor(mk, S.metric, S.cls, "total"));
        html += rowHtml(label(mk), col ? p[col] * growFactor(mk) : null, f);
      });
    }
    html += "</table>";
    if (!hoverPopup) {
      hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8, maxWidth: "340px" });
    }
    hoverPopup.setLngLat(lngLat).setHTML(html).addTo(map);
  }

  function showDetail(lngLat, p) {
    const f = fmt();
    let html = "<h4>" + p.name + " — all models (" + metricLabel() + ")</h4><table>";
    MODEL_ORDER.forEach((mk) => {
      const col = dispCol(colFor(mk, S.metric, S.cls, "total"));
      html += rowHtml(label(mk), col ? p[col] * growFactor(mk) : null, f);
    });
    if (S.metric === "value" && S.cls === "total") {
      html += rowHtml("· GIRI residential", p[dispCol(META.models.giri.sub.res)], f);
      html += rowHtml("· GIRI non-residential", p[dispCol(META.models.giri.sub.nres)], f);
    }
    html += "</table>";
    if (p.esh === true || p.esh === "true") {
      html += '<div class="popup-esh">WB non-determined legal status area; GEM values ' +
        "here are its two southern-region units reassigned (see About).</div>";
    }
    new maplibregl.Popup({ offset: 8, maxWidth: "340px" }).setLngLat(lngLat).setHTML(html).addTo(map);
  }

  // ---------- controls ----------
  function segWire(id, key, cb) {
    document.querySelectorAll("#" + id + " button").forEach((b) => {
      b.addEventListener("click", () => {
        if (b.disabled) return;
        S[key] = b.dataset[key === "cls" ? "class" : key];
        (cb || refresh)();
      });
    });
  }

  function fillModelSelect(sel, pred, current) {
    sel.innerHTML = "";
    MODEL_ORDER.forEach((mk) => {
      if (!pred(mk)) return;
      const o = document.createElement("option");
      o.value = mk;
      o.textContent = label(mk);
      sel.appendChild(o);
    });
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
    return sel.value;
  }

  function wireControls() {
    segWire("mode-seg", "mode");
    segWire("metric-seg", "metric");
    segWire("class-seg", "cls");
    segWire("diff-seg", "diff");
    document.getElementById("model-sel").addEventListener("change", (e) => {
      S.model = e.target.value; refresh();
    });
    document.getElementById("giri-sel").addEventListener("change", (e) => {
      S.giriSub = e.target.value; refresh();
    });
    document.getElementById("model-a").addEventListener("change", (e) => {
      S.a = e.target.value; refresh();
    });
    document.getElementById("model-b").addEventListener("change", (e) => {
      S.b = e.target.value; refresh();
    });
    document.getElementById("scope-reset").addEventListener("click", () => {
      S.scopeCode = null;
      map.setFilter("adm1-sel", ["==", ["get", "code"], "__none__"]);
      renderBreakdown();
    });
    document.querySelectorAll("#break-seg button").forEach((b) => {
      b.addEventListener("click", () => {
        S.breakAbs = b.dataset.break === "abs";
        renderBreakdown();
      });
    });
    document.querySelectorAll("#grow-seg button").forEach((b) => {
      b.addEventListener("click", () => {
        S.grow = b.dataset.grow === "on";
        refresh();
      });
    });
  }

  function syncControls() {
    document.querySelectorAll("#mode-seg button").forEach((b) =>
      b.classList.toggle("on", b.dataset.mode === S.mode));
    document.querySelectorAll("#metric-seg button").forEach((b) =>
      b.classList.toggle("on", b.dataset.metric === S.metric));
    document.querySelectorAll("#diff-seg button").forEach((b) =>
      b.classList.toggle("on", b.dataset.diff === S.diff));
    document.querySelectorAll("#grow-seg button").forEach((b) => {
      b.classList.toggle("on", (b.dataset.grow === "on") === S.grow);
      if (b.dataset.grow === "on") b.textContent = "Grown to " + usdYear();
    });
    const gn = document.getElementById("grow-note");
    if (gn && META.vintages) {
      gn.textContent = S.grow
        ? ("Each model grown from its data vintage to " + usdYear() +
           (S.metric === "value"
             ? " along WB produced-capital accumulation (CWON, ~" +
               (100 * META.vintages.value_growth.trailing_cagr).toFixed(1) +
               "%/yr recently)."
             : " at the GHSL built-up-volume rate (~" +
               (100 * META.vintages.floor_growth.rate).toFixed(1) + "%/yr).") +
           " Use it to test how much of a gap is just data age.")
        : "Values as of each model's own data vintage.";
    }
    document.querySelectorAll("#class-seg button").forEach((b) => {
      const cls = b.dataset.class;
      const any = MODEL_ORDER.some((mk) => colFor(mk, S.metric, cls, "total"));
      b.disabled = !any;
      if (b.disabled && S.cls === cls) S.cls = "total";
      b.classList.toggle("on", b.dataset.class === S.cls);
    });

    document.getElementById("single-ctl").classList.toggle("hidden", S.mode !== "single");
    document.getElementById("compare-ctl").classList.toggle("hidden", S.mode !== "compare");

    if (S.mode === "single") {
      S.model = fillModelSelect(document.getElementById("model-sel"), available, S.model);
      document.getElementById("giri-sub").classList.toggle(
        "hidden", !(S.model === "giri" && S.metric === "value"));
    } else {
      S.a = fillModelSelect(document.getElementById("model-a"), available, S.a);
      S.b = fillModelSelect(document.getElementById("model-b"),
        (mk) => available(mk) && mk !== S.a, S.b === S.a ? null : S.b);
    }
  }
})();
