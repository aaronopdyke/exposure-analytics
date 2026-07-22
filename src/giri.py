"""
Exposure Analytics - GIRI Building Exposure Model (BEM) loader.

Source: UNEP/GRID-Geneva GIRI data server (the portal at
https://giri.unepgrid.ch fronts the same rasters). Direct GeoTIFFs:

    https://hazards-data.unepgrid.ch/bem_5x5_valfis.tif       (total)
    https://hazards-data.unepgrid.ch/bem_5x5_valfis_res.tif   (residential)
    https://hazards-data.unepgrid.ch/bem_5x5_valfis_nres.tif  (non-res)

Global EPSG:4326 grids at ~0.0417 deg (~5 km), float32, nodata -9999.
Cell values are the fiscal (replacement) value of the building stock in
USD. The three ~16 MB files are cached whole under Source Data/GIRI.
"""

import os

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from shapely.geometry import box

from src.config import SOURCE_DIR, CFG
from src.util import download

BASE_URL = 'https://hazards-data.unepgrid.ch/'
LAYERS = {'giri_total_usd': 'bem_5x5_valfis.tif',
          'giri_res_usd': 'bem_5x5_valfis_res.tif',
          'giri_nres_usd': 'bem_5x5_valfis_nres.tif'}
CACHE = os.path.join(SOURCE_DIR, CFG['sources']['giri']['cache_subdir'])


def fetch():
    """Ensure all three BEM rasters are cached locally; return paths."""
    return {k: download(BASE_URL + f, os.path.join(CACHE, f), 1 << 20)
            for k, f in LAYERS.items()}


def read_window(bounds, layer='giri_total_usd'):
    """(array, extent) of one BEM layer over (minx, miny, maxx, maxy);
    nodata -> NaN. extent is (left, right, bottom, top) for imshow."""
    path = fetch()[layer]
    with rasterio.open(path) as src:
        w = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
        a = src.read(1, window=w).astype('float64')
        a[a == src.nodata] = np.nan
        wb = src.window_bounds(w)
    return a, (wb[0], wb[2], wb[1], wb[3])


def load_cells(bounds):
    """BEM 5 km cells within bounds as polygon GeoDataFrame.

    Columns: giri_total_usd / giri_res_usd / giri_nres_usd + cell geometry.
    Cells where all layers are nodata/zero are dropped. Aggregate to ADM1
    with util.cells_to_adm1 (largest-overlap assignment) - do NOT use a
    nearest fallback: the grid is global and would leak neighbours in.
    """
    paths = fetch()
    arrays = {}
    with rasterio.open(paths['giri_total_usd']) as src:
        w = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
        transform = src.window_transform(w)
        nodata = src.nodata
        for k, p in paths.items():
            with rasterio.open(p) as s:
                a = s.read(1, window=w).astype('float64')
            a[a == nodata] = np.nan
            arrays[k] = a
    keep = np.zeros(arrays['giri_total_usd'].shape, dtype=bool)
    for a in arrays.values():
        keep |= np.nan_to_num(a) > 0
    rows, cols = np.nonzero(keep)
    xs, ys = rasterio.transform.xy(transform, rows, cols)  # cell centres
    rx, ry = transform.a / 2, -transform.e / 2
    geoms = [box(x - rx, y - ry, x + rx, y + ry) for x, y in zip(xs, ys)]
    data = {k: np.nan_to_num(a[rows, cols]) for k, a in arrays.items()}
    return gpd.GeoDataFrame(data, geometry=geoms, crs='EPSG:4326')
