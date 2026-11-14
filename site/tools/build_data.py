"""Build the site's static data from the exposure-analytics loaders.

Reads the cached extractions (Drive Outputs/) plus the fast loaders,
assembles one wide per-unit table, and writes, per country:

  docs/data/<ISO>/adm1.geojson   (simplified display units + all metrics)
  docs/data/<ISO>/meta.json      (model/column registry + country totals)
  docs/data/countries.json       (index of every country built so far)

and copies site/assets/* into docs/assets/. The first build of a country
runs its Overture / GBA / Microsoft extractions (minutes to an hour or
more); afterwards they are read from the Drive cache.

Seven models: GAR15, GIRI, GEM v2023.1.1, GEM v2026.0.0, Overture, GBA,
Microsoft GlobalML (dropped where Microsoft publishes no tiles).
Countries are configured in config.yaml (`countries:`).

Floor areas for Overture/Microsoft: reported num_floors/height where
present (floor_known) + a GBA-CALIBRATED storey multiplier for the rest -
multiplier = GBA floor/footprint ratio per ADM1 x urban/rural class (GBA
is the one footprint source with modelled heights). No more 1-storey
assumption.

Value handling: nominal USD columns keep each model's native price year
(GAR15 2005, GIRI 2018, GEM-2023 2021, GEM-2026/UCC 2024); every
``*_usd*`` column gets an ``_adj`` sibling in constant latest-year US$
(WDI US GDP deflator). Overture/GBA/Microsoft values are ESTIMATED as
floor area x GEM-derived ADM1 UCC (src/ucc.py; excludes contents,
consistent with GAR15/GIRI which are structures-only).

Usage:  py site/tools/build_data.py  [ISO3 ...]     (default: config country)
"""

import datetime
import json
import os
import shutil
import sys

import shapely

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(SITE)        # site/ lives inside exposure-analytics
DOCS = os.path.join(REPO, 'docs')   # GitHub Pages root
sys.path.insert(0, REPO)

from src.boundaries import admin1                             # noqa: E402
from src.config import COUNTRY_ISO, country                   # noqa: E402
from src import buildings, deflate, gar15, gem, giri, ucc, util  # noqa: E402

GAR_COLS = ['gar15_usd', 'gar15_urban_usd', 'gar15_rural_usd']
GIRI_COLS = ['giri_total_usd', 'giri_res_usd', 'giri_nres_usd']
FOOTPRINT_MODELS = ['overture', 'gba', 'msb']   # get UCC-estimated values
DOCS_LINKS = {
    'gar15': 'https://www.preventionweb.net/english/hyogo/gar/2015/en/bgdocs/risk-section/De%20Bono,%20Andrea,%20Bruno%20Chatenoux.%202015.%20A%20Global%20Exposure%20Model%20for%20GAR%202015,%20%20UNEP-GRID.pdf',
    'giri': 'https://giri.unepgrid.ch/sites/default/files/2023-09/GIRI_BEM_report_UNIGE.pdf',
    'gem2023': 'https://onlinelibrary.wiley.com/doi/10.1177/87552930231194048',
    'gem2026': 'https://github.com/gem/global_exposure_model/releases/tag/v2026.0.0',
    'overture': 'https://docs.overturemaps.org/guides/buildings/',
    'gba': 'https://essd.copernicus.org/articles/17/6647/2025/essd-17-6647-2025.html',
    'msb': 'https://github.com/microsoft/GlobalMLBuildingFootprints',
}


