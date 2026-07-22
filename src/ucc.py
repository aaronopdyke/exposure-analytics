"""
Exposure Analytics - GEM-derived unit construction costs (UCC, USD/m2).

Source: the UCC-database compilation (github.com/aaronopdyke/ucc-database),
which extracts UCC = BLDG_REPL_COST_USD / TOTAL_AREA_SQM (structural +
non-structural, EXCLUDING contents; 2021 US$) from the GEM Global Exposure
Model per country x admin-1 x occupancy. Used here to put an estimated USD
value on the footprint datasets (Overture, GBA, VIDA):

    estimated value = floor area x ADM1 TOTAL UCC

GEM ID_1 codes map to WB ADM1 via gem.WB_CROSSWALK; ESH000 gets the
area-weighted UCC of GEM's two southern regions; units with no GEM row
(e.g. the WB MAR007 sliver) fall back to the national TOTAL UCC.
"""

import os

import pandas as pd

from src.gem import WB_CROSSWALK

LOCAL_CSV = r'c:\Users\aaron\repos\UCC-database\data\ucc_adm1.csv'
RAW_URL = ('https://raw.githubusercontent.com/aaronopdyke/ucc-database/'
           'main/data/ucc_adm1.csv')


def _load(iso):
    src = LOCAL_CSV if os.path.exists(LOCAL_CSV) else RAW_URL
    df = pd.read_csv(src)
    df = df[(df['ID_0'] == iso.upper()) & (df['OCCUPANCY'] == 'TOTAL')]
    if not len(df):
        raise LookupError(f'no UCC rows for {iso}')
    return df


def adm1_ucc(iso, adm1_codes):
    """UCC (USD/m2, 2021 US$) per WB ADM1CD_c as a Series over adm1_codes."""
    df = _load(iso)
    xw = WB_CROSSWALK.get(iso.upper())
    if xw is None:
        raise LookupError(f'no GEM->WB crosswalk for {iso}')
    df = df.assign(ADM1CD_c=df['ID_1'].map(xw))
    grp = df.groupby('ADM1CD_c')
    # area-weighted UCC where several GEM units share a WB unit (ESH000)
    ucc = grp.apply(
        lambda g: g['BLDG_REPL_COST_USD'].sum() / g['TOTAL_AREA_SQM'].sum(),
        include_groups=False)
    national = df['BLDG_REPL_COST_USD'].sum() / df['TOTAL_AREA_SQM'].sum()
    return pd.Series({c: float(ucc.get(c, national)) for c in adm1_codes},
                     name='ucc_usd_per_m2')
