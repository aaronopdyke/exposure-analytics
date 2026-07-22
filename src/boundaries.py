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
"""

import os
import warnings

import geopandas as gpd
import pandas as pd

from src.config import CFG, COUNTRY_ISO, ADM0_PATH, ADM1_PATH, DISPLAY_CRS

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
