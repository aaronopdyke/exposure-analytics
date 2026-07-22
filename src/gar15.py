"""
Exposure Analytics - GAR15 Global Exposure Dataset (GEG-15) loader.

Source: UNISDR GAR 2015 per-country shapefiles on the Humanitarian Data
Exchange (HDX), resolved by ISO3 through the CKAN API, e.g. Morocco:
https://data.humdata.org/dataset/gar15-global-exposure-dataset-for-morocco

Each row is a grid-cell point (~5 km, 1 km on the coast) with population
proxies and capital value by sector/income class. Monetary columns are in
MILLIONS of 2015 USD; `tot_val` = tot_cu + tot_cr (urban + rural capital).

WB boundaries carry Western Sahara separately (ISO ESH), so for MAR the
companion ESH dataset is fetched and appended when include_esh is on.
"""

import glob
import os
import zipfile

import geopandas as gpd
import pandas as pd
import requests

from src.config import SOURCE_DIR, CFG
from src.util import download, ensure_dir

HDX_API = 'https://data.humdata.org/api/3/action/package_search'
CACHE = os.path.join(SOURCE_DIR, CFG['sources']['gar15']['cache_subdir'])

VALUE_COL = 'tot_val'          # total capital stock, millions USD (2015)
POP_COL = 'tot_pob'


def hdx_resource_url(iso):
    """Find the GAR15 shapefile-zip download URL for an ISO3 on HDX."""
    r = requests.get(HDX_API, params={
        'q': 'name:gar15-global-exposure-dataset*',
        'fq': f'groups:{iso.lower()}', 'rows': 5}, timeout=60)
    r.raise_for_status()
    results = r.json()['result']['results']
    if not results:
        raise LookupError(f'no GAR15 dataset on HDX for {iso}')
    res = results[0]['resources'][0]
    return res['url']


def fetch(iso):
    """Download + unzip the GAR15 shapefile for iso; return the gdf."""
    iso = iso.upper()
    zpath = os.path.join(CACHE, f'{iso.lower()}.zip')
    if not os.path.exists(zpath):
        download(hdx_resource_url(iso), zpath)
    xdir = os.path.join(CACHE, iso.lower())
    if not glob.glob(os.path.join(xdir, '**', '*.shp'), recursive=True):
        ensure_dir(xdir)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(xdir)
    shp = glob.glob(os.path.join(xdir, '**', '*.shp'), recursive=True)[0]
    g = gpd.read_file(shp)
    if g.crs is None:
        g = g.set_crs('EPSG:4326')
    return g.to_crs('EPSG:4326')


def load(iso, include_esh=False):
    """GAR15 point cells for a country (+ ESH appended for MAR).

    Adds `gar15_usd` = tot_val * 1e6 (absolute 2015 USD).
    """
    parts = [fetch(iso)]
    if include_esh and iso.upper() == 'MAR':
        try:
            parts.append(fetch('ESH'))
        except Exception as e:                      # pragma: no cover
            import warnings
            warnings.warn(f'GAR15 ESH fetch failed: {e}')
    g = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
    g = gpd.GeoDataFrame(g, geometry='geometry', crs='EPSG:4326')
    g['gar15_usd'] = g[VALUE_COL] * 1e6
    g['gar15_urban_usd'] = g['tot_cu'] * 1e6   # urban capital
    g['gar15_rural_usd'] = g['tot_cr'] * 1e6   # rural capital
    return g
