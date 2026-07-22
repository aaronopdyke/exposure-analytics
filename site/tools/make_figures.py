"""Deck + site figures from the built site data (docs/data/MAR).

Reads the simplified ADM1 geojson (all metrics baked in, incl. constant-US$
`_adj` columns and UCC-estimated values) and renders the maps/charts used by
the PowerPoint deck, in WBG template colours (Arial, navy #17406D, WBG blue
#0F6FC6, pale tint #DBEFF9, olive #A5C249).

Usage: py site/tools/make_figures.py [outdir]
"""

import json
import os
import sys

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(os.path.dirname(SITE), 'docs', 'data', 'MAR')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SITE, 'figures')
os.makedirs(OUT, exist_ok=True)

NAVY, BLUE, BRIGHT, CYAN = '#17406D', '#0F6FC6', '#009DD9', '#0BD0D9'
GREEN, OLIVE, TINT = '#10CF9B', '#A5C249', '#DBEFF9'
WBG_SEQ = LinearSegmentedColormap.from_list('wbg', [TINT, BRIGHT, BLUE, NAVY])

plt.rcParams.update({'font.family': 'Arial', 'font.size': 11,
                     'figure.facecolor': 'white', 'savefig.facecolor': 'white'})

g = gpd.read_file(os.path.join(DATA, 'adm1.geojson'))
meta = json.load(open(os.path.join(DATA, 'meta.json'), encoding='utf-8'))
T = meta['totals']
YR = meta['deflator']['target_year']
COUNTRY = (meta.get('country') or 'Country').split(' (')[0]


def _decorate(ax, gdf):
    esh_g = gdf[gdf['esh'] == True]  # noqa: E712
    if len(esh_g):
        esh_g.plot(ax=ax, facecolor='none', edgecolor='#8a8873',
                   hatch='///', linewidth=0.9)
    ax.set_axis_off()


def choro(col, title, label, fname, fmt=lambda v: f'${v / 1e9:,.0f}B',
          vmax=None):
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    gdf = g.copy()
    gdf.plot(column=col, ax=ax, cmap=WBG_SEQ, edgecolor='white',
             linewidth=0.8, legend=True, vmin=0, vmax=vmax,
             legend_kwds={'shrink': 0.55, 'label': label,
                          'format': lambda v, _: fmt(v)})
    _decorate(ax, gdf)
    ax.set_title(title, fontsize=14, fontweight='bold', color=NAVY, pad=8)
    fig.savefig(os.path.join(OUT, fname), dpi=200, bbox_inches='tight')
    plt.close(fig)


usdlab = f'constant {YR} US$'
# ---- per-model maps: ONE shared color scale across all seven models ------
VALUE_COLS = ['gar15_usd_adj', 'giri_total_usd_adj', 'gem23_bldg_repl_usd_adj',
              'gem26_bldg_repl_usd_adj', 'overture_value_usd_adj',
              'gba_value_usd_adj', 'msb_value_usd_adj']
VMAX = float(g[VALUE_COLS].max().max())
shared = f'{usdlab} (shared scale)'
choro('gar15_usd_adj', 'GAR15 capital stock', shared, 'map_gar15.png',
      vmax=VMAX)
choro('giri_total_usd_adj', 'GIRI BEM capital stock', shared,
      'map_giri.png', vmax=VMAX)
choro('gem23_bldg_repl_usd_adj', 'GEM v2023.1.1 building replacement cost',
      shared, 'map_gem23.png', vmax=VMAX)
choro('gem26_bldg_repl_usd_adj', 'GEM v2026.0.0 building replacement cost',
      shared, 'map_gem26.png', vmax=VMAX)
choro('overture_value_usd_adj', 'Overture est. replacement value (floor x UCC)',
      shared, 'map_overture.png', vmax=VMAX)
choro('gba_value_usd_adj', 'GBA est. replacement value (floor x UCC)', shared,
      'map_gba.png', vmax=VMAX)
choro('msb_value_usd_adj', 'Microsoft est. replacement value (floor x UCC)',
      shared, 'map_msb.png', vmax=VMAX)

# ---- comparison: totals bars ---------------------------------------------
# the grown twin below must keep IDENTICAL axes so the two deck slides
# overlay exactly (only the bars move) - share y-limits from the grown maxima
vals = [('GAR15', T['gar15_usd_adj'], BLUE),
        ('GIRI', T['giri_total_usd_adj'], NAVY),
        ('GEM\nv2023', T['gem23_bldg_repl_usd_adj'], BRIGHT),
        ('GEM\nv2026', T['gem26_bldg_repl_usd_adj'], BRIGHT),
        ('Overture*', T['overture_value_usd_adj'], CYAN),
        ('GBA*', T['gba_value_usd_adj'], GREEN),
        ('MSB*', T['msb_value_usd_adj'], OLIVE)]
