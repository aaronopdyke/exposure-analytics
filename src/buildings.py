"""
Exposure Analytics - Overture Maps + Global Building Atlas extraction.

Adapted from the sibling global-building-forecast project
(src/extraction.py, src/diagnostics.py) - same DuckDB machinery, but
instead of sampled 1 km training cells the queries aggregate EVERY
building, grouped by (WB ADM1 unit x 1 km Mollweide grid cell). The grid
key lets Python classify each cell urban/rural against the GHSL DEGURBA
E2020 raster (urban = classes 21/22/23/30, i.e. cities + towns/suburbs;
everything else incl. water counts as rural) before collapsing to ADM1.

- Overture: pinned S3 release, bbox-struct prefilter + ST_Contains join.
  Floor area uses num_floors when present, else the height tiering below,
  else 1 storey (footprint = floor area).
- GBA LoD1: deterministic 5-degree tile names on source.coop, tiles cached
  locally. Height -> storeys via the forecast project's 3-tier divisor
  (h<18: 3.0, h<60: 3.25, else 3.5 m per storey); missing/<=0 heights are
  imputed at 3 m and counted in `missing_height`.

Both are physical exposure (counts, footprint m2, floor area m2) - no USD.
Results are cached as CSV under Outputs/, keyed by ISO3.
"""

import json
import math
import os
import time

import duckdb
import numpy as np
import pandas as pd
import requests

from src.config import CFG, GHSL_DIR, OUTPUTS_DIR, SOURCE_DIR, country
from src.util import ensure_dir

OVERTURE_URL = CFG['sources']['overture']['url']
GBA_HTTPS = CFG['sources']['gba']['base_url']
GBA_TILE_CACHE = os.path.join(SOURCE_DIR, 'GBA_tiles')
DEGURBA_TIF = os.path.join(
    GHSL_DIR or '', 'Urbanization',
    'GHS_WUP_DEGURBA_E2020_GLOBE_R2025A_54009_1000_V1_0.tif')

_HEIGHT = ("CASE WHEN try_cast(height AS DOUBLE) IS NULL OR "
           "try_cast(height AS DOUBLE) <= 0 THEN {} END")
_H_MISSING = _HEIGHT.format('1 ELSE 0')
_H_VALUE = _HEIGHT.format('3.0 ELSE try_cast(height AS DOUBLE)')
_DIVISOR = "CASE WHEN h < 18 THEN 3.0 WHEN h < 60 THEN 3.25 ELSE 3.5 END"
# Footprint area in m2. DuckDB's ST_Area_Spheroid reads coordinates as
# [latitude, longitude]; every source here stores [longitude, latitude], so
# the geometry is flipped first. Unflipped, the result is silently wrong by
# cos(lon)/cos(lat) - x1.18 around Casablanca, x0.28 around Bogota, NaN in
# the Pacific - which is why _connect verifies the convention on every run.
_AREA = "ST_Area_Spheroid(ST_FlipCoordinates({g}))"


def _check_area_convention(con):
    """Fail loudly if _AREA stops returning true geodesic areas (e.g. a
    DuckDB release changing the axis order ST_Area_Spheroid expects)."""
    from pyproj import Geod
    from shapely.geometry import box
    for x, y in ((-74.1, 4.6), (171.2, 7.1), (-7.6, 33.5)):
        sq = box(x, y, x + 0.0002, y + 0.0002)
        true = abs(Geod(ellps='WGS84').geometry_area_perimeter(sq)[0])
        got = con.execute(
            f"SELECT {_AREA.format(g='ST_GeomFromText(?)')}",
            [sq.wkt]).fetchone()[0]
        if got is None or not abs(got / true - 1) < 0.01:
            raise RuntimeError(
                f'footprint-area check failed at ({x}, {y}): DuckDB returned '
                f'{got} m2 for a {true:.1f} m2 square - ST_Area_Spheroid axis '
                'order has changed; fix buildings._AREA before extracting.')