def _coverage(wide, names, has_msb):
    """Data-driven coverage facts for the footprint sources: the share of
    footprint carrying a usable height/floors attribute, and (Microsoft)
    the units where the release has little or no data relative to GBA."""
    cov = {}
    for p in ['overture'] + (['msb'] if has_msb else []):
        fp = wide[f'{p}_footprint_m2'].sum()
        cov[p] = {'attr_share': round(
            float(1 - wide[f'{p}_fp_unknown_m2'].sum() / fp) if fp else 0.0, 4)}
    cov['gba'] = {'missing_height_share': round(float(
        wide['gba_missing_height'].sum() / max(wide['gba_buildings'].sum(), 1)),
        4)}
    if has_msb:
        # Judged on footprint AREA, not building count: Microsoft draws
        # adjoining buildings as one polygon, so dense cities carry a
        # fraction of GBA's count while covering nearly the same area
        # (Bogota: 15% of the count, 87% of the footprint).
        ratio = wide['msb_footprint_m2'] / wide['gba_footprint_m2'].where(
            wide['gba_footprint_m2'] > 0)
        sparse = wide.loc[(ratio < 0.25) & (wide['gba_buildings'] > 1000),
                          'ADM1CD_c']
        cov['msb']['sparse_units'] = [names[c] for c in sparse]
        cov['msb']['vs_gba_buildings'] = round(float(
            wide['msb_buildings'].sum() / max(wide['gba_buildings'].sum(), 1)),
            3)
        cov['msb']['vs_gba_footprint'] = round(float(
            wide['msb_footprint_m2'].sum()
            / max(wide['gba_footprint_m2'].sum(), 1)), 3)
    return cov


def _attr_phrase(share):
    if share < 0.005:
        return 'essentially never populated'
    if share < 0.25:
        return f'populated for only {share:.0%} of footprint area'
    return f'populated for {share:.0%} of footprint area'


