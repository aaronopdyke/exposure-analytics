"""
Exposure Analytics - shared helpers: cached downloads and ADM1 aggregation.

All zonal aggregation funnels through the same two functions so every source
(GAR15 points, GIRI cells, Overture/GBA buildings) is assigned to the SAME
WB ADM1 units the same way, keeping totals comparable across datasets.
"""

import os

import geopandas as gpd
import pandas as pd
import requests


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def download(url, dest, min_bytes=1024, timeout=300):
    """Stream url -> dest (atomic; skipped if dest already looks valid)."""
    if os.path.exists(dest) and os.path.getsize(dest) >= min_bytes:
        return dest
    ensure_dir(os.path.dirname(dest))
    tmp = dest + '.tmp'
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(tmp, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    if os.path.getsize(tmp) < min_bytes:
        os.remove(tmp)
        raise IOError(f'download too small: {url}')
    os.replace(tmp, dest)
    return dest


def points_to_adm1(points, adm1, value_cols, nearest_max_deg=None):
    """Sum value_cols of a point GeoDataFrame per ADM1 unit.

    Points are matched 'within'; when nearest_max_deg is set, unmatched
    points (e.g. 1 km coastal GAR15 cells whose centres sit offshore) are
    recovered with a bounded nearest join. Only use the fallback for
    country-specific datasets - for global grids it would suck in
    neighbouring countries' cells.
    Returns adm1 with value_cols added (NaN-free, 0 for empty units).
    """
    pts = points.to_crs(adm1.crs)
    j = gpd.sjoin(pts, adm1[['ADM1CD_c', 'geometry']],
                  how='left', predicate='within')
    if nearest_max_deg:
        miss = j['ADM1CD_c'].isna()
        if miss.any():
            near = gpd.sjoin_nearest(
                pts.loc[miss.values, points.geometry.name].to_frame(),
                adm1[['ADM1CD_c', 'geometry']],
                how='left', max_distance=nearest_max_deg)
            near = near[~near.index.duplicated(keep='first')]
            j.loc[miss, 'ADM1CD_c'] = near['ADM1CD_c']
    sums = j.groupby('ADM1CD_c')[value_cols].sum()
    out = adm1.merge(sums, on='ADM1CD_c', how='left')
    out[value_cols] = out[value_cols].fillna(0.0)
    return out


def cells_to_adm1(cells, adm1, value_cols):
    """Sum value_cols of a polygon-cell GeoDataFrame per ADM1 unit.

    Each cell goes WHOLLY to the ADM1 unit it overlaps most (largest
    intersection area), so coastal cells are kept and border cells are not
    double counted. Suitable for coarse global grids (GIRI 5 km cells).
    """
    cells = cells.to_crs(adm1.crs).reset_index(drop=True)
    j = gpd.sjoin(cells, adm1[['ADM1CD_c', 'geometry']],
                  how='inner', predicate='intersects')
    dup = j.index[j.index.duplicated(keep=False)].unique()
    if len(dup):
        adm_geom = adm1.set_index('ADM1CD_c').geometry
        sub = j.loc[dup]
        ov = [row.geometry.intersection(adm_geom[row.ADM1CD_c]).area
              for row in sub.itertuples()]
        sub = sub.assign(_ov=ov).sort_values('_ov')
        keep = sub[~sub.index.duplicated(keep='last')].drop(columns='_ov')
        j = pd.concat([j.drop(index=dup), keep])
    sums = j.groupby('ADM1CD_c')[value_cols].sum()
    out = adm1.merge(sums, on='ADM1CD_c', how='left')
    out[value_cols] = out[value_cols].fillna(0.0)
    return out