def _subdivide(adm1, step=0.25):
    """Cut every unit into pieces along a `step`-degree grid. The pieces
    tile the unit exactly, so a centroid falls in the same unit either way,
    but each containment test now runs against a few dozen vertices instead
    of a whole department outline - about 70x faster on Colombia, where the
    undivided join took two hours per source."""
    import shapely
    rows = []
    for code, geom in zip(adm1['ADM1CD_c'], adm1.geometry.values):
        if not shapely.is_valid(geom):
            geom = shapely.make_valid(geom)
        shapely.prepare(geom)
        minx, miny, maxx, maxy = geom.bounds
        for i in range(math.floor(minx / step), math.floor(maxx / step) + 1):
            for j in range(math.floor(miny / step),
                           math.floor(maxy / step) + 1):
                cell = shapely.box(i * step, j * step,
                                   (i + 1) * step, (j + 1) * step)
                if not geom.intersects(cell):
                    continue
                if geom.contains(cell):
                    rows.append((code, cell))
                    continue
                for part in shapely.get_parts(geom.intersection(cell)):
                    if part.geom_type == 'Polygon' and not part.is_empty:
                        rows.append((code, part))
    pieces = pd.DataFrame(rows, columns=['ADM1CD_c', 'geom'])
    whole = float(shapely.area(adm1.geometry.values).sum())
    cut = float(shapely.area(pieces['geom'].values).sum())
    if not abs(cut / whole - 1) < 1e-9:
        raise RuntimeError(f'unit subdivision lost area ({cut / whole})')
    return pieces


def _connect(adm1):
    import shapely
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    con.execute("SET enable_progress_bar=false;")
    _check_area_convention(con)
    pieces = _subdivide(adm1)
    df = pd.DataFrame({'ADM1CD_c': pieces['ADM1CD_c'],
                       'wkb': list(shapely.to_wkb(pieces['geom'].values))})
    con.register('adm1_df', df)
    con.execute("CREATE TEMP TABLE adm1 AS "
                "SELECT ADM1CD_c, ST_GeomFromWKB(wkb) AS geom FROM adm1_df")
    return con


def _cached(path, force):
    if not force and os.path.exists(path) and os.path.getsize(path) > 10:
        return pd.read_csv(path)
    return None


def _classify_urban(grid_df):
    """True where the 1 km Mollweide cell (gx, gy) is DEGURBA-urban."""
    import rasterio
    if not os.path.exists(DEGURBA_TIF):
        raise FileNotFoundError(f'DEGURBA raster not found: {DEGURBA_TIF}')
    xs = (grid_df['gx'].to_numpy() + 0.5) * 1000.0
    ys = (grid_df['gy'].to_numpy() + 0.5) * 1000.0
    with rasterio.open(DEGURBA_TIF) as src:
        vals = np.fromiter(
            (v[0] for v in src.sample(zip(xs, ys))), dtype='float64',
            count=len(grid_df))
    return vals >= 21


def _collapse(grid, metrics):
    """(ADM1 x grid cell) frame -> per-ADM1 totals + urban/rural splits."""
    grid = grid.copy()
    grid['urban'] = _classify_urban(grid)
    out = grid.groupby('ADM1CD_c', as_index=False)[metrics].sum()
    for cls in ('urban', 'rural'):
        sub = grid[grid['urban'] == (cls == 'urban')]
        s = sub.groupby('ADM1CD_c')[metrics].sum()
        s.columns = [f'{c}_{cls}' for c in s.columns]
        out = out.merge(s.reset_index(), on='ADM1CD_c', how='left')
    return out.fillna(0.0)