def _models(iso, cov, has_msb, gem_split, overture_release):
    cc = country(iso)
    est = ('Replacement value ESTIMATED as floor area x GEM-derived unit '
           'construction cost per unit (2024 US$, excl. contents).')
    storey = ('floor area = reported heights where present + GBA-calibrated '
              'storey multipliers (GBA floor/footprint ratio per unit and '
              'urban/rural class) for the rest')
    xwalk = str(dict(cc.get('notes') or {}).get(
        'gem', 'GEM regions matched to the display units by region name'))
    m = {
        'gar15': {
            'label': 'GAR15 (UNISDR)', 'vintage': '2015 (2005 US$)',
            'value': {'total': 'gar15_usd', 'urban': 'gar15_urban_usd',
                      'rural': 'gar15_rural_usd'},
            'floor': None,
            'breakdown': {'value': [['gar15_urban_usd', 'urban'],
                                    ['gar15_rural_usd', 'rural']]},
            'note': ('Capital stock of buildings (structures, no contents), '
                     'top-down from WB produced capital. Native urban/rural '
                     'split.')},
        'giri': {
            'label': 'GIRI BEM (UNEP/GRID)', 'vintage': '~2023 (2018 US$)',
            'value': {'total': 'giri_total_usd'},
            'sub': {'res': 'giri_res_usd', 'nres': 'giri_nres_usd'},
            'floor': None,
            'breakdown': {'value': [['giri_res_usd', 'residential'],
                                    ['giri_nres_usd', 'non-res']]},
            'note': ('Capital stock of buildings (structures, no contents), 5 km '
                     'cells assigned by largest overlap. Residential / '
                     'non-residential layers; no urban/rural split.')},
        'gem2023': {
            'label': 'GEM v2023.1.1', 'vintage': '2023 (2021 US$)',
            'value': {'total': 'gem23_bldg_repl_usd'},
            'floor': {'total': 'gem23_floor_area_m2'},
            'breakdown': {'value': [['gem23_res_usd', 'residential'],
                                    ['gem23_com_usd', 'commercial'],
                                    ['gem23_ind_usd', 'industrial']],
                          'floor': [['gem23_res_floor_m2', 'residential'],
                                    ['gem23_com_floor_m2', 'commercial'],
                                    ['gem23_ind_floor_m2', 'industrial']]},
            'note': ('June 2023 GEM release: building replacement cost '
                     '(structural + non-structural, excl. contents). '
                     f'{xwalk}. No urban/rural split in this release.')},
        'gem2026': {
            'label': 'GEM v2026.0.0',
            'vintage': '2026 (2024 US$)',
            'value': {'total': 'gem26_bldg_repl_usd',
                      'urban': 'gem26_res_urban_usd',
                      'rural': 'gem26_res_rural_usd'},
            'floor': {'total': 'gem26_floor_area_m2',
                      'urban': 'gem26_res_urban_floor_m2',
                      'rural': 'gem26_res_rural_floor_m2'},
            'split_note': 'urban/rural covers RESIDENTIAL only',
            'breakdown': {'value': [['gem26_res_usd', 'residential'],
                                    ['gem26_com_usd', 'commercial'],
                                    ['gem26_ind_usd', 'industrial']],
                          'floor': [['gem26_res_floor_m2', 'residential'],
                                    ['gem26_com_floor_m2', 'commercial'],
                                    ['gem26_ind_floor_m2', 'industrial']]},
            'note': ('June 2026 GEM release: building replacement cost '
                     '(structural + non-structural, excl. contents; costs '
                     f're-based to 2024-25). {xwalk}. Urban/rural published '
                     'for residential only.')},
        'overture': {
            'label': 'Overture Maps',
            'vintage': f'{overture_release[:7]} release',
            'estimated_value': True,
            'note': ('Mapped footprints (OSM, Microsoft, Google); height / '
                     'floors attributes are '
                     f"{_attr_phrase(cov['overture']['attr_share'])}; "
                     f'{storey}. {est}')},
        'gba': {
            'label': 'Global Building Atlas LoD1', 'vintage': '~2024',
            'estimated_value': True,
            'note': ('Footprints + modelled heights (TUM LoD1); floor area '
                     'via the 3-tier storey divisor; missing heights = 1 '
                     f'storey. Calibrates the other footprint sources. {est}')},
    }
    if has_msb:
        sparse = cov['msb']['sparse_units']
        partial = ('Coverage is PARTIAL - little or no data in '
                   f"{', '.join(sparse[:4])}"
                   f"{' and others' if len(sparse) > 4 else ''}, so totals "
                   'undercount. ') if sparse else ''
        m['msb'] = {
            'label': 'Microsoft Buildings', 'vintage': '2026-02 release',
            'estimated_value': True,
            'note': (f'Native Microsoft GlobalML footprints. {partial}'
                     'The height field is '
                     f"{_attr_phrase(cov['msb']['attr_share'])}; {storey}. "
                     f'{est}')}
    if not gem_split:
        # this country's v2026 rows carry no URBAN/RURAL settlement tags
        g26 = m['gem2026']
        for k in ('value', 'floor'):
            g26[k] = {'total': g26[k]['total']}
        g26.pop('split_note')
        g26['note'] = g26['note'].replace(
            ' Urban/rural published for residential only.',
            ' No urban/rural split published for this country.')
    for p in [p for p in FOOTPRINT_MODELS if p in m]:
        m[p]['value'] = {c: f'{p}_value_usd{s}' for c, s in
                         [('total', ''), ('urban', '_urban'),
                          ('rural', '_rural')]}
        m[p]['floor'] = {c: f'{p}_floor_area_m2{s}' for c, s in
                         [('total', ''), ('urban', '_urban'),
                          ('rural', '_rural')]}
        m[p]['extra'] = {'buildings': f'{p}_buildings',
                         'footprint': f'{p}_footprint_m2'}
        m[p]['breakdown'] = {
            'value': [[f'{p}_value_usd_urban', 'urban'],
                      [f'{p}_value_usd_rural', 'rural']],
            'floor': [[f'{p}_floor_area_m2_urban', 'urban'],
                      [f'{p}_floor_area_m2_rural', 'rural']]}
    for k, url in DOCS_LINKS.items():
        if k in m:
            m[k]['docs'] = url
    return m


def _adj_factor_for(col):
    """Deflator multiplier for a nominal USD column, by model prefix."""
    if col.startswith('gar15'):
        return deflate.factor(deflate.VALUE_YEARS['gar15'])
    if col.startswith('giri'):
        return deflate.factor(deflate.VALUE_YEARS['giri'])
    if col.startswith('gem23'):
        return deflate.factor(deflate.VALUE_YEARS['gem2023'])
    if col.startswith('gem26'):
        return deflate.factor(deflate.VALUE_YEARS['gem2026'])
    # UCC-estimated values (overture/gba/msb) are 2024 US$
    return deflate.factor(deflate.VALUE_YEARS['ucc'])


