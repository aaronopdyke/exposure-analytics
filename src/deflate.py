"""
Exposure Analytics - price-year alignment via the WDI US GDP deflator.

Each exposure model reports USD of a different base year (verified against
the source documentation this project cached):

- GAR15: 2005 US$  (WB CWON 2011 produced capital, "current (2005) capital
  stock of machinery and structures" per the GEG-15 metadata PDF)
- GIRI BEM: 2018 US$ (WB CWON 2021 produced capital, constant 2018 US$,
  per the BEM technical report)
- GEM v2023.1.1: 2021 US$ (Yepes-Estrada et al. 2023)
- GEM v2026.0.0 / UCC: 2024 US$ (release notes: replacement costs
  "updated to 2024-2025 values"; the UCC-database totals match v2026)

`factor(year)` converts those to the latest year available in the World
Bank WDI US GDP deflator (NY.GDP.DEFL.ZS, country USA). The series is
cached on the Drive so builds are reproducible offline.
"""

import json
import os

import requests

from src.config import SOURCE_DIR

WDI_URL = ('https://api.worldbank.org/v2/country/USA/indicator/'
           'NY.GDP.DEFL.ZS?format=json&per_page=100')
CACHE = os.path.join(SOURCE_DIR or '', 'WDI', 'us_gdp_deflator.json')

VALUE_YEARS = {'gar15': 2005, 'giri': 2018, 'gem2023': 2021,
               'gem2026': 2024, 'ucc': 2024}

# approximate DATA vintage (what year the physical stock reflects) - used by
# the vintage reconciliation, distinct from the price base above
VINTAGE_YEARS = {'gar15': 2011, 'giri': 2020, 'gem2023': 2023,
                 'gem2026': 2025, 'overture': 2025, 'gba': 2023,
                 'msb': 2024}

# growth bases for the vintage reconciliation (both data-driven):
# - VALUE: the WB Wealth Accounts produced-capital series (NW.PCA.TO, real
#   chained 2019 US$) - the very series GAR15/GIRI derive from, so growing
#   GAR15 along it and comparing to GIRI isolates method differences.
# - FLOOR AREA: GHSL Built-up Volume growth (physical proxy; capital growth
#   includes deepening/quality, which floor space does not).
#   Where the Wealth Accounts publish no produced capital for a country
#   (small island states, e.g. the Marshall Islands) the value path falls
#   back to WDI real GDP - a stable capital-output ratio makes GDP the
#   closest published proxy - and meta.json records which basis was used.
WDI_URL_T = ('https://api.worldbank.org/v2/country/{iso}/indicator/'
             '{ind}?format=json&per_page=100')
VALUE_BASES = {
    'produced_capital': {
        'indicator': 'NW.PCA.TO',
        'source': ('WB Wealth Accounts produced capital '
                   '(NW.PCA.TO, real chained 2019 US$)'),
        'short': 'WB produced capital (CWON)'},
    'real_gdp': {
        'indicator': 'NY.GDP.MKTP.KD',
        'source': ('WDI real GDP (NY.GDP.MKTP.KD, constant 2015 US$) - the '
                   'WB Wealth Accounts publish no produced capital for this '
                   'country, so GDP stands in for the capital path'),
        'short': 'real GDP (WDI; no produced-capital series published)'},
}
FALLBACK_CAPITAL_CAGR = 0.057   # MAR trailing-10y, verified 2026-07
FALLBACK_BUILTV_RATE = 0.015    # MAR GHS-BUILT-V 2010-2020 CAGR


def _growth_cache_path(iso):
    return os.path.join(SOURCE_DIR or '', 'WDI',
                        f'growth_{iso.lower()}.json')


def _growth_cache(iso):
    p = _growth_cache_path(iso)
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_growth_cache(iso, data):
    p = _growth_cache_path(iso)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _wdi_fetch(iso, indicator):
    """{year: value} for one WDI indicator; {} when the country simply has
    no observations (HTTP/parse errors raise - they must not be mistaken
    for 'not published')."""
    r = requests.get(WDI_URL_T.format(iso=iso, ind=indicator), timeout=60)
    r.raise_for_status()
    body = r.json()
    rows = (body[1] if len(body) > 1 else None) or []
    return {int(x['date']): float(x['value']) for x in rows
            if x['value'] is not None}


def value_series(iso):
    """(basis, {year: level}) of the series values are grown along:
    produced capital where the Wealth Accounts publish it, else real GDP.
    Cached per country (Source Data/WDI/growth_<iso>.json)."""
    cache = _growth_cache(iso)
    for basis in VALUE_BASES:
        if basis in cache:
            return basis, {int(k): v for k, v in cache[basis].items()}
    for basis, spec in VALUE_BASES.items():
        s = _wdi_fetch(iso, spec['indicator'])
        if s:
            cache[basis] = s
            _save_growth_cache(iso, cache)
            return basis, s
    raise LookupError(f'no produced-capital or real-GDP series for {iso}')


