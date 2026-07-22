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
PC_URL = ('https://api.worldbank.org/v2/country/{iso}/indicator/'
          'NW.PCA.TO?format=json&per_page=100')
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


def produced_capital_series(iso):
    """{year: produced capital} (NW.PCA.TO, real chained 2019 US$)."""
    cache = _growth_cache(iso)
    if 'produced_capital' in cache:
        return {int(k): v for k, v in cache['produced_capital'].items()}
    r = requests.get(PC_URL.format(iso=iso), timeout=60)
    r.raise_for_status()
    rows = r.json()[1] or []
    s = {int(x['date']): float(x['value']) for x in rows
         if x['value'] is not None}
    if not s:
        raise LookupError(f'no NW.PCA.TO data for {iso}')
    cache['produced_capital'] = s
    _save_growth_cache(iso, cache)
    return s


def capital_cagr(iso, window=10):
    """Trailing-{window}-year CAGR of real produced capital."""
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
    """CAGR of GHSL Built-up Volume over the country bbox (cached)."""
    cache = _growth_cache(iso)
    key = f'builtv_cagr_{epochs[0]}_{epochs[1]}'
    if key in cache:
        return cache[key]
    try:
        import numpy as np
        import rasterio
        from rasterio.windows import from_bounds
        from rasterio.warp import transform_bounds
        from src.config import GHSL_DIR
        from src.boundaries import admin1
        b4326 = tuple(admin1(iso).total_bounds)
        tot = {}
        for y in epochs:
            p = os.path.join(
                GHSL_DIR, 'Volume_Total',
                f'GHS_BUILT_V_E{y}_GLOBE_R2023A_54009_1000_V1_0.tif')
            with rasterio.open(p) as src:
                b = transform_bounds('EPSG:4326', src.crs, *b4326)
                a = src.read(1, window=from_bounds(*b, src.transform))
                if src.nodata is not None:
                    a = np.where(a == src.nodata, 0, a)
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


def model_factors():
    """{model: {'year': base_year, 'factor': to-target multiplier}}."""
    return {m: {'year': y, 'factor': round(factor(y), 4)}
            for m, y in VALUE_YEARS.items()}
