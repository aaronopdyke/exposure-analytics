"""Deck + site figures from the built site data (docs/data/<ISO>).

Reads the simplified unit geojson (all metrics baked in, incl. constant-US$
`_adj` columns and UCC-estimated values) and renders the maps/charts used by
the PowerPoint deck, in WBG template colours (Arial, navy #17406D, WBG blue
#0F6FC6, pale tint #DBEFF9, olive #A5C249).

Everything adapts to the country: models that do not exist there (e.g.
Microsoft over the Marshall Islands) are left out, and money / floor-area
axes pick billions vs millions from the data.

Usage: py site/tools/make_figures.py [ISO3 ...]      -> site/figures/<ISO>/
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
from matplotlib.patches import Patch

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DATA = os.path.join(os.path.dirname(SITE), 'docs', 'data')

NAVY, BLUE, BRIGHT, CYAN = '#17406D', '#0F6FC6', '#009DD9', '#0BD0D9'
GREEN, OLIVE, TINT = '#10CF9B', '#A5C249', '#DBEFF9'
WBG_SEQ = LinearSegmentedColormap.from_list('wbg', [TINT, BRIGHT, BLUE, NAVY])

plt.rcParams.update({'font.family': 'Arial', 'font.size': 11,
                     'figure.facecolor': 'white', 'savefig.facecolor': 'white'})

# model key -> (short chart label, value column, floor column, colour)
MODELS = [
    ('gar15', 'GAR15', 'gar15_usd_adj', None, BLUE),
    ('giri', 'GIRI', 'giri_total_usd_adj', None, NAVY),
    ('gem2023', 'GEM\nv2023', 'gem23_bldg_repl_usd_adj',
     'gem23_floor_area_m2', BRIGHT),
    ('gem2026', 'GEM\nv2026', 'gem26_bldg_repl_usd_adj',
     'gem26_floor_area_m2', BRIGHT),
    ('overture', 'Overture', 'overture_value_usd_adj',
     'overture_floor_area_m2', CYAN),
    ('gba', 'GBA', 'gba_value_usd_adj', 'gba_floor_area_m2', GREEN),
    ('msb', 'MSB', 'msb_value_usd_adj', 'msb_floor_area_m2', OLIVE),
]
ESTIMATED = {'overture', 'gba', 'msb'}
MAP_TITLES = {
    'gar15': 'GAR15 capital stock',
    'giri': 'GIRI BEM capital stock',
    'gem2023': 'GEM v2023.1.1 building replacement cost',
    'gem2026': 'GEM v2026.0.0 building replacement cost',
    'overture': 'Overture est. replacement value (floor x UCC)',
    'gba': 'GBA est. replacement value (floor x UCC)',
    'msb': 'Microsoft est. replacement value (floor x UCC)',
}
MAP_FILES = {'gar15': 'map_gar15.png', 'giri': 'map_giri.png',
             'gem2023': 'map_gem23.png', 'gem2026': 'map_gem26.png',
             'overture': 'map_overture.png', 'gba': 'map_gba.png',
             'msb': 'map_msb.png'}
EST_NOTE = '* est. replacement value: floor area x GEM UCC'


def money_scale(vmax):
    """(divisor, axis word, formatter) - billions or millions, with one
    decimal while the numbers are small enough to need it."""
    div, word, suf = (1e9, 'billions', 'B') if vmax >= 2e9 else (
        1e6, 'millions', 'M')
    dec = 0 if vmax / div >= 20 else 1
    return div, word, lambda v: f'${v / div:,.{dec}f}{suf}'


def area_scale(vmax):
    div, word = (1e6, 'Mm²') if vmax >= 2e6 else (1e3, 'thousand m²')
    dec = 0 if vmax / div >= 20 else 1
    return div, word, lambda v: f'{v / div:,.{dec}f}'


def make(iso, out=None):
    data = os.path.join(DOCS_DATA, iso)
    out = out or os.path.join(SITE, 'figures', iso)
    os.makedirs(out, exist_ok=True)

    g = gpd.read_file(os.path.join(data, 'adm1.geojson'))
    with open(os.path.join(data, 'meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    T = meta['totals']
    YR = meta['deflator']['target_year']
    usdlab = f'constant {YR} US$'
    units = meta.get('units') or {'kind': 'adm1', 'noun': 'region'}
    atolls = units['kind'] == 'atolls'
    models = [m for m in MODELS if m[0] in meta['models']]
    star = lambda k, lab: lab + ('*' if k in ESTIMATED else '')  # noqa: E731
    VG = meta['vintages']['value_growth']['factors']
    FG = meta['vintages']['floor_growth']['factors']
    VIN = meta['vintages']['years']
    v_cagr = meta['vintages']['value_growth']['trailing_cagr']
    v_basis = (meta['vintages']['value_growth'].get('short')
               or 'WB produced capital (CWON)').split(' (')[0]

    def save(fig, name):
        fig.savefig(os.path.join(out, name), dpi=200, bbox_inches='tight')
        plt.close(fig)

    # ---- per-model maps: ONE shared colour scale across all models -------
    vmax = float(g[[m[2] for m in models]].max().max())
    _, _, mfmt = money_scale(vmax)
    for key, _, col, _, _ in models:
        fig, ax = plt.subplots(figsize=(7.2, 6.4))
        g.plot(column=col, ax=ax, cmap=WBG_SEQ,
               edgecolor='#8fa3b3' if atolls else 'white',
               linewidth=0.5 if atolls else 0.8, legend=True, vmin=0,
               vmax=vmax,
               legend_kwds={'shrink': 0.55,
                            'label': f'{usdlab} (shared scale)',
                            'format': lambda v, _: mfmt(v)})
        esh = g[g['esh'] == True]  # noqa: E712
        if len(esh):
            esh.plot(ax=ax, facecolor='none', edgecolor='#8a8873',
                     hatch='///', linewidth=0.9)
        ax.set_axis_off()
        ax.set_title(MAP_TITLES[key], fontsize=14, fontweight='bold',
                     color=NAVY, pad=8)
        save(fig, MAP_FILES[key])

    # ---- comparison: totals bars + their grown twin -----------------------
    # the twin keeps IDENTICAL axes so the two deck slides overlay exactly
    # (only the bars move): y-limits come from the grown maxima
    vals = [(star(k, lab), T[col], c, k) for k, lab, col, _, c in models]
    fl = [(lab, T[fcol], c, k) for k, lab, _, fcol, c in models if fcol]
    ymax_v = max(v * VG[k] for _, v, _, k in vals) * 1.14
    ymax_f = max(v * FG[k] for _, v, _, k in fl) * 1.14
    vdiv, vword, vfmt = money_scale(ymax_v / 1.14)
    fdiv, fword, ffmt = area_scale(ymax_f / 1.14)

    def totals_figure(fname, grown):
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4))
        vv = [(n, v * (VG[k] if grown else 1), c) for n, v, c, k in vals]
        ff = [(n, v * (FG[k] if grown else 1), c) for n, v, c, k in fl]
        axes[0].bar([v[0] for v in vv], [v[1] / vdiv for v in vv],
                    color=[v[2] for v in vv], width=0.62)
        axes[0].set_ylabel(f'{usdlab}, {vword}')
        axes[0].set_ylim(0, ymax_v / vdiv)
        axes[0].set_title(
            f'Building value, grown to {YR} ({v_basis} path)' if grown
            else 'Building value (structures, no contents)',
            fontweight='bold', color=NAVY, fontsize=11)
        for i, v in enumerate(vv):
            axes[0].text(i, (v[1] + 0.0115 * ymax_v) / vdiv, vfmt(v[1]),
                         ha='center', fontweight='bold', color=NAVY,
                         fontsize=9.5)
        axes[0].text(0.02, 0.95, EST_NOTE, transform=axes[0].transAxes,
                     ha='left', fontsize=8.5, color='#666')
        axes[1].bar([v[0] for v in ff], [v[1] / fdiv for v in ff],
                    color=[v[2] for v in ff], width=0.62)
        axes[1].set_ylabel(f'floor area, {fword}')
        axes[1].set_ylim(0, ymax_f / fdiv)
        axes[1].set_title(
            f'Total floor area, grown to {YR} (GHSL built-up-volume rate)'
            if grown else 'Total floor area', fontweight='bold', color=NAVY,
            fontsize=11)
        for i, v in enumerate(ff):
            axes[1].text(i, (v[1] + 0.0115 * ymax_f) / fdiv, ffmt(v[1]),
                         ha='center', fontweight='bold', color=NAVY,
                         fontsize=9.5)
        for ax in axes:
            ax.spines[['top', 'right']].set_visible(False)
        fig.tight_layout()
        save(fig, fname)

    totals_figure('bars_totals.png', grown=False)
    totals_figure('bars_totals_grown.png', grown=True)

    # ---- comparison: per-unit grouped value bars (3 native value models) --
    trio = [(0.25, 'gar15_usd_adj', BLUE, 'GAR15'),
            (0.0, 'giri_total_usd_adj', NAVY, 'GIRI'),
            (-0.25, 'gem26_bldg_repl_usd_adj', BRIGHT, 'GEM v2026')]
    TOP = 12
    gg = g.assign(_peak=g[[t[1] for t in trio]].max(axis=1))
    shown = len(gg) if len(gg) <= TOP + 2 else TOP
    gg = gg.nlargest(shown, '_peak').sort_values('giri_total_usd_adj')
    udiv, uword, _ = money_scale(float(gg['_peak'].max()))
    y = np.arange(len(gg))
    fig, ax = plt.subplots(figsize=(9.5, 6.6))
    # offsets: +0.25 renders on top within each group; plot top-first so the
    # legend's vertical order matches the bars'
    for off, col, colr, lab in trio:
        ax.barh(y + off, gg[col] / udiv, height=0.22, color=colr, label=lab)
    names = [n.split(' (')[0] for n in gg['name']]
    names = [n if len(n) < 26 else n[:24] + '…' for n in names]
    ax.set_yticks(y, names, fontsize=9.5)
    ax.set_xlabel(f'{usdlab}, {uword}')
    ax.legend(frameon=False, loc='lower right')
    ax.spines[['top', 'right']].set_visible(False)
    what = 'atoll' if atolls else 'WB Admin-1 unit'
    ax.set_title(
        f'Building value by {what} (native value models)'
        + (f' - top {shown} of {len(g)}' if shown < len(g) else ''),
        fontweight='bold', color=NAVY)
    fig.tight_layout()
    save(fig, 'adm1_grouped.png')

    # ---- comparison: urban / rural ---------------------------------------
    ur = [('GAR15 value\n(all sectors)', T['gar15_urban_usd_adj'],
           T['gar15_rural_usd_adj'])]
    if 'urban' in meta['models']['gem2026']['value']:
        ur.append(('GEM v2026 res. value', T['gem26_res_urban_usd_adj'],
                   T['gem26_res_rural_usd_adj']))
    for k, lab in (('overture', 'Overture'), ('gba', 'GBA'),
                   ('msb', 'Microsoft')):
        if k in meta['models']:
            ur.append((f'{lab} floor\n(DEGURBA)',
                       T[f'{k}_floor_area_m2_urban'],
                       T[f'{k}_floor_area_m2_rural']))
    ur = [r for r in ur if r[1] + r[2] > 0]
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    yy = np.arange(len(ur))
    shares_u = [100 * u / (u + r) for _, u, r in ur]
    ax.barh(yy, shares_u, height=0.55, color=NAVY, label='urban')
    ax.barh(yy, [100 - s for s in shares_u], left=shares_u, height=0.55,
            color=OLIVE, label='rural')
    for i, s in enumerate(shares_u):
        if s >= 6:
            ax.text(s / 2, i, f'{s:.0f}%', ha='center', va='center',
                    color='white', fontweight='bold')
        if 100 - s >= 6:
            ax.text(s + (100 - s) / 2, i, f'{100 - s:.0f}%', ha='center',
                    va='center', color='#3a3a2a', fontweight='bold')
    ax.set_yticks(yy, [u[0] for u in ur], fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel('share of national total, %')
    ax.legend(frameon=False, loc='upper right', bbox_to_anchor=(1, 1.14),
              ncol=2)
    ax.spines[['top', 'right']].set_visible(False)
    ax.set_title('Urban vs rural shares by model', fontweight='bold',
                 color=NAVY, pad=18)
    fig.tight_layout()
    save(fig, 'urban_rural.png')

    # ---- vintage reconciliation: does data age explain the gaps? ---------
    mv = [(lab.replace('\n', ' '), col, k, c) for k, lab, col, _, c in models
          if k in ('gar15', 'giri', 'gem2023', 'gem2026', 'gba')]
    mv = [(star(k, n), col, k, CYAN if k == 'gem2023' else c)
          for n, col, k, c in mv]
    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    x = np.arange(len(mv))
    obs = [T[c] for _, c, _, _ in mv]
    adj = [T[c] * VG[k] for _, c, k, _ in mv]
    gdiv, gword, gfmt = money_scale(max(adj))
    cols_v = [m[3] for m in mv]
    ax.bar(x - 0.2, [o / gdiv for o in obs], width=0.38, color=cols_v,
           alpha=0.45)
    ax.bar(x + 0.2, [a / gdiv for a in adj], width=0.38, color=cols_v)
    ax.set_xticks(x, [f'{n}\n({VIN[k]})  x{VG[k]:.2f}'
                      for n, _, k, _ in mv], fontsize=9)
    ax.set_ylabel(f'{usdlab}, {gword}')
    top = max(adj) * 1.15
    ax.set_ylim(0, top / gdiv)
    ax.set_title(f'Value: grown along {v_basis} (~{100 * v_cagr:.1f}%/yr '
                 'recently)', fontweight='bold', color=NAVY, fontsize=10.5)
    for i, a in enumerate(adj):
        ax.text(i + 0.2, (a + 0.011 * top) / gdiv, gfmt(a), ha='center',
                fontsize=8.5, fontweight='bold', color=NAVY)
    ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle(f'Observed (pale) vs grown to {YR} (solid) - x1.00 means '
                 f'the data already reflects {YR}', fontweight='bold',
                 color=NAVY, fontsize=12.5)
    fig.tight_layout()
    save(fig, 'vintage_growth.png')

    # ---- storey-rule sensitivity: footprint models under other rules ------
    SENS = meta.get('sensitivity')
    if SENS:
        natives = [(lab, T[col], c) for k, lab, col, _, c in models
                   if k not in ESTIMATED]
        fps = [(lab + '*', k, c) for k, lab, _, _, c in models
               if k in ESTIMATED]
        labels = [n for n, _, _ in natives] + [n for n, _, _ in fps]
        base = [v for _, v, _ in natives]
        cols = [c for _, _, c in natives] + [c for _, _, c in fps]
        band = []
        for _, k, _ in fps:
            sv = [s['models'][k]['value_usd_adj'] for s in SENS.values()]
            base.append(SENS['baseline']['models'][k]['value_usd_adj'])
            band.append((min(sv), max(sv)))
        top = max(max(base), max(h for _, h in band))
        sdiv, sword, sfmt = money_scale(top)
        fig, ax = plt.subplots(figsize=(9.5, 4.6))
        x = np.arange(len(labels))
        ax.bar(x, [b / sdiv for b in base], color=cols, width=0.62)
        # scenario envelope: hatched band per footprint bar, hatch in the
        # bar's own colour; baseline label on the bar, bounds small + grey
        for j, (lo, hi) in enumerate(band):
            i = len(natives) + j
            ax.bar([i], [(hi - lo) / sdiv], bottom=lo / sdiv, width=0.62,
                   facecolor='white', alpha=0.45, edgecolor=cols[i],
                   linewidth=1.2, hatch='///')
            for bound in (hi, lo):
                ax.text(i + 0.36, bound / sdiv, sfmt(bound), ha='left',
                        va='center', color='#8a8a8a', fontsize=8)
        for i, b in enumerate(base):
            ax.text(i, (b + top * 0.025) / sdiv, sfmt(b), ha='center',
                    fontweight='bold', color=NAVY, fontsize=9.5)
        ax.set_xticks(x, labels)
        ax.set_ylabel(f'{usdlab}, {sword}')
        # headroom keeps the legend clear of the tallest bar's label
        ax.set_ylim(0, top * 1.36 / sdiv)
        ax.set_xlim(-0.6, len(labels) - 0.25)
        ax.spines[['top', 'right']].set_visible(False)
        ax.legend(handles=[Patch(facecolor='white', edgecolor='#8a8a8a',
                                 hatch='///',
                                 label='range across storey rules\n'
                                       '(floor/ceil, divisor ±0.25 m)')],
                  frameon=False, loc='upper left',
                  bbox_to_anchor=(0.0, 0.92), fontsize=8.5, handlelength=1.6)
        ax.set_title('Storey-rule sensitivity: hatched band spans integer '
                     'floor/ceil storeys and divisor ±0.25 m',
                     fontweight='bold', color=NAVY, fontsize=11.5)
        ax.text(0.02, 0.95, EST_NOTE, transform=ax.transAxes, ha='left',
                fontsize=8.5, color='#666')
        fig.tight_layout()
        save(fig, 'bars_sensitivity.png')

    print('figures written to', out)


if __name__ == '__main__':
    for _iso in (sys.argv[1:] or ['MAR']):
        make(_iso.upper())
