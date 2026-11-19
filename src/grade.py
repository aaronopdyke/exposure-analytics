"""
Exposure Analytics - link to GRADE (Global Rapid Post-Disaster Damage
Estimation, World Bank).

A GRADE multiplies an exposure base by damage ratios, so the base it starts
from carries straight through to the damage estimate. `link()` puts a
country's GRADE exposure (config.yaml `countries.<ISO>.grade`, as reported:
buildings AND contents, US$ of the report year) on the footing of this
project's models - same price year, and a structures-only equivalent - and
computes every number the deck's GRADE slide and its chart state. Where no
GRADE exists, other published values (`benchmarks`) are compared by unit.

Used by site/tools/make_figures.py (chart) and build_deck.py (text) so the
two cannot disagree.
"""

import statistics

from src import deflate
from src.config import country

# model key -> (label, value column); deck order
MODELS = [
    ('gar15', 'GAR15', 'gar15_usd_adj'),
    ('giri', 'GIRI', 'giri_total_usd_adj'),
    ('gem2023', 'GEM v2023', 'gem23_bldg_repl_usd_adj'),
    ('gem2026', 'GEM v2026', 'gem26_bldg_repl_usd_adj'),
    ('overture', 'Overture', 'overture_value_usd_adj'),
    ('gba', 'GBA', 'gba_value_usd_adj'),
    ('msb', 'Microsoft', 'msb_value_usd_adj'),
]
FOOTPRINT = {'overture', 'gba', 'msb'}

# From "A Review of the GRADE Assessments 2015-2024" (World Bank / GFDRR,
# 2025): GRADE results as a percentage of the PDNA / DaLA for the same
# event, Table 8 (17 comparable events; the sector averages rest on the 15
# with a sector breakdown, and totals average 88%).
REVIEW = {
    'cite': 'GRADE review 2015-2024',
    'sector_events': 15,
    'total_vs_pdna': 0.88,             # average
    'residential_vs_pdna': 0.65,       # average
    'non_residential_vs_pdna': 1.51,   # average
    'vanuatu_vs_pdna': (0.36, 0.31),   # TC Harold 2020; TC Judy & Kevin 2023
}


def link(iso, meta, units):
    """Everything the GRADE slide states, for one country.

    meta: docs/data/<ISO>/meta.json; units: the unit table (adm1.geojson)."""
    cfg = country(iso)
    T = meta['totals']
    yr = meta['deflator']['target_year']
    present = [(k, lab, col) for k, lab, col in MODELS if k in meta['models']]
    vals = {lab: T[col] for _, lab, col in present}
    lo, hi = min(vals, key=vals.get), max(vals, key=vals.get)

    # spread inside a unit: Microsoft is left out (its coverage gaps are
    # reported on its own slide and would otherwise read as disagreement),
    # and only units holding >= 1% of the stock count
    cols = [col for k, _, col in present if k != 'msb']
    m = units[cols]
    share = (m / m.sum()).mean(axis=1)
    sp = (m.max(axis=1) / m.min(axis=1).where(m.min(axis=1) > 0))
    sp = sp[share >= 0.01].dropna()

    out = {
        'year': yr,
        'models': vals,
        'keys': {lab: k for k, lab, _ in present},
        'lo': lo, 'hi': hi,
        'spread': vals[hi] / vals[lo],
        'median': statistics.median(vals.values()),
        'unit_spread_median': float(sp.median()) if len(sp) else None,
        # GEM publishes contents beside structures: the only like-for-like
        # handle on what "buildings and contents" adds in this country
        'contents_ratio': T['gem26_contents_usd'] / T['gem26_bldg_repl_usd'],
        'nonres_share': {
            'GEM v2026': (T['gem26_com_usd'] + T['gem26_ind_usd'])
            / T['gem26_bldg_repl_usd'],
            'GIRI': T['giri_nres_usd'] / T['giri_total_usd'],
        },
        'floor_vs_gem': {lab: T[f'{k}_floor_area_m2'] / T['gem26_floor_area_m2']
                         for k, lab, _ in present if k in FOOTPRINT},
        'grade': None,
        'benchmarks': [],
    }

    gr = cfg.get('grade')
    if gr:
        f, extrapolated = deflate.price_factor(gr['price_year'])
        res, nres = gr['residential_usd'], gr['non_residential_usd']
        total = (res + nres) * f
        ex = total / (1 + out['contents_ratio'])
        cagr = meta['vintages']['value_growth']['trailing_cagr']
        stock_year = int(gr.get('stock_year', gr['price_year']))
        nearest = min(vals, key=lambda k: abs(vals[k] - ex))
        out['grade'] = {
            'event': gr['event'],
            'price_year': int(gr['price_year']),
            'stock_year': stock_year,
            'native_total': res + nres,
            'factor': f, 'extrapolated': extrapolated,
            'total': total, 'res': res * f, 'nres': nres * f,
            'nonres_share': nres / (res + nres),
            'ex_contents': ex,
            'vs_median': ex / out['median'] - 1,
            'vs': {lab: ex / v for lab, v in vals.items()},
            'nearest': nearest,
            'vs_nearest': ex / vals[nearest] - 1,
            # what growing GRADE's stock to the target year would do, along
            # the same path the vintage slide uses - not stated where that
            # path is shrinking (a collapsing GDP says little about the
            # building stock)
            'stock_growth': ((1 + cagr) ** (yr - stock_year) - 1
                             if cagr >= 0 else None),
        }

    name = units['name'].str.split(' (', regex=False).str[0]
    for b in cfg.get('benchmarks') or []:
        f, _ = deflate.price_factor(b.get('price_year', yr))
        places = []
        for p in b['places']:
            row = units[name == p['unit']]
            if row.empty:
                raise LookupError(f"{iso}: benchmark unit {p['unit']!r} is "
                                  'not a display unit')
            row = row.iloc[0]
            mv = {lab: float(row[col]) for _, lab, col in present}
            places.append({'name': p['name'], 'unit': p['unit'],
                           'usd': p['usd'] * f, 'models': mv,
                           'ratio': {lab: v / (p['usd'] * f)
                                     for lab, v in mv.items()}})
        out['benchmarks'].append({'source': b['source'], 'places': places})
    return out