def extract_overture(iso, adm1, force=False):
    """Per-ADM1 Overture count / footprint, with DEGURBA urban-rural
    splits. Floor area is split into floor_known_m2 (from num_floors or
    height where present, via the 3-tier storey divisor) and fp_unknown_m2
    (footprint of buildings with no usable attributes) - the caller
    estimates storeys for the unknown share (e.g. GBA-calibrated
    multipliers) instead of assuming one storey. One S3 scan over the
    country bbox (then cached)."""
    out_path = os.path.join(ensure_dir(OUTPUTS_DIR),
                            f'overture_adm1_{iso.lower()}.csv')
    hit = _cached(out_path, force)
    if hit is not None:
        return hit
    minx, miny, maxx, maxy = adm1.total_bounds
    con = _connect(adm1)
    q = f"""
        WITH b AS (
            SELECT ST_Centroid(geometry) AS c,
                   {_AREA.format(g='geometry')} AS area,
                   try_cast(num_floors AS DOUBLE) AS nf,
                   try_cast(height AS DOUBLE) AS ht
            FROM read_parquet('{OVERTURE_URL}', hive_partitioning=1)
            WHERE bbox.xmin <= {maxx} AND bbox.xmax >= {minx}
              AND bbox.ymin <= {maxy} AND bbox.ymax >= {miny}
        ),
        j AS (
            SELECT a.ADM1CD_c,
                   ST_Transform(b.c, 'EPSG:4326', 'ESRI:54009', always_xy := true) AS p,
                   b.area,
                   CASE
                       WHEN b.nf IS NOT NULL AND b.nf > 0 THEN b.area * b.nf
                       WHEN b.ht IS NOT NULL AND b.ht > 0 THEN b.area * b.ht /
                           (CASE WHEN b.ht < 18 THEN 3.0
                                 WHEN b.ht < 60 THEN 3.25 ELSE 3.5 END)
                       END AS floor_known,
                   CASE WHEN (b.nf IS NULL OR b.nf <= 0)
                             AND (b.ht IS NULL OR b.ht <= 0)
                        THEN b.area END AS fp_unknown
            FROM b JOIN adm1 AS a ON ST_Contains(a.geom, b.c)
        )
        SELECT ADM1CD_c,
               CAST(floor(ST_X(p) / 1000) AS INT) AS gx,
               CAST(floor(ST_Y(p) / 1000) AS INT) AS gy,
               count(*)         AS overture_buildings,
               sum(area)        AS overture_footprint_m2,
               sum(floor_known) AS overture_floor_known_m2,
               sum(fp_unknown)  AS overture_fp_unknown_m2
        FROM j GROUP BY 1, 2, 3
    """
    grid = con.execute(q).df()
    con.close()
    grid = grid.fillna(0.0)
    res = _collapse(grid,
                    ['overture_buildings', 'overture_footprint_m2',
                     'overture_floor_known_m2', 'overture_fp_unknown_m2'])
    res.to_csv(out_path, index=False)
    with open(_overture_sidecar(iso), 'w', encoding='utf-8') as f:
        json.dump({'release': _release_of(OVERTURE_URL)}, f)
    return res


def _release_of(url):
    return url.split('/release/')[1].split('/')[0]


def _overture_sidecar(iso):
    return os.path.join(OUTPUTS_DIR, f'overture_adm1_{iso.lower()}.json')


def overture_release(iso):
    """Overture release a country's cached extraction came from (releases
    rotate out of the bucket, so countries can differ). Caches that predate
    the sidecar are the config's `legacy_release`."""
    p = _overture_sidecar(iso)
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return json.load(f)['release']
    return str(CFG['sources']['overture'].get('legacy_release',
                                              _release_of(OVERTURE_URL)))


MSB_LINKS_URL = ('https://minedbuildings.z5.web.core.windows.net/'
                 'global-buildings/dataset-links.csv')
MSB_CACHE = os.path.join(SOURCE_DIR, 'Microsoft')


def msb_regions(iso):
    """Microsoft's "Location" name(s) per ISO3 (config.yaml). An empty list
    means the release has no tiles over the country (e.g. the Marshall
    Islands) and the model is dropped for it. dataset-links.csv has no
    Western Sahara region; ESH coverage rides on the Morocco partition."""
    return list(country(iso).get('msb_regions') or [])