def _estimate_floor(wide, prefix):
    """floor_known + fp_unknown x GBA storey multiplier, per class."""
    for s in ('', '_urban', '_rural'):
        fp = wide[f'gba_footprint_m2{s}']
        mult = (wide[f'gba_floor_area_m2{s}'] / fp.where(fp > 0)).fillna(
            wide['gba_floor_area_m2'].sum() / wide['gba_footprint_m2'].sum())
        wide[f'{prefix}_floor_area_m2{s}'] = (
            wide[f'{prefix}_floor_known_m2{s}']
            + wide[f'{prefix}_fp_unknown_m2{s}'] * mult)
    return wide


_SCENARIOS = {
    'baseline': 'continuous h / divisor (published)',
    'floor': 'integer storeys, rounded down (min 1)',
    'ceil': 'integer storeys, rounded up',
    'div_minus': 'storey divisor -0.25 m',
    'div_plus': 'storey divisor +0.25 m',
}


def _sensitivity(wide, rate, adj, has_msb=True):
    """Country totals for the footprint models under alternative storey
    rules. GBA is recomputed per building (floor/ceil) or per height tier
    (divisor shifts); Overture/Microsoft reuse the GBA multiplier
    calibration with the scenario's floor areas. The reported-attribute
    share (floor_known, a few % of footprint) is held fixed."""
    def gba_floor(key):
        if key == 'baseline':
            return wide['gba_floor_area_m2']
        if key == 'floor':
            return wide['gba_floor_floor_m2']
        if key == 'ceil':
            return wide['gba_floor_ceil_m2']
        d = -0.25 if key == 'div_minus' else 0.25
        return (wide['gba_volume_t1_m3'] / (3.0 + d)
                + wide['gba_volume_t2_m3'] / (3.25 + d)
                + wide['gba_volume_t3_m3'] / (3.5 + d))

    out = {}
    for key, label in _SCENARIOS.items():
        g = gba_floor(key)
        fp = wide['gba_footprint_m2']
        mult = (g / fp.where(fp > 0)).fillna(g.sum() / fp.sum())
        floors = {'gba': g}
        for p in ['overture'] + (['msb'] if has_msb else []):
            floors[p] = (wide[f'{p}_floor_known_m2']
                         + wide[f'{p}_fp_unknown_m2'] * mult)
        out[key] = {'label': label, 'models': {
            p: {'floor_m2': float(f.sum()),
                'value_usd_adj': float((f * rate).sum() * adj)}
            for p, f in floors.items()}}
    return out


def _unit_info(iso, adm1):
    """How this country's display units relate to WB Admin-1."""
    units = country(iso).get('units')
    if units and units.get('kind') == 'atolls':
        return {'kind': 'atolls', 'count': len(adm1), 'noun': 'atoll',
                'label': 'atolls: WB coastline split by SPC/OCHA atoll names',
                'note': ('WB Official Boundaries carry this country as a '
                         'single Admin-1 unit, so the WB polygon is split '
                         'into atolls using the SPC / OCHA COD-AB atoll '
                         'names. Each atoll is drawn - and every dataset '
                         'aggregated - as an envelope around its islets '
                         '(lagoon included); uninhabited atolls belong to '
                         'the nearest municipality.')}
    return {'kind': 'adm1', 'count': len(adm1), 'noun': 'region',
            'label': 'WB Admin-1 units', 'note': None}


def write_country_index():
    """docs/data/countries.json - the countries with built data, for the
    landing page picker and the explorer's country switcher."""
    root = os.path.join(DOCS, 'data')
    rows = []
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d, 'meta.json')
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                m = json.load(f)
            rows.append({'iso': m['iso'],
                         'name': (m.get('name')
                                  or m['country'].split(' (')[0]),
                         'generated': m['generated']})
    rows.sort(key=lambda r: r['name'])
    with open(os.path.join(root, 'countries.json'), 'w',
              encoding='utf-8') as f:
        json.dump(rows, f, indent=1)
    return rows