key_of = {'GAR15': 'gar15', 'GIRI': 'giri', 'GEM\nv2023': 'gem2023',
          'GEM\nv2026': 'gem2026', 'Overture*': 'overture', 'GBA*': 'gba',
          'MSB*': 'msb'}
fkey = {'GEM\nv2023': 'gem2023', 'GEM\nv2026': 'gem2026',
        'Overture': 'overture', 'GBA': 'gba', 'MSB': 'msb'}
VGF = meta['vintages']['value_growth']['factors']
FGF = meta['vintages']['floor_growth']['factors']
YMAX_V = max(v * VGF[key_of[n]] for n, v, _ in vals) / 1e9 * 1.14
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4))
axes[0].bar([v[0] for v in vals], [v[1] / 1e9 for v in vals],
            color=[v[2] for v in vals], width=0.62)
axes[0].set_ylabel(f'{usdlab}, billions')
axes[0].set_ylim(0, YMAX_V)
axes[0].set_title('Building value (structures, no contents)',
                  fontweight='bold', color=NAVY, fontsize=11)
for i, v in enumerate(vals):
    axes[0].text(i, v[1] / 1e9 + 16, f'${v[1] / 1e9:,.0f}B', ha='center',
                 fontweight='bold', color=NAVY, fontsize=9.5)
axes[0].text(0.02, 0.95, '* est. replacement value: floor area x GEM UCC',
             transform=axes[0].transAxes, ha='left', fontsize=8.5,
             color='#666')
fl = [('GEM\nv2023', T['gem23_floor_area_m2']),
      ('GEM\nv2026', T['gem26_floor_area_m2']),
      ('Overture', T['overture_floor_area_m2']),
      ('GBA', T['gba_floor_area_m2']),
      ('MSB', T['msb_floor_area_m2'])]
YMAX_F = max(v * FGF[fkey[n]] for n, v in fl) / 1e6 * 1.14
axes[1].bar([v[0] for v in fl], [v[1] / 1e6 for v in fl],
            color=[BRIGHT, BRIGHT, CYAN, GREEN, OLIVE], width=0.62)
axes[1].set_ylabel('floor area, Mm²')
axes[1].set_ylim(0, YMAX_F)
axes[1].set_title('Total floor area', fontweight='bold', color=NAVY,
                  fontsize=11)
for i, v in enumerate(fl):
    axes[1].text(i, v[1] / 1e6 + 30, f'{v[1] / 1e6:,.0f}', ha='center',
                 fontweight='bold', color=NAVY, fontsize=9.5)
for ax in axes:
    ax.spines[['top', 'right']].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, 'bars_totals.png'), dpi=200,
            bbox_inches='tight')
plt.close(fig)

# ---- comparison: per-ADM1 grouped value bars (the 3 native value models) --
gg = g.sort_values('giri_total_usd_adj', ascending=True)
y = np.arange(len(gg))
fig, ax = plt.subplots(figsize=(9.5, 6.6))
# offsets: +0.25 renders on top within each group; plot top-first so the
# legend's vertical order matches the bars'
for off, col, colr, lab in [(0.25, 'gar15_usd_adj', BLUE, 'GAR15'),
                            (0.0, 'giri_total_usd_adj', NAVY, 'GIRI'),
                            (-0.25, 'gem26_bldg_repl_usd_adj', BRIGHT,
                             'GEM v2026')]:
    ax.barh(y + off, gg[col] / 1e9, height=0.22, color=colr, label=lab)
names = [n if len(n) < 26 else n[:24] + '…' for n in gg['name']]
ax.set_yticks(y, names, fontsize=9.5)
ax.set_xlabel(f'{usdlab}, billions')
ax.legend(frameon=False, loc='lower right')
ax.spines[['top', 'right']].set_visible(False)
ax.set_title('Building value by WB Admin-1 unit (native value models)',
             fontweight='bold', color=NAVY)
fig.tight_layout()
fig.savefig(os.path.join(OUT, 'adm1_grouped.png'), dpi=200,
            bbox_inches='tight')
plt.close(fig)

