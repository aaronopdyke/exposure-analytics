"""
Exposure Analytics - boundaries with Western Sahara handled explicitly.

WB Official Boundaries draw Morocco ending at 27.67N; Western Sahara exists
ONLY as an ADM0 polygon (ISO ESH, WB_STATUS "Non-determined legal status
area") with no ADM1 subdivisions in the WB Admin-1 layer. Every map in this
repo must still show the full territory, so:

- `admin1(iso)` returns the WB ADM1 units for the country;
- when `iso` is 'MAR' (or 'ESH' is requested, or boundaries.include_esh is
  on), the ESH ADM0 polygon is APPENDED as one additional unit
  (ADM1CD_c 'ESH000'), labelled per config - shown whole, never subdivided,
  and never merged into a member state.

Countries the WB Admin-1 layer carries as a single unit (config
`countries.<ISO>.units`, e.g. the Marshall Islands) get atoll units instead:
see `_atoll_units`.
"""

import functools
import glob
import os
import warnings
import zipfile

import geopandas as gpd
import pandas as pd
import requests
import shapely

from src.config import (CFG, COUNTRIES, COUNTRY_ISO, ADM0_PATH, ADM1_PATH,
                        DISPLAY_CRS, SOURCE_DIR)
from src.util import download

_BCFG = dict(CFG.get('boundaries', {}))
ESH_LABEL = str(_BCFG.get('esh_label', 'Western Sahara'))
INCLUDE_ESH = bool(_BCFG.get('include_esh', True))


def _read_where(path, where):
    if not path or not os.path.exists(path):
        raise FileNotFoundError(
            f'Boundary GPKG not found ({path}). Is the Drive mounted and the '
            'Global Building Forecast project synced?')
    try:
        g = gpd.read_file(path, where=where, engine='pyogrio')
    except Exception:
        g = gpd.read_file(path)
        g = g.query(where.replace('=', '==')) if where else g
    return g


def _norm_names(g, level):
    key = f'NAME_{level}'
    if key not in g.columns:
        for c in (f'NAM_{level}', f'ADM{level}_NAME', 'shapeName'):
            if c in g.columns:
                g[key] = g[c]
                break
    return g


def admin0(iso=None):
    """WB ADM0 polygon(s) for a country (EPSG:4326)."""
    iso = iso or COUNTRY_ISO
    g = _read_where(ADM0_PATH, f"ISO_A3 = '{iso}'")
    if not len(g):
        raise ValueError(f'no ADM0 rows for {iso}')
    return _norm_names(g, 0).to_crs(DISPLAY_CRS)


def esh_admin0():
    """The Western Sahara ADM0 polygon (ESH) as a one-row GeoDataFrame."""
    g = _read_where(ADM0_PATH, "ISO_A3 = 'ESH'")
    if not len(g):
        warnings.warn('ESH polygon not found in the WB ADM0 layer.')
        return None
    return _norm_names(g, 0).to_crs(DISPLAY_CRS)


def admin1(iso=None, include_esh=None):
    """WB ADM1 units with guaranteed [ADM1CD_c, admin_name] (EPSG:4326).

    include_esh (default: config, and only when relevant) appends the ESH
    ADM0 polygon as ONE unit with ADM1CD_c 'ESH000'. Relevant = iso is MAR
    or ESH itself is requested.
    """
    iso = iso or COUNTRY_ISO
    include_esh = INCLUDE_ESH if include_esh is None else bool(include_esh)

    units = COUNTRIES.get(iso.upper(), {}).get('units')
    if units and units.get('kind') == 'atolls':
        return _atoll_units(iso.upper()).copy()

    if iso == 'ESH':
        g = esh_admin0()
        if g is None:
            raise ValueError('ESH polygon unavailable.')
        g = g.assign(ADM1CD_c='ESH000', admin_name=ESH_LABEL,
                     ISO_A3='ESH')
        return g[['ISO_A3', 'ADM1CD_c', 'admin_name', 'geometry']]

    g = _read_where(ADM1_PATH, f"ISO_A3 = '{iso}'")
    if not len(g):
        raise ValueError(f'no ADM1 rows for {iso}')
    g = _norm_names(g, 1).to_crs(DISPLAY_CRS)
    g['admin_name'] = g['NAME_1'].astype(str)
    # config `unit_names`: WB name -> current / correctly accented name
    names = dict(COUNTRIES.get(iso, {}).get('unit_names') or {})
    if names:
        g['admin_name'] = g['admin_name'].replace(names)
    if 'ADM1CD_c' not in g.columns:
        g['ADM1CD_c'] = [f'{iso}{i:03d}' for i in range(len(g))]
    out = g[['ISO_A3', 'ADM1CD_c', 'admin_name', 'geometry']]

    if include_esh and iso == 'MAR':
        e = esh_admin0()
        if e is not None:
            e = e.assign(ISO_A3='ESH', ADM1CD_c='ESH000', admin_name=ESH_LABEL)
            out = pd.concat(
                [out, e[['ISO_A3', 'ADM1CD_c', 'admin_name', 'geometry']]],
                ignore_index=True)
            out = gpd.GeoDataFrame(out, geometry='geometry', crs=DISPLAY_CRS)
    return out