def build(iso='MAR'):
    iso = iso.upper()
    cc = country(iso)
    adm1 = admin1(iso)
    include_esh = (adm1['ADM1CD_c'] == 'ESH000').any()
    has_msb = bool(buildings.msb_regions(iso))
    footprint = [p for p in FOOTPRINT_MODELS if p != 'msb' or has_msb]

    print('GAR15 ...')
    g15 = gar15.load(iso, include_esh=include_esh)
    wide = util.points_to_adm1(g15, adm1, GAR_COLS, nearest_max_deg=0.1)
    print(f"  assigned {wide['gar15_usd'].sum() / g15['gar15_usd'].sum():.1%}"
          ' of the country file')

    print('GIRI ...')
    cells = giri.load_cells(tuple(adm1.total_bounds))
    wide = wide.merge(
        util.cells_to_adm1(cells, adm1, GIRI_COLS)
        .drop(columns='geometry')[['ADM1CD_c'] + GIRI_COLS], on='ADM1CD_c')

    print('GEM v2023.1.1 + v2026.0.0 ...')
    g26 = gem.load(iso)
    wide = wide.merge(gem.adm1_totals_2023(gem.load_2023(iso), iso),
                      on='ADM1CD_c', how='left')
    wide = wide.merge(gem.adm1_totals(g26, iso), on='ADM1CD_c', how='left')
    gem_split = bool(g26['SETTLEMENT'].isin(['URBAN', 'RURAL']).any())

    print('Overture + GBA' + (' + Microsoft' if has_msb else '')
          + ' (cached extractions) ...')
    fns = [buildings.extract_overture, buildings.extract_gba]
    if has_msb:
        fns.append(buildings.extract_msb)
    for fn in fns:
        wide = wide.merge(fn(iso, adm1), on='ADM1CD_c', how='left')

    num0 = [c for c in wide.columns
            if c != 'geometry' and wide[c].dtype.kind in 'if']
    wide[num0] = wide[num0].fillna(0.0)
    names = dict(zip(wide['ADM1CD_c'],
                     wide['admin_name'].str.split(' (', regex=False).str[0]))
    cov = _coverage(wide, names, has_msb)

    print('GBA-calibrated storeys + UCC values + deflator ...')
    for p in [p for p in ('overture', 'msb') if p in footprint]:
        wide = _estimate_floor(wide, p)
    u = ucc.adm1_ucc(iso, list(wide['ADM1CD_c']))
    rate = wide['ADM1CD_c'].map(u)
    for p in footprint:
        for s in ('', '_urban', '_rural'):
            wide[f'{p}_value_usd{s}'] = wide[f'{p}_floor_area_m2{s}'] * rate

    num_cols = [c for c in wide.columns
                if c not in ('geometry',) and wide[c].dtype.kind in 'if']
    wide[num_cols] = wide[num_cols].fillna(0.0)

    usd_cols = [c for c in num_cols if '_usd' in c]
    for c in usd_cols:
        wide[f'{c}_adj'] = wide[c] * _adj_factor_for(c)
    num_cols += [f'{c}_adj' for c in usd_cols]

    # ---- geojson (simplified for the web) ----
    out_dir = os.path.join(DOCS, 'data', iso)
    os.makedirs(out_dir, exist_ok=True)
    g = wide.copy()
    g['geometry'] = shapely.set_precision(
        g.geometry.simplify(0.01, preserve_topology=True).values, 1e-4)
    g['esh'] = g['ADM1CD_c'] == 'ESH000'
    g = g.rename(columns={'ADM1CD_c': 'code', 'admin_name': 'name'})
    g[num_cols] = g[num_cols].round(0)
    keep = ['code', 'name', 'esh'] + num_cols + ['geometry']
    g[keep].to_file(os.path.join(out_dir, 'adm1.geojson'), driver='GeoJSON')

    # ---- meta.json ----
    totals = {c: float(wide[c].sum()) for c in num_cols}
    basis = deflate.value_basis(iso)
    units = _unit_info(iso, adm1)
    notes = [str(n) for n in (dict(cc.get('notes') or {}).get('site') or [])]
    if units['note']:
        notes.append(units['note'])
    if not has_msb:
        notes.append('Microsoft GlobalML Building Footprints publish no '
                     'tiles over this country, so six models are compared '
                     'here instead of seven.')
    if basis['basis'] != 'produced_capital':
        notes.append('The WB Wealth Accounts publish no produced-capital '
                     'series for this country; the vintage adjustment grows '
                     f"values along {basis['short'].split(' (')[0]} instead.")
    if not gem_split:
        notes.append('GEM v2026 publishes no urban/rural split for this '
                     'country.')
    meta = {
        'iso': iso,
        'name': cc['name'],
        'country': cc.get('label', cc['name']),
        'units': units,
        'notes': notes,
        'coverage': cov,
        'generated': datetime.date.today().isoformat(),
        'deflator': {'target_year': deflate.target_year(),
                     'source': 'WDI NY.GDP.DEFL.ZS (USA)',
                     'adj_suffix': '_adj',
                     'models': deflate.model_factors()},
        'vintages': {
            'years': deflate.VINTAGE_YEARS,
            'value_growth': {
                'source': basis['source'],
                'basis': basis['basis'],
                'short': basis['short'],
                'trailing_cagr': round(deflate.capital_cagr(iso), 4),
                'factors': {m: round(deflate.capital_growth_factor(
                    iso, y, deflate.target_year()), 3)
                    for m, y in deflate.VINTAGE_YEARS.items()}},
            'floor_growth': {
                'source': 'GHSL Built-up Volume 2010-2020',
                'rate': round(deflate.builtv_growth_rate(iso), 4),
                'factors': {m: round(deflate.floor_growth_factor(
                    iso, y, deflate.target_year()), 3)
                    for m, y in deflate.VINTAGE_YEARS.items()}}},
        'ucc': {'source': ('UCC-database (GEM-derived, 2024 US$), '
                           'ADM1 TOTAL occupancy'),
                'per_adm1_usd_m2': {k: round(v, 1) for k, v in u.items()}},
        'sensitivity': _sensitivity(
            wide, rate, deflate.factor(deflate.VALUE_YEARS['ucc']), has_msb),
        'models': _models(iso, cov, has_msb, gem_split,
                          buildings.overture_release(iso)),
        'totals': totals,
    }
    with open(os.path.join(out_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=1)

    # ---- assets ----
    a_src = os.path.join(SITE, 'assets')
    a_dst = os.path.join(DOCS, 'assets')
    os.makedirs(a_dst, exist_ok=True)
    for fn in os.listdir(a_src):
        shutil.copy2(os.path.join(a_src, fn), os.path.join(a_dst, fn))

    index = write_country_index()

    yr = deflate.target_year()
    print(f'wrote {out_dir} (geojson '
          f'{os.path.getsize(os.path.join(out_dir, "adm1.geojson")) // 1024} '
          f'kB) + assets; countries.json = {[r["iso"] for r in index]}')
    for label, col in [('GAR15', 'gar15_usd'), ('GIRI', 'giri_total_usd'),
                       ('GEM23', 'gem23_bldg_repl_usd'),
                       ('GEM26', 'gem26_bldg_repl_usd'),
                       ('Ovtr*', 'overture_value_usd'),
                       ('GBA*', 'gba_value_usd'),
                       ('MSB*', 'msb_value_usd')]:
        if col in totals:
            print(f'{label:6s} {totals[col] / 1e9:8.2f} B$ nominal | '
                  f'{totals[col + "_adj"] / 1e9:8.2f} B$ ({yr})')


if __name__ == '__main__':
    for _iso in (sys.argv[1:] or [COUNTRY_ISO]):
        build(_iso)