def value_basis(iso):
    """VALUE_BASES entry (+ 'basis' key) describing the country's value
    growth series; the fallback constant when nothing could be fetched."""
    try:
        basis = value_series(iso)[0]
    except Exception:
        return {'basis': 'fallback', 'indicator': None,
                'source': f'assumed {FALLBACK_CAPITAL_CAGR:.1%}/yr (no series)',
                'short': 'an assumed constant rate'}
    return dict(VALUE_BASES[basis], basis=basis)


def produced_capital_series(iso):
    """{year: level} of the value-growth series (produced capital, or the
    real-GDP stand-in - see value_series)."""
    return value_series(iso)[1]


def capital_cagr(iso, window=10):
    """Trailing-{window}-year CAGR of the value-growth series."""
    try:
        s = produced_capital_series(iso)
    except Exception:
        import warnings
        warnings.warn(f'NW.PCA.TO unavailable for {iso}; using fallback '
                      f'{FALLBACK_CAPITAL_CAGR:.1%}/yr')
        return FALLBACK_CAPITAL_CAGR
    last = max(s)
    first = max(min(s), last - window)
    return (s[last] / s[first]) ** (1 / (last - first)) - 1


def capital_growth_factor(iso, from_year, to_year):
    """K(to)/K(from) along the produced-capital path; years beyond the
    last observation extrapolate at the trailing-10y CAGR."""
    try:
        s = produced_capital_series(iso)
    except Exception:
        return (1 + FALLBACK_CAPITAL_CAGR) ** (to_year - from_year)
    g = capital_cagr(iso)
    last = max(s)

    def level(y):
        if y in s:
            return s[y]
        if y > last:
            return s[last] * (1 + g) ** (y - last)
        ys = sorted(s)
        lo = max(y0 for y0 in ys if y0 <= y)
        hi = min(y1 for y1 in ys if y1 >= y)
        w = (y - lo) / (hi - lo) if hi > lo else 0
        return s[lo] * (s[hi] / s[lo]) ** w

    return level(to_year) / level(from_year)


def builtv_growth_rate(iso, epochs=(2010, 2020)):
    """CAGR of GHSL Built-up Volume inside the country's units (cached).

    Masked to the unit polygons, not the bounding box: a bbox drags in the
    neighbours' cities (Caracas, Quito and Panama City all sit inside
    Colombia's)."""
    cache = _growth_cache(iso)
    key = f'builtv_cagr_{epochs[0]}_{epochs[1]}'
    if key in cache:
        return cache[key]
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask
        from src.config import GHSL_DIR
        from src.boundaries import admin1
        units = admin1(iso)
        tot = {}
        for y in epochs:
            p = os.path.join(
                GHSL_DIR, 'Volume_Total',
                f'GHS_BUILT_V_E{y}_GLOBE_R2023A_54009_1000_V1_0.tif')
            with rasterio.open(p) as src:
                shape = units.to_crs(src.crs).union_all()
                a, _ = mask(src, [shape], crop=True, indexes=1)
                a = a.astype('float64')
                if src.nodata is not None:
                    a[a == src.nodata] = 0
                tot[y] = float(a.sum())
        rate = (tot[epochs[1]] / tot[epochs[0]]) ** (
            1 / (epochs[1] - epochs[0])) - 1
    except Exception:
        import warnings
        warnings.warn(f'GHS-BUILT-V unavailable for {iso}; using fallback '
                      f'{FALLBACK_BUILTV_RATE:.1%}/yr')
        return FALLBACK_BUILTV_RATE
    cache[key] = rate
    _save_growth_cache(iso, cache)
    return rate


def floor_growth_factor(iso, from_year, to_year):
    """(1+g_builtv)^(to-from): physical floor-area growth."""
    return (1 + builtv_growth_rate(iso)) ** (to_year - from_year)

_series = None


def series(refresh=False):
    """{year: deflator} for the US (WDI NY.GDP.DEFL.ZS), cached."""
    global _series
    if _series is not None and not refresh:
        return _series
    if not refresh and os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f:
            _series = {int(k): v for k, v in json.load(f).items()}
        return _series
    r = requests.get(WDI_URL, timeout=60)
    r.raise_for_status()
    rows = r.json()[1]
    _series = {int(x['date']): float(x['value'])
               for x in rows if x['value'] is not None}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(_series, f)
    return _series


def target_year():
    return max(series())


def factor(year):
    """Multiplier taking {year} US$ to latest-year US$."""
    s = series()
    return s[target_year()] / s[int(year)]


def price_factor(year):
    """(multiplier, extrapolated) taking {year} US$ to latest-year US$.

    Unlike `factor`, accepts a year AFTER the last published deflator (a
    report priced in the current year): those are extrapolated at the
    latest annual rate, and the flag says so."""
    s = series()
    last, year = target_year(), int(year)
    if year <= last:
        return factor(year), False
    rate = s[last] / s[last - 1]
    return rate ** (last - year), True


def model_factors():
    """{model: {'year': base_year, 'factor': to-target multiplier}}."""
    return {m: {'year': y, 'factor': round(factor(y), 4)}
            for m, y in VALUE_YEARS.items()}