def _fetch_msb(iso):
    """Download all Microsoft GlobalML quadkey files for a country's
    region(s) to the local cache; returns local paths."""
    from src.util import download
    links_path = os.path.join(ensure_dir(MSB_CACHE), 'dataset-links.csv')
    download(MSB_LINKS_URL, links_path, 1 << 10)
    links = pd.read_csv(links_path)
    links = links[links['Location'].isin(msb_regions(iso))]
    if not len(links):
        raise LookupError(f'no Microsoft GlobalML region for {iso}')
    paths = []
    for row in links.itertuples():
        dest = os.path.join(MSB_CACHE, f'{row.Location}_{row.QuadKey}.csv.gz')
        # some quadkeys hold only a handful of buildings -> tiny gz files
        paths.append(download(row.Url, dest, min_bytes=30, timeout=1800))
    return paths


def extract_msb(iso, adm1, force=False):
    """Per-ADM1 Microsoft GlobalML footprints with DEGURBA urban-rural
    splits. Unlike the VIDA repackaging, the native release carries a
    per-building `height` (metres, -1 when unmodelled): buildings with a
    height contribute floor_known_m2 via the 3-tier storey divisor;
    the rest accumulate fp_unknown_m2 for the caller's storey model."""
    out_path = os.path.join(ensure_dir(OUTPUTS_DIR),
                            f'msb_adm1_{iso.lower()}.csv')
    hit = _cached(out_path, force)
    if hit is not None:
        return hit
    con = _connect(adm1)
    parts = []
    for path in _fetch_msb(iso):
        q = f"""
            WITH b AS (
                SELECT ST_GeomFromGeoJSON(to_json(geometry)) AS g,
                       try_cast(properties.height AS DOUBLE) AS ht
                FROM read_json('{path.replace(os.sep, '/')}',
                               format='newline_delimited',
                               compression='gzip')
            ),
            j AS (
                SELECT a.ADM1CD_c,
                       ST_Transform(ST_Centroid(b.g), 'EPSG:4326',
                                    'ESRI:54009', always_xy := true) AS p,
                       {_AREA.format(g='b.g')} AS area,
                       b.ht
                FROM b JOIN adm1 AS a
                  ON ST_Contains(a.geom, ST_Centroid(b.g))
            )
            SELECT ADM1CD_c,
                   CAST(floor(ST_X(p) / 1000) AS INT) AS gx,
                   CAST(floor(ST_Y(p) / 1000) AS INT) AS gy,
                   count(*)  AS msb_buildings,
                   sum(area) AS msb_footprint_m2,
                   sum(CASE WHEN ht > 0 THEN area * ht /
                       (CASE WHEN ht < 18 THEN 3.0
                             WHEN ht < 60 THEN 3.25 ELSE 3.5 END) END)
                       AS msb_floor_known_m2,
                   sum(CASE WHEN ht IS NULL OR ht <= 0 THEN area END)
                       AS msb_fp_unknown_m2
            FROM j GROUP BY 1, 2, 3
        """
        parts.append(con.execute(q).df())
    con.close()
    grid = (pd.concat(parts).fillna(0.0)
            .groupby(['ADM1CD_c', 'gx', 'gy'], as_index=False).sum())
    res = _collapse(grid, ['msb_buildings', 'msb_footprint_m2',
                           'msb_floor_known_m2', 'msb_fp_unknown_m2'])
    res.to_csv(out_path, index=False)
    return res


def gba_tile_name(lon_idx, lat_idx, step=5):
    """source.coop GBA tile name for a 5-deg tile, e.g. w010_n35_w005_n30
    = (minLon, maxLat, maxLon, minLat)."""
    def flon(v):
        return f"{'e' if v >= 0 else 'w'}{abs(v):03d}"

    def flat(v):
        return f"{'n' if v >= 0 else 's'}{abs(v):02d}"

    min_lon, min_lat = lon_idx * step, lat_idx * step
    return (f"{flon(min_lon)}_{flat(min_lat + step)}_"
            f"{flon(min_lon + step)}_{flat(min_lat)}.parquet")


def gba_tiles_for_bounds(bounds, step=5):
    minx, miny, maxx, maxy = bounds
    names = []
    for lon_idx in range(math.floor(minx / step), math.floor(maxx / step) + 1):
        for lat_idx in range(math.floor(miny / step),
                             math.floor(maxy / step) + 1):
            names.append(gba_tile_name(lon_idx, lat_idx, step))
    return names


