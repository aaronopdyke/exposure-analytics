"""
Exposure Analytics - GEM Global Exposure Model loaders (two releases).

- v2026.0.0 (June 2026 release): global ADM1 x taxonomy summary CSV;
  replacement costs in 2024-25 US$; ID_1 codes follow ISO-3166-2 (MA-01..).
  https://github.com/gem/global_exposure_model/releases/tag/v2026.0.0
- v2023.1.1 (June 2023 release): per-country Exposure_Summary_Adm1.csv;
  costs in 2021 US$ (Yepes-Estrada et al. 2023); GADM-style ID_1 codes and
  NO settlement (urban/rural) split - reconciled to WB ADM1 by normalised
  region NAME instead of codes.
  https://github.com/gem/global_exposure_model/releases/tag/2023.1.1

Monetary columns are USD. "Building replacement" = structural +
non-structural, EXCLUDING contents (consistent with GAR15/GIRI, which are
structures-only). GEM covers Western Sahara within its Morocco model in
both releases; the two southern regions map to the WB unit ESH000.
"""

import os
import unicodedata

import pandas as pd

from src.config import SOURCE_DIR, CFG
from src.util import download

RAW = 'https://raw.githubusercontent.com/gem/global_exposure_model'
URL_2026 = f'{RAW}/v2026.0.0/World/summaries/Exposure_Summary_Adm1_Taxonomy.csv'
URL_2023 = {'MAR': f'{RAW}/2023.1.1/Africa/Morocco/Exposure_Summary_Adm1.csv'}
CACHE_DIR = os.path.join(SOURCE_DIR, CFG['sources']['gem']['cache_subdir'])


def load(iso):
    """GEM v2026 summary rows for one ISO3.

    SETTLEMENT usage varies by occupancy (e.g. MAR: RES rows come as
    URBAN/RURAL, COM/IND as TOTAL), so the double-counting guard is per
    occupancy: keep TOTAL rows where an occupancy has them, else all rows.
    """
    cache = os.path.join(CACHE_DIR, 'Exposure_Summary_Adm1_Taxonomy.csv')
    download(URL_2026, cache, 1 << 20)
    df = pd.read_csv(cache, low_memory=False)
    df = df[df['ID_0'] == iso.upper()].copy()
    keep = []
    for _, grp in df.groupby('OCCUPANCY'):
        has_total = (grp['SETTLEMENT'] == 'TOTAL').any()
        keep.append(grp[grp['SETTLEMENT'] == 'TOTAL'] if has_total else grp)
    return pd.concat(keep) if keep else df


def load_2023(iso):
    """GEM v2023.1.1 per-country ADM1 summary (ADM1 x occupancy rows)."""
    url = URL_2023[iso.upper()]
    cache = os.path.join(CACHE_DIR, f'{iso.lower()}_adm1_2023.1.1.csv')
    download(url, cache, 1 << 10)
    # NB: the published 2023 CSVs carry literal U+FFFD replacement chars
    # where accents were lost upstream; the name crosswalk includes those
    # degraded spellings explicitly
    df = pd.read_csv(cache)
    df['BLDG_REPL_COST_USD'] = (df['COST_STRUCTURAL_USD']
                                + df['COST_NONSTRUCTURAL_USD'])
    return df


def totals(df):
    """Country totals for a v2026 frame as a dict (USD, m2, counts)."""
    res = df[df['OCCUPANCY'] == 'RES']
    urb = res[res['SETTLEMENT'] == 'URBAN']
    rur = res[res['SETTLEMENT'] == 'RURAL']
    return {
        'gem_buildings': df['BUILDINGS'].sum(),
        'gem_floor_area_m2': df['TOTAL_AREA_SQM'].sum(),
        'gem_bldg_repl_usd': df['BLDG_REPL_COST_USD'].sum(),
        'gem_contents_usd': df['COST_CONTENTS_USD'].sum(),
        'gem_total_repl_usd': df['TOTAL_REPL_COST_USD'].sum(),
        'gem_res_urban_usd': urb['BLDG_REPL_COST_USD'].sum(),
        'gem_res_rural_usd': rur['BLDG_REPL_COST_USD'].sum(),
        'gem_res_urban_floor_m2': urb['TOTAL_AREA_SQM'].sum(),
        'gem_res_rural_floor_m2': rur['TOTAL_AREA_SQM'].sum(),
    }


# GEM ID_1 -> WB ADM1CD_c crosswalk (v2026 ISO-3166-2 codes). GEM models
# the full 12 official Moroccan regions; WB stops Morocco at 27.67N
# (keeping only a sliver of Laayoune-Sakia al Hamra as MAR007, no Dakhla at
# all) and carries Western Sahara as the single unit ESH000. GEM's two
# southern regions are assigned wholly to ESH000 - their exposure
# (Laayoune, Dakhla cities) lies south of the WB line - so the WB MAR007
# sliver shows no GEM value by construction.
WB_CROSSWALK = {
    'MAR': {
        'MA-01': 'MAR011',  # Tangier-Tetouan-Al Hoceima
        'MA-02': 'MAR006',  # Al-Sharq / L'oriental
        'MA-03': 'MAR004',  # Fes-Meknes
        'MA-04': 'MAR009',  # Rabat-Sale-Kenitra
        'MA-05': 'MAR001',  # Beni Mellal-Khenifra
        'MA-06': 'MAR002',  # Casablanca-Settat
        'MA-07': 'MAR008',  # Marrakech-Safi
        'MA-08': 'MAR003',  # Draa-Tafilalet
        'MA-09': 'MAR010',  # Souss-Massa
        'MA-10': 'MAR005',  # Guelmim-Oued Noun
        'MA-11': 'ESH000',  # Laayoune-Sakia El Hamra -> Western Sahara
        'MA-12': 'ESH000',  # Dakhla-Oued Ed-Dahab   -> Western Sahara
    },
}

