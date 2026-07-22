# exposure-analytics

**How much is the built environment worth — and do the world's public
building-exposure datasets agree?** Anyone doing disaster-risk work has to
pick an exposure dataset, and the candidates disagree — for the same country,
by multiples. This project puts seven public datasets on a common footing
(one boundary standard, one price basis, one zonal methodology) so you can
see *how much* they disagree, *why*, and *which differences actually matter*
for your use case.

**Live site:** https://aaronopdyke.github.io/exposure-analytics/
· current build: **Morocco** · works per country, more coming.

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
  floor area). Spoiler for Morocco: it doesn't — gaps are method, not age.
- **Brief others.** A World Bank-branded PowerPoint (comparison first, then
  one slide per model, then assumptions/sensitivity) is built from the same
  data, and every number on it is reproducible from this repo.

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
  and even extreme storey-height rules move footprint totals only −8%/+29% —
  far too little to reorder the models. The conclusions are about method, not
  tuning.

Everything model-specific — vintages, price bases, boundary handling, the
UCC valuation, caveats per dataset — is documented on the site's About page.

## Layout

- `config.yaml` — country default, pinned source URLs, boundary policy
- `src/` — loaders and shared machinery: `boundaries.py` (WB ADM1 + Western
  Sahara policy), `gar15.py`, `giri.py`, `gem.py` (both releases),
  `buildings.py` (DuckDB extraction: Overture / GBA / Microsoft),
  `ucc.py` (unit construction costs), `deflate.py` (price-year and growth
  alignment), `util.py` (downloads + zonal aggregation)
- `notebooks/exposure_comparison.ipynb` — the full comparison, target
  country selectable at the top
- `site/` — site sources and build tools (`build_data.py` bakes the ADM1
  GeoJSON + metadata, `protect.py` wraps the explorer in the landing page,
  `make_figures.py` + `build_deck.py` produce the WBG PowerPoint)
- `docs/` — the built site served by GitHub Pages

Data lives on Google Drive under `World Bank/Exposure Analytics`
(auto-detected; see `src/config.py`) — the repo holds code and the published
site only.

## Reproducing

```
pip install -r requirements.txt
py site/tools/build_data.py MAR      # assemble ADM1 data (extractions cached)
py site/tools/protect.py             # landing page + pages into docs/
py site/tools/make_figures.py        # deck figures
py site/tools/build_deck.py          # WBG PowerPoint
```

First-time extractions (Overture S3 scan, GBA tiles, Microsoft quadkeys) take
minutes to tens of minutes per country and are cached on the Drive.

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