def _fetch_gba_tile(name, retries=4):
    """Download a GBA tile to the local cache; None ONLY on a definitive
    404 (ocean tiles are absent from the bucket). Transient probe failures
    must raise, not skip - a silently dropped land tile corrupts totals."""
    url = f'{GBA_HTTPS}/{name}'
    dest = os.path.join(ensure_dir(GBA_TILE_CACHE), name)
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return dest
    from src.util import download
    last = None
    for attempt in range(retries):
        try:
            head = requests.head(url, timeout=60, allow_redirects=True)
            if head.status_code == 404:
                return None
            if head.status_code == 200:
                return download(url, dest, min_bytes=1024, timeout=1800)
            last = f'HTTP {head.status_code}'
        except requests.RequestException as e:
            last = repr(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'GBA tile probe failed for {name}: {last}')


def extract_gba(iso, adm1, force=False):
    """Per-ADM1 GBA count / footprint / volume / floor area with DEGURBA
    urban-rural splits."""
    out_path = os.path.join(ensure_dir(OUTPUTS_DIR),
                            f'gba_adm1_{iso.lower()}.csv')
    hit = _cached(out_path, force)
    if hit is not None:
        return hit
    con = _connect(adm1)
    parts = []
    for name in gba_tiles_for_bounds(adm1.total_bounds):
        path = _fetch_gba_tile(name)
        if path is None:
            continue
        q = f"""
            WITH j AS (
                SELECT a.ADM1CD_c,
                       ST_Transform(b.c, 'EPSG:4326', 'ESRI:54009', always_xy := true) AS p,
                       b.area, b.h, b.missing
                FROM (
                    SELECT ST_Centroid(geometry)      AS c,
                           {_AREA.format(g='geometry')} AS area,
                           {_H_MISSING}               AS missing,
                           {_H_VALUE}                 AS h
                    FROM read_parquet('{path.replace(os.sep, '/')}')
                ) AS b
                JOIN adm1 AS a ON ST_Contains(a.geom, b.c)
            )
            SELECT ADM1CD_c,
                   CAST(floor(ST_X(p) / 1000) AS INT) AS gx,
                   CAST(floor(ST_Y(p) / 1000) AS INT) AS gy,
                   count(*)               AS gba_buildings,
                   sum(area)              AS gba_footprint_m2,
                   sum(area * h)          AS gba_volume_m3,
                   sum(area * h / ({_DIVISOR})) AS gba_floor_area_m2,
                   sum(area * greatest(1, floor(h / ({_DIVISOR}))))
                                          AS gba_floor_floor_m2,
                   sum(area * ceil(h / ({_DIVISOR})))
                                          AS gba_floor_ceil_m2,
                   sum(CASE WHEN h < 18 THEN area * h ELSE 0 END)
                                          AS gba_volume_t1_m3,
                   sum(CASE WHEN h >= 18 AND h < 60 THEN area * h ELSE 0 END)
                                          AS gba_volume_t2_m3,
                   sum(CASE WHEN h >= 60 THEN area * h ELSE 0 END)
                                          AS gba_volume_t3_m3,
                   sum(missing)           AS gba_missing_height
            FROM j GROUP BY 1, 2, 3
        """
        parts.append(con.execute(q).df())
    con.close()
    if not parts:
        raise RuntimeError(f'no GBA tiles found for {iso}')
    grid = (pd.concat(parts)
            .groupby(['ADM1CD_c', 'gx', 'gy'], as_index=False).sum())
    res = _collapse(grid,
                    ['gba_buildings', 'gba_footprint_m2', 'gba_volume_m3',
                     'gba_floor_area_m2', 'gba_floor_floor_m2',
                     'gba_floor_ceil_m2', 'gba_volume_t1_m3',
                     'gba_volume_t2_m3', 'gba_volume_t3_m3',
                     'gba_missing_height'])
    res.to_csv(out_path, index=False)
    return res