# v2023 has GADM-style ID_1 codes, so it reconciles by normalised NAME_1
NAME_CROSSWALK = {
    'MAR': {
        'tangertetouanalhoceima': 'MAR011',
        'tangiertetouanalhoceima': 'MAR011',
        'fezmeknes': 'MAR004',
        'oriental': 'MAR006',
        'loriental': 'MAR006',
        'fesmeknes': 'MAR004',
        'rabatsalekenitra': 'MAR009',
        'benimellalkhenifra': 'MAR001',
        'casablancasettat': 'MAR002',
        'marrakechsafi': 'MAR008',
        'draatafilalet': 'MAR003',
        'soussmassa': 'MAR010',
        'guelmimouednoun': 'MAR005',
        'laayounesakiaelhamra': 'ESH000',
        # degraded spellings as published in the v2023 file (lost accents)
        'bnimellalkhnifra': 'MAR001',
        'dratafilalet': 'MAR003',
        'layounesakiaelhamra': 'ESH000',
        'rabatsalkenitra': 'MAR009',
        'dakhlaoueddahab': 'ESH000',
        'dakhlaoueeddahab': 'ESH000',
        'dakhlaouededdahab': 'ESH000',
    },
}


def _norm(name):
    s = unicodedata.normalize('NFKD', str(name))
    return ''.join(c for c in s if c.isalpha()).lower()


def adm1_totals(df, iso, prefix='gem26'):
    """Per-WB-ADM1 metrics for a v2026 frame via the ID_1 crosswalk."""
    xw = WB_CROSSWALK.get(iso.upper())
    if xw is None:
        raise LookupError(f'no GEM->WB ADM1 crosswalk curated for {iso}')
    unmapped = sorted(set(df['ID_1']) - set(xw))
    if unmapped:
        raise LookupError(f'GEM units missing from {iso} crosswalk: {unmapped}')
    d = df.assign(ADM1CD_c=df['ID_1'].map(xw))
    res = d['OCCUPANCY'] == 'RES'
    com = d['OCCUPANCY'] == 'COM'
    ind = d['OCCUPANCY'] == 'IND'
    urb = d['SETTLEMENT'] == 'URBAN'
    rur = d['SETTLEMENT'] == 'RURAL'
    p = prefix
    out = pd.DataFrame({
        f'{p}_buildings': d.groupby('ADM1CD_c')['BUILDINGS'].sum(),
        f'{p}_floor_area_m2': d.groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
        f'{p}_bldg_repl_usd':
            d.groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_contents_usd':
            d.groupby('ADM1CD_c')['COST_CONTENTS_USD'].sum(),
        f'{p}_res_urban_usd':
            d[res & urb].groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_res_rural_usd':
            d[res & rur].groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_res_urban_floor_m2':
            d[res & urb].groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
        f'{p}_res_rural_floor_m2':
            d[res & rur].groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
        f'{p}_res_usd':
            d[res].groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_com_usd':
            d[com].groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_ind_usd':
            d[ind].groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_res_floor_m2':
            d[res].groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
        f'{p}_com_floor_m2':
            d[com].groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
        f'{p}_ind_floor_m2':
            d[ind].groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
    }).fillna(0.0).reset_index()
    return out


def adm1_totals_2023(df, iso, prefix='gem23'):
    """Per-WB-ADM1 metrics for a v2023.1.1 frame (name crosswalk, no
    urban/rural split - GEM 2023 publishes none)."""
    xw = NAME_CROSSWALK.get(iso.upper())
    if xw is None:
        raise LookupError(f'no GEM-2023 name crosswalk curated for {iso}')
    d = df.assign(ADM1CD_c=df['NAME_1'].map(lambda n: xw.get(_norm(n))))
    unmapped = sorted(d.loc[d['ADM1CD_c'].isna(), 'NAME_1'].unique())
    if unmapped:
        raise LookupError(f'GEM-2023 names missing from {iso} crosswalk: '
                          f'{unmapped}')
    occ = {k: d['OCCUPANCY'].str.upper() == k for k in ('RES', 'COM', 'IND')}
    p = prefix
    out = pd.DataFrame({
        f'{p}_buildings': d.groupby('ADM1CD_c')['BUILDINGS'].sum(),
        f'{p}_floor_area_m2': d.groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
        f'{p}_bldg_repl_usd':
            d.groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_res_usd':
            d[occ['RES']].groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_com_usd':
            d[occ['COM']].groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_ind_usd':
            d[occ['IND']].groupby('ADM1CD_c')['BLDG_REPL_COST_USD'].sum(),
        f'{p}_res_floor_m2':
            d[occ['RES']].groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
        f'{p}_com_floor_m2':
            d[occ['COM']].groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
        f'{p}_ind_floor_m2':
            d[occ['IND']].groupby('ADM1CD_c')['TOTAL_AREA_SQM'].sum(),
    }).fillna(0.0).reset_index()
    return out
