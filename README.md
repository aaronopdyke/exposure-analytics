# Exposure Analytics

**How much is the built environment worth — and do the world's public
building-exposure datasets agree?** Anyone doing disaster-risk work has to
pick an exposure dataset, and the candidates disagree — for the same country,
by multiples. This project puts seven public datasets on a common footing
(one boundary standard, one price basis, one zonal methodology) so you can
see *how much* they disagree, *why*, and *which differences actually matter*
for your use case.

**Live site:** https://aaronopdyke.github.io/exposure-analytics/
· countries: **Colombia**, **Marshall Islands**, **Morocco**, **Venezuela**
— pick one from the dropdown on the landing page, or switch from the header
of any page.

## What you can do with it

- **Choose a dataset with open eyes.** Before adopting GAR15, GIRI, GEM, or a
  footprint-derived estimate for a risk assessment, see where each sits for
  your country — total value, floor area, regional pattern, urban/rural
  split — and what drives its position.
- **Explore on the map.** One choropleth per model on World Bank Admin-1
  units, or a difference map of any two models (absolute or %). Switch
  between replacement value (constant US$) and floor area (m²); filter
  urban/rural; click a region for its composition and every model's figure.
- **Test whether "the data is old" explains a gap.** The *vintage adjustment*
  toggle grows each dataset from its own input vintage to the present along
  data-driven paths (WB produced capital for values, GHSL built-up volume for
  floor area). Spoiler for the countries built so far: it doesn't — gaps are
  method, not age.
- **Brief others.** A World Bank-branded PowerPoint per country (comparison
  first, then one slide per model, then assumptions/sensitivity) is built
  from the same data; every number and every comparative statement on it is
  computed from this repo's outputs.

## How to read the numbers

- The models measure **three different things**: GAR15/GIRI report the
  *capital stock of buildings* (top-down from national produced capital),
  GEM reports *engineering replacement cost*, and the footprint datasets
  (Overture, Global Building Atlas, Microsoft) carry *estimated replacement
  values* (floor area × GEM unit construction costs). None is market or
  insured value; all are structures-only (contents excluded — which is also
  why GEM's own published totals are higher than the figures here).
- **Disagreement is information, not error.** Footprint datasets count what
  is *mapped* (they miss what mappers miss); top-down models distribute
  national aggregates (they include unmapped stock but inherit their source's
  assumptions). A gap between the two tells you something real about a
  country's data landscape.
- **Magnitudes hold up under the assumptions.** For Morocco the native-value
  models span ~2.7×; growing everything to a common year *widens* the spread,
  and even extreme storey-height rules move footprint totals only −8%/+29%.
  The conclusions are about method, not tuning. Each country's own figures
  are on its About page.
- **The ranking is not universal.** In Morocco the top-down capital-stock
  models sit above the footprint estimates; in the Marshall Islands the
  mapped footprints imply more than twice the floor area the engineering
  model assumes. That is the reason to look country by country.

Everything model-specific — vintages, price bases, boundary handling, the
UCC valuation, caveats per dataset — is documented on the site's About page.

## Layout

- `config.yaml` — the `countries:` registry (name, GEM/Microsoft region
  names, name aliases, unit policy), pinned source URLs, boundary policy
- `src/` — loaders and shared machinery: `boundaries.py` (WB ADM1, the
  Western Sahara policy, atoll units where WB has no subdivisions),
  `gar15.py`, `giri.py`, `gem.py` (both releases),
  `buildings.py` (DuckDB extraction: Overture / GBA / Microsoft),
  `ucc.py` (unit construction costs), `deflate.py` (price-year and growth
  alignment), `util.py` (downloads + zonal aggregation)
- `notebooks/exposure_comparison.ipynb` — the full comparison, target
  country selectable at the top
- `site/` — site sources and build tools (`build_data.py` bakes each
  country's GeoJSON + metadata under `docs/data/<ISO>/`, `protect.py`
  publishes the pages behind the country-selection landing page,
  `make_figures.py` + `build_deck.py` produce the WBG PowerPoints)
- `docs/` — the built site served by GitHub Pages

Data lives on Google Drive under `World Bank/Exposure Analytics`
(auto-detected; see `src/config.py`) — the repo holds code and the published
site only.

## Reproducing

```
pip install -r requirements.txt
py site/tools/build_data.py MAR COL MHL VEN     # per-country data (extractions cached)
py site/tools/protect.py                        # landing page (country dropdown) + pages into docs/
py site/tools/make_figures.py MAR COL MHL VEN   # deck figures -> site/figures/<ISO>/
py site/tools/build_deck.py MAR COL MHL VEN     # one WBG PowerPoint per country
```

First-time extractions (Overture S3 scan, GBA tiles, Microsoft quadkeys) take
minutes for a small country and an hour or more for a large one; they are
cached on the Drive.

### Adding a country

1. Add it under `countries:` in `config.yaml` — display name, the GEM
   v2023.1.1 folder, Microsoft's region name (or `[]` if Microsoft has no
   tiles there). Set `gar15: false` if GAR15's per-country release has no
   file for it (Venezuela), and `unit_names` where the WB layer carries an
   outdated or unaccented unit name.
2. Run `build_data.py <ISO>`. GEM regions are matched to the WB units by
   name; if the build stops on an unmatched region, add it to
   `gem_name_aliases`.
3. Re-run `protect.py` (the landing page lists every country with built
   data), then `make_figures.py` and `build_deck.py` for the deck.
4. Optional: give the deck its own cover. `build_deck.py` uses
   `site/deck/cover_<ISO>.png` when it exists and a neutral skyline
   otherwise; add a scene to `site/tools/make_covers.py` to draw one in
   the shared style.
5. Optional: link the deck to GRADE. The closing slide draws a GRADE
   exposure base (`grade:` under the country in `config.yaml` — as
   reported, buildings and contents, with its price year) against the
   models, converted to the same price year. Without one it compares
   other published values by unit (`benchmarks:`), or just shows the
   spread a GRADE would start from.

Two situations need more than configuration: a territory WB carries
separately (Morocco / Western Sahara, curated in `src/gem.py` and
`src/boundaries.py`), and a country WB carries as a single Admin-1 unit
(Marshall Islands — set `units:` to split the WB coastline into atolls).

A model a country lacks is left out everywhere — site, figures and deck —
and the country is compared on the models that remain: no Microsoft tiles
over the Marshall Islands, no GAR15 country file for Venezuela.

## License

**CC BY-NC-SA 4.0** (see [LICENSE](LICENSE)) — the repository adopts the most
restrictive terms of its underlying data: GEM's exposure model is
CC BY-NC-SA and GAR15 is non-commercial, so everything derived here is
share-alike and non-commercial too. Per-source licenses are listed in the
LICENSE file and on the site's About page.

## Acknowledgements

This work was supported by a AAAS Revelle Fellowship. Sources and licences
are documented on the site's About page — several datasets are
non-commercial (GAR15, GEM CC BY-NC-SA).