# ---- comparison: urban / rural --------------------------------------------
ur = [
    ('GAR15 value\n(all sectors)', T['gar15_urban_usd_adj'],
     T['gar15_rural_usd_adj']),
    ('GEM v2026 res. value', T['gem26_res_urban_usd_adj'], T['gem26_res_rural_usd_adj']),
    ('Overture floor\n(DEGURBA)', T['overture_floor_area_m2_urban'],
     T['overture_floor_area_m2_rural']),
    ('GBA floor\n(DEGURBA)', T['gba_floor_area_m2_urban'],
     T['gba_floor_area_m2_rural']),
    ('Microsoft floor\n(DEGURBA)', T['msb_floor_area_m2_urban'],
     T['msb_floor_area_m2_rural']),
]
fig, ax = plt.subplots(figsize=(9.5, 4.6))
yy = np.arange(len(ur))
shares_u = [100 * u / (u + r) for _, u, r in ur]
ax.barh(yy, shares_u, height=0.55, color=NAVY, label='urban')
ax.barh(yy, [100 - s for s in shares_u], left=shares_u, height=0.55,
        color=OLIVE, label='rural')
for i, s in enumerate(shares_u):
    ax.text(s / 2, i, f'{s:.0f}%', ha='center', va='center', color='white',
            fontweight='bold')
    ax.text(s + (100 - s) / 2, i, f'{100 - s:.0f}%', ha='center', va='center',
            color='#3a3a2a', fontweight='bold')
ax.set_yticks(yy, [u[0] for u in ur], fontsize=10)
ax.invert_yaxis()
ax.set_xlim(0, 100)
ax.set_xlabel('share of national total, %')
ax.legend(frameon=False, loc='upper right', bbox_to_anchor=(1, 1.14), ncol=2)
ax.spines[['top', 'right']].set_visible(False)
ax.set_title('Urban vs rural shares by model', fontweight='bold', color=NAVY,
             pad=18)
fig.tight_layout()
fig.savefig(os.path.join(OUT, 'urban_rural.png'), dpi=200,
            bbox_inches='tight')
plt.close(fig)

# ---- vintage reconciliation: does data age explain the gaps? -------------
VIN = meta['vintages']['years']
VG = meta['vintages']['value_growth']['factors']
FG = meta['vintages']['floor_growth']['factors']
v_cagr = meta['vintages']['value_growth']['trailing_cagr']
f_rate = meta['vintages']['floor_growth']['rate']
models_v = [('GAR15', 'gar15_usd_adj', 'gar15', BLUE),
            ('GIRI', 'giri_total_usd_adj', 'giri', NAVY),
            ('GEM v2023', 'gem23_bldg_repl_usd_adj', 'gem2023', CYAN),
            ('GEM v2026', 'gem26_bldg_repl_usd_adj', 'gem2026', BRIGHT),
            ('GBA*', 'gba_value_usd_adj', 'gba', GREEN)]
fig, ax = plt.subplots(figsize=(9.0, 4.8))
x = np.arange(len(models_v))
obs = [T[c] / 1e9 for _, c, _, _ in models_v]
adj = [T[c] * VG[k] / 1e9 for _, c, k, _ in models_v]
cols_v = [m[3] for m in models_v]
ax.bar(x - 0.2, obs, width=0.38, color=cols_v, alpha=0.45)
ax.bar(x + 0.2, adj, width=0.38, color=cols_v)
ax.set_xticks(x, [n + '\n(' + str(VIN[k]) + ')  x' +
                  format(VG[k], '.2f')
                  for n, _, k, _ in models_v], fontsize=9)
ax.set_ylabel(usdlab + ', billions')
ax.set_ylim(0, max(adj) * 1.15)
ax.set_title('Value: grown along WB produced capital (CWON, ~' +
             format(100 * v_cagr, '.1f') + '%/yr recently)',
             fontweight='bold', color=NAVY, fontsize=10.5)
for i, a in enumerate(adj):
    ax.text(i + 0.2, a + 14, '$' + format(a, ',.0f') + 'B', ha='center',
            fontsize=8.5, fontweight='bold', color=NAVY)
ax.spines[['top', 'right']].set_visible(False)
fig.suptitle('Observed (pale) vs grown to ' + str(YR) + ' (solid) - x1.00 '
             'means the data already reflects ' + str(YR),
             fontweight='bold', color=NAVY, fontsize=12.5)
fig.tight_layout()
fig.savefig(os.path.join(OUT, 'vintage_growth.png'), dpi=200,
            bbox_inches='tight')
plt.close(fig)

# ---- grown twin of the totals figure (deck slide after the totals) --------
# axes/limits identical to bars_totals so the two slides overlay exactly
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4))
gvals = [(n, T_col * VG[key_of[n]], c) for (n, T_col, c) in vals]
axes[0].bar([v[0] for v in gvals], [v[1] / 1e9 for v in gvals],
            color=[v[2] for v in gvals], width=0.62)