def _cod_adm1(iso, hdx_id):
    """OCHA COD-AB Admin-1 polygons (atoll names) for a country, resolved
    through the HDX CKAN API and cached under Source Data/Boundaries_extra."""
    dest = os.path.join(SOURCE_DIR, 'Boundaries_extra',
                        f'cod_ab_{iso.lower()}')
    pattern = os.path.join(dest, '**', '*adm1*.shp')
    if not glob.glob(pattern, recursive=True):
        r = requests.get('https://data.humdata.org/api/3/action/package_show',
                         params={'id': hdx_id}, timeout=60)
        r.raise_for_status()
        url = next(x['url'] for x in r.json()['result']['resources']
                   if x['format'].upper() == 'SHP')
        zpath = download(url, os.path.join(dest, f'{iso.lower()}_shp.zip'))
        with zipfile.ZipFile(zpath) as z:
            z.extractall(dest)
    g = gpd.read_file(glob.glob(pattern, recursive=True)[0]).to_crs(DISPLAY_CRS)
    return g[['ADM1_EN', 'ADM1_PCODE', 'geometry']]


@functools.lru_cache(maxsize=None)
def _atoll_units(iso):
    """Atoll units for a country the WB Admin-1 layer carries as ONE unit.

    Every part of the WB polygon (the official coastline) is assigned to its
    nearest COD-AB atoll - which also folds the uninhabited atolls into the
    municipality that customarily administers them (Erikub -> Wotje, Ujelang
    -> Enewetak, Bikar/Bokak/Taka -> Utirik, ...). Each unit's geometry is the
    ENVELOPE of its islets (convex hull + buffer, lagoon included): islets a
    few hundred metres wide are invisible on a country map and would miss the
    5 km GAR15/GIRI cells and any building outside the generalised coast.
    The same envelope is used for display and for every zonal assignment.
    """
    cfg = COUNTRIES[iso]['units']
    wb = _read_where(ADM1_PATH, f"ISO_A3 = '{iso}'").to_crs(DISPLAY_CRS)
    parts = wb[['geometry']].explode(index_parts=False).reset_index(drop=True)
    cod = _cod_adm1(iso, cfg['hdx_id'])
    # nearest atoll in a local equidistant projection (Mollweide shears
    # distances this far from its central meridian)
    c = parts.union_all().centroid
    aeqd = f'+proj=aeqd +lat_0={c.y:.3f} +lon_0={c.x:.3f} +datum=WGS84'
    near = gpd.sjoin_nearest(parts.to_crs(aeqd),
                             cod[['ADM1_PCODE', 'geometry']].to_crs(aeqd))
    parts['ADM1_PCODE'] = near[~near.index.duplicated()]['ADM1_PCODE']
    buf = float(cfg.get('hull_buffer_deg', 0.04))
    rename = dict(cfg.get('rename', {}))
    rows = []
    link = float(cfg.get('cluster_link_deg', 0.12))
    for row in cod.sort_values('ADM1_PCODE').itertuples():
        islets = list(parts.loc[parts['ADM1_PCODE'] == row.ADM1_PCODE,
                                'geometry']) + list(
            getattr(row.geometry, 'geoms', [row.geometry]))
        # one envelope per atoll: islets chain into clusters when closer
        # than 2 x link, so a unit that also holds outlying atolls becomes a
        # multi-part unit instead of one hull spanning open ocean
        blobs = shapely.union_all([g.buffer(link) for g in islets])
        hull = shapely.union_all([
            shapely.union_all([g for g in islets if g.intersects(blob)])
            .convex_hull.buffer(buf)
            for blob in getattr(blobs, 'geoms', [blobs])])
        for prev in rows:                       # envelopes never overlap
            if hull.intersects(prev['geometry']):
                hull = hull.difference(prev['geometry'])
        rows.append({'ISO_A3': iso, 'ADM1CD_c': row.ADM1_PCODE,
                     'admin_name': rename.get(row.ADM1_EN, row.ADM1_EN),
                     'geometry': hull})
    return gpd.GeoDataFrame(rows, geometry='geometry', crs=DISPLAY_CRS)


def plot_admin1(gdf, title=None, ax=None, esh_hatch=True):
    """Reference map of the ADM1 units; ESH drawn hatched + labelled to make
    its non-determined status visually explicit."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(9, 9))
    main = gdf[gdf['ADM1CD_c'] != 'ESH000']
    esh = gdf[gdf['ADM1CD_c'] == 'ESH000']
    main.plot(ax=ax, facecolor='#e8eef4', edgecolor='#456', linewidth=0.8)
    if len(esh):
        esh.plot(ax=ax, facecolor='#f4efe4',
                 edgecolor='#997', linewidth=1.0,
                 hatch='//' if esh_hatch else None)
    for row in gdf.itertuples():
        c = row.geometry.representative_point()
        nm = row.admin_name.split('(')[0].strip()
        ax.annotate(nm, (c.x, c.y), ha='center', fontsize=7, color='#333')
    ax.set_title(title or 'Admin-1 units (Western Sahara shown whole, hatched)')
    ax.set_axis_off()
    return ax
