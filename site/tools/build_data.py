"""Build the site's static data from the exposure-analytics loaders.

Reads the cached extractions (Drive Outputs/) plus the fast loaders,
assembles one wide per-ADM1 table, and writes:

  docs/data/MAR/adm1.geojson   (simplified WB ADM1 + all metrics)
  docs/data/MAR/meta.json      (model/column registry + country totals)

and copies site/assets/* into docs/assets/. Run AFTER the Overture, GBA
and Microsoft extractions have been cached (they are not triggered from
here so a site rebuild can never kick off an hour-long scan by accident).

Seven models: GAR15, GIRI, GEM v2023.1.1, GEM v2026.0.0, Overture, GBA,
Microsoft GlobalML.

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

Usage:  py site/tools/build_data.py  [ISO3=MAR]
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
from src import buildings, deflate, gar15, gem, giri, ucc, util  # noqa: E402

GAR_COLS = ['gar15_usd', 'gar15_urban_usd', 'gar15_rural_usd']
GIRI_COLS = ['giri_total_usd', 'giri_res_usd', 'giri_nres_usd']
FOOTPRINT_MODELS = ['overture', 'gba', 'msb']   # get UCC-estimated values
DOCS_LINKS = {
    'gar15': 'https://www.preventionweb.net/english/hyogo/gar/2015/en/bgdocs/risk-section/De%20Bono,%20Andrea,%20Bruno%20Chatenoux.%202015.%20A%20Global%20Exposure%20Model%20for%20GAR%202015,%20%20UNEP-GRID.pdf',
    'giri': 'https://giri.unepgrid.ch/sites/default/files/2023-09/GIRI_BEM_report_UNIGE.pdf',
    'gem2023': 'https://doi.org/10.1177/87552930231194048',
    'gem2026': 'https://github.com/gem/global_exposure_model/releases/tag/v2026.0.0',
    'overture': 'https://docs.overturemaps.org/guides/buildings/',
    'gba': 'https://essd.copernicus.org/articles/17/6647/2025/essd-17-6647-2025.html',
    'msb': 'https://github.com/microsoft/GlobalMLBuildingFootprints',
}


def _models(iso):
    est = ('Replacement value ESTIMATED as floor area x GEM-derived unit '
           'construction cost per ADM1 (2024 US$, excl. contents).')
    storey = ('floor area = reported heights where present + GBA-calibrated '
              'storey multipliers (GBA floor/footprint ratio per ADM1 and '
              'urban/rural class) for the rest')
    xwalk = ("GEM regions matched to WB Admin-1 boundaries; GEM's two "
             'southern regions are assigned to the WB Western Sahara unit')
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
            'label': 'Overture Maps', 'vintage': '2026-06 release',
            'estimated_value': True,
            'note': ('Mapped footprints (OSM, Microsoft, Google); '
                     f'{storey}. {est}')},
        'gba': {
            'label': 'Global Building Atlas LoD1', 'vintage': '~2024',
            'estimated_value': True,
            'note': ('Footprints + modelled heights (TUM LoD1); floor area '
                     'via the 3-tier storey divisor; missing heights = 1 '
                     f'storey. Calibrates the other footprint sources. {est}')},
        'msb': {
            'label': 'Microsoft Buildings', 'vintage': '2026-02 release',
            'estimated_value': True,
            'note': ('Native Microsoft GlobalML footprints. Coverage is '
                     f'PARTIAL in {iso} - several interior regions (e.g. '
                     'Souss-Massa, Beni Mellal-Khenifra) have no tiles, so '
                     'totals undercount. The height field is unmodelled '
                     f'(-1) here, so {storey}. {est}')},
    }
    for p in FOOTPRINT_MODELS:
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
        m[p]['docs'] = DOCS_LINKS[p]
    for k, url in DOCS_LINKS.items():
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


def _sensitivity(wide, rate, adj):
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
        for p in ('overture', 'msb'):
            floors[p] = (wide[f'{p}_floor_known_m2']
                         + wide[f'{p}_fp_unknown_m2'] * mult)
        out[key] = {'label': label, 'models': {
            p: {'floor_m2': float(f.sum()),
                'value_usd_adj': float((f * rate).sum() * adj)}
            for p, f in floors.items()}}
    return out


def build(iso='MAR'):
    adm1 = admin1(iso)
    include_esh = (adm1['ADM1CD_c'] == 'ESH000').any()

    print('GAR15 ...')
    g15 = gar15.load(iso, include_esh=include_esh)
    wide = util.points_to_adm1(g15, adm1, GAR_COLS, nearest_max_deg=0.1)

    print('GIRI ...')
    cells = giri.load_cells(tuple(adm1.total_bounds))
    wide = wide.merge(
        util.cells_to_adm1(cells, adm1, GIRI_COLS)
        .drop(columns='geometry')[['ADM1CD_c'] + GIRI_COLS], on='ADM1CD_c')

    print('GEM v2023.1.1 + v2026.0.0 ...')
    wide = wide.merge(gem.adm1_totals_2023(gem.load_2023(iso), iso),
                      on='ADM1CD_c', how='left')
    wide = wide.merge(gem.adm1_totals(gem.load(iso), iso),
                      on='ADM1CD_c', how='left')

    print('Overture + GBA + Microsoft (cached extractions) ...')
    for fn in (buildings.extract_overture, buildings.extract_gba,
               buildings.extract_msb):
        wide = wide.merge(fn(iso, adm1), on='ADM1CD_c', how='left')

    num0 = [c for c in wide.columns
            if c != 'geometry' and wide[c].dtype.kind in 'if']
    wide[num0] = wide[num0].fillna(0.0)

    print('GBA-calibrated storeys + UCC values + deflator ...')
    for p in ('overture', 'msb'):
        wide = _estimate_floor(wide, p)
    u = ucc.adm1_ucc(iso, list(wide['ADM1CD_c']))
    rate = wide['ADM1CD_c'].map(u)
    for p in FOOTPRINT_MODELS:
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
    meta = {
        'iso': iso,
        'country': 'Morocco (Western Sahara shown as one separate unit)',
        'generated': datetime.date.today().isoformat(),
        'deflator': {'target_year': deflate.target_year(),
                     'source': 'WDI NY.GDP.DEFL.ZS (USA)',
                     'adj_suffix': '_adj',
                     'models': deflate.model_factors()},
        'vintages': {
            'years': deflate.VINTAGE_YEARS,
            'value_growth': {
                'source': ('WB Wealth Accounts produced capital '
                           '(NW.PCA.TO, real chained 2019 US$)'),
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
            wide, rate, deflate.factor(deflate.VALUE_YEARS['ucc'])),
        'models': _models(iso),
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

    yr = deflate.target_year()
    print(f'wrote {out_dir} (geojson '
          f'{os.path.getsize(os.path.join(out_dir, "adm1.geojson")) // 1024} '
          f'kB) + assets')
    for label, col in [('GAR15', 'gar15_usd'), ('GIRI', 'giri_total_usd'),
                       ('GEM23', 'gem23_bldg_repl_usd'),
                       ('GEM26', 'gem26_bldg_repl_usd'),
                       ('Ovtr*', 'overture_value_usd'),
                       ('GBA*', 'gba_value_usd'),
                       ('MSB*', 'msb_value_usd')]:
        print(f'{label:6s} {totals[col] / 1e9:7.1f} B$ nominal | '
              f'{totals[col + "_adj"] / 1e9:7.1f} B$ ({yr})')


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else 'MAR')