axes[0].set_ylabel(f'{usdlab}, billions')
axes[0].set_ylim(0, YMAX_V)
axes[0].set_title('Building value, grown to ' + str(YR) +
                  ' (WB produced-capital path)', fontweight='bold',
                  color=NAVY, fontsize=11)
for i, v in enumerate(gvals):
    axes[0].text(i, v[1] / 1e9 + 16, '$' + format(v[1] / 1e9, ',.0f') + 'B',
                 ha='center', fontweight='bold', color=NAVY, fontsize=9.5)
axes[0].text(0.02, 0.95, '* est. replacement value: floor area x GEM UCC',
             transform=axes[0].transAxes, ha='left', fontsize=8.5,
             color='#666')
gfl = [(n, v * FG[fkey[n]]) for n, v in fl]
axes[1].bar([v[0] for v in gfl], [v[1] / 1e6 for v in gfl],
            color=[BRIGHT, BRIGHT, CYAN, GREEN, OLIVE], width=0.62)
axes[1].set_ylabel('floor area, Mm²')
axes[1].set_ylim(0, YMAX_F)
axes[1].set_title('Total floor area, grown to ' + str(YR) +
                  ' (GHSL built-up-volume rate)', fontweight='bold',
                  color=NAVY, fontsize=11)
for i, v in enumerate(gfl):
    axes[1].text(i, v[1] / 1e6 + 30, format(v[1] / 1e6, ',.0f'), ha='center',
                 fontweight='bold', color=NAVY, fontsize=9.5)
for ax in axes:
    ax.spines[['top', 'right']].set_visible(False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, 'bars_totals_grown.png'), dpi=200,
            bbox_inches='tight')
plt.close(fig)

# ---- storey-rule sensitivity: footprint models under alternative rules ----
SENS = meta.get('sensitivity')
if SENS:
    natives = [('GAR15', T['gar15_usd_adj'], BLUE),
               ('GIRI', T['giri_total_usd_adj'], NAVY),
               ('GEM\nv2023', T['gem23_bldg_repl_usd_adj'], BRIGHT),
               ('GEM\nv2026', T['gem26_bldg_repl_usd_adj'], BRIGHT)]
    fps = [('Overture*', 'overture', CYAN), ('GBA*', 'gba', GREEN),
           ('MSB*', 'msb', OLIVE)]
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    labels = [n for n, _, _ in natives] + [n for n, _, _ in fps]
    base = [v / 1e9 for _, v, _ in natives]
    cols = [c for _, _, c in natives] + [c for _, _, c in fps]
    lo, hi = [], []
    for _, k, _ in fps:
        vals = [s['models'][k]['value_usd_adj'] / 1e9
                for s in SENS.values()]
        b = SENS['baseline']['models'][k]['value_usd_adj'] / 1e9
        base.append(b)
        lo.append(b - min(vals))
        hi.append(max(vals) - b)
    x = np.arange(len(labels))
    ax.bar(x, base, color=cols, width=0.62)
    # scenario envelope as a hatched band over each footprint bar (whiskers
    # collided with the value labels)
    band_lo = [b - d for b, d in zip(base[len(natives):], lo)]
    band_hi = [b + d for b, d in zip(base[len(natives):], hi)]
    ax.bar(x[len(natives):], [h - l for l, h in zip(band_lo, band_hi)],
           bottom=band_lo, width=0.62, facecolor='white', alpha=0.45,
           edgecolor='#3a3a2a', linewidth=1.1, hatch='///',
           label='range across storey rules\n(floor/ceil, divisor ±0.25 m)')
    for i, b in enumerate(base):
        top = b if i < len(natives) else band_hi[i - len(natives)]
        ax.text(i, top + max(base) * 0.025, '$' + format(b, ',.0f') + 'B',
                ha='center', fontweight='bold', color=NAVY, fontsize=9.5)
    ax.set_xticks(x, labels)
    ax.set_ylabel(f'{usdlab}, billions')
    ax.set_ylim(0, max(max(base), max(band_hi)) * 1.18)
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False, loc='upper left', bbox_to_anchor=(0.0, 0.92),
              fontsize=8.5, handlelength=1.6)
    ax.set_title('Storey-rule sensitivity: hatched band spans integer '
                 'floor/ceil storeys and divisor ±0.25 m', fontweight='bold',
                 color=NAVY, fontsize=11.5)
    ax.text(0.02, 0.95, '* est. replacement value: floor area x GEM UCC',
            transform=ax.transAxes, ha='left', fontsize=8.5, color='#666')
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'bars_sensitivity.png'), dpi=200,
                bbox_inches='tight')
    plt.close(fig)

print('figures written to', OUT)
