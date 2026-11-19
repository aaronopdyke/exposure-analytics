"""Build the WBG-branded comparison deck for a country with python-pptx.

Starts from the official WBG template; keeps its Cover and the light
acknowledgements/disclaimer slide (wording lives on the layout, preserved
verbatim), deletes the other demo slides, and builds clean content slides:
white canvas + manually placed title/images/text (no body placeholders, no
split layouts - per formatting guidance for this deck). All monetary figures
in constant latest-year US$.

The same deck is produced for every country: every number AND every
comparative statement (which model is highest, whether growing to a common
year widens or narrows the spread, where regions disagree) is computed from
docs/data/<ISO>/meta.json + adm1.geojson at build time, so the narrative
cannot drift from the data. Models a country lacks (e.g. Microsoft over the
Marshall Islands, GAR15 over Venezuela) drop out of the slides. Only the
short COUNTRY_NOTES below are hand-written.

The closing slide links the comparison to GRADE (the World Bank's rapid
post-disaster damage estimation): a country's GRADE exposure base, or other
published values where there is none, comes from config.yaml
(`countries.<ISO>.grade` / `.benchmarks`) and is put on the models' footing
by src/grade.py.

Usage: py site/tools/build_deck.py [ISO3 ...]
       -> site/<Country>_Exposure_Model_Comparison.pptx (+ Drive Outputs/)
Run site/tools/make_figures.py for the same countries first.
"""

import json
import os
import shutil
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DATA = os.path.join(os.path.dirname(SITE), 'docs', 'data')
TEMPLATE = os.path.expanduser(
    r'~\.claude\skills\wbg-deck-template\assets\WBG_Template.pptx')
COVER_DIR = os.path.join(SITE, 'deck')


def cover_image(iso):
    """Country-specific cover art (site/deck/cover_<ISO>.png, see
    make_covers.py), else the neutral default skyline."""
    own = os.path.join(COVER_DIR, f'cover_{iso.upper()}.png')
    return own if os.path.exists(own) else os.path.join(
        COVER_DIR, 'cover_default.png')

NAVY = RGBColor(0x17, 0x40, 0x6D)
BLUE = RGBColor(0x0F, 0x6F, 0xC6)
GREY = RGBColor(0x40, 0x40, 0x40)
MUTED = RGBColor(0x9A, 0xA3, 0xAB)
BRIGHT = RGBColor(0x00, 0x9D, 0xD9)
CYAN = RGBColor(0x0B, 0xD0, 0xD9)
GREEN = RGBColor(0x10, 0xCF, 0x9B)
OLIVE = RGBColor(0xA5, 0xC2, 0x49)
TINT = RGBColor(0xDB, 0xEF, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

# The only hand-written, country-specific sentences in the deck: facts about
# how a country's boundaries/sources were handled that the data cannot say.
COUNTRY_NOTES = {
    'MAR': {
        'gar15': ('Western Sahara is a separate GAR15 dataset, shown as the '
                  'hatched WB unit'),
        'gem': ("GEM's two southern regions map to the WB Western Sahara "
                'unit via region matching'),
        'regional': ('Western Sahara (hatched unit): small in all models; '
                     'GEM values come from its two southern regions via the '
                     'boundary crosswalk.'),
    },
    'MHL': {
        'gar15': ('its ~5 km cells rarely sit on an islet, so each is '
                  'assigned to the atoll envelope it falls in or nearest to'),
        'gem': ("GEM's 23 atoll units are matched to the atolls by name "
                '(Bikini & Kili to Kili, Enewetak & Ujelang to Enewetak)'),
        'regional': ('WB Admin-1 has no subdivisions here: the WB coastline '
                     'is split into atolls by SPC/OCHA atoll names and each '
                     'is drawn as an envelope around its islets.'),
    },
}

NUM_WORD = {2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven'}


# ---- number formatting -----------------------------------------------------
def B(v):
    """Money in words, with only as many decimals as the size needs."""
    if abs(v) >= 1e10:
        return f'${v / 1e9:,.0f} billion'
    if abs(v) >= 1e9:
        return f'${v / 1e9:,.1f} billion'
    return f'${v / 1e6:,.0f} million'


def MM(v):
    return f'{v / 1e6:,.0f} Mm²' if v >= 2e7 else f'{v / 1e6:,.1f} Mm²'


def ML(v):
    return f'{v / 1e6:,.1f} million' if v >= 1e6 else f'{v:,.0f}'


def pct(a, b):
    return f'{100 * a / (a + b):,.0f}%'


def join_names(names):
    names = list(names)
    if len(names) <= 1:
        return ''.join(names)
    return ', '.join(names[:-1]) + ' and ' + names[-1]


# ---- slide helpers ---------------------------------------------------------
def keep_only(prs, keep_idx):
    ids = list(prs.slides._sldIdLst)
    for i, sld in enumerate(ids):
        if i not in keep_idx:
            rid = sld.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            prs.part.drop_rel(rid)
            prs.slides._sldIdLst.remove(sld)


def layout_by_name(prs, name):
    for master in prs.slide_masters:
        for lay in master.slide_layouts:
            if lay.name.strip() == name:
                return lay
    raise LookupError(name)


def text_block(slide, x, y, w, lines, h=None):
    """lines: list of (text, size, bold, color, space_after_pt)."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w),
                                  Inches(h or 1))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, (txt, size, bold, color, gap) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(gap)
        r = p.add_run()
        r.text = txt
        r.font.name = 'Arial'
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
    return tb


def content_slide(prs, layout, title):
    """Clean white content slide: the template's content layouts are all
    half-split art panels (explicitly not wanted for this deck), so every
    placeholder is dropped, the layout art is covered with a white canvas,
    and the title + rule are drawn manually in brand type."""
    s = prs.slides.add_slide(layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    canvas = s.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    canvas.fill.solid()
    canvas.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    canvas.line.fill.background()
    canvas.shadow.inherit = False
    text_block(s, 0.45, 0.32, 12.4, [(title, 24, True, NAVY, 0)])
    rule = s.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.5), Inches(1.02), Inches(12.35),
        Pt(1.6))
    rule.fill.solid()
    rule.fill.fore_color.rgb = NAVY
    rule.line.fill.background()
    rule.shadow.inherit = False
    return s


def pic_fit(slide, path, x, y, max_w, max_h):
    from PIL import Image
    iw, ih = Image.open(path).size
    scale = min(max_w / iw, max_h / ih)
    return slide.shapes.add_picture(
        path, Inches(x), Inches(y),
        width=Emu(int(Inches(1) * iw * scale)),
        height=Emu(int(Inches(1) * ih * scale)))


def section_slide(prs, layout, num, title):
    """Navy full-bleed section divider."""
    s = prs.slides.add_slide(layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    canvas = s.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    canvas.fill.solid()
    canvas.fill.fore_color.rgb = NAVY
    canvas.line.fill.background()
    canvas.shadow.inherit = False
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.95), Inches(2.85),
                             Inches(1.5), Pt(3.5))
    bar.fill.solid()
    bar.fill.fore_color.rgb = CYAN
    bar.line.fill.background()
    bar.shadow.inherit = False
    text_block(s, 0.9, 3.05, 11.6, [
        (f'SECTION {num}', 13, True, CYAN, 8),
        (title, 38, True, WHITE, 0)])
    return s


def replace_cover_photo(prs, iso):
    """Swap the Cover layout's 'Photograph' picture for the country's
    cover art, center-cropped to the frame's aspect so nothing stretches."""
    COVER_IMG = cover_image(iso)
    if not os.path.exists(COVER_IMG):
        print('cover image not found, keeping template photo:', COVER_IMG)
        return
    import io
    from PIL import Image
    layout = prs.slides[0].slide_layout
    pic = next(sh for sh in layout.shapes
               if sh.shape_type == 13 and sh.name == 'Photograph')
    frame_aspect = pic.width / pic.height
    img = Image.open(COVER_IMG).convert('RGB')
    w, h = img.size
    if w / h > frame_aspect:      # too wide - crop sides
        new_w = int(h * frame_aspect)
        img = img.crop(((w - new_w) // 2, 0, (w + new_w) // 2, h))
    else:                          # too tall - crop top/bottom
        new_h = int(w / frame_aspect)
        img = img.crop((0, (h - new_h) // 2, w, (h + new_h) // 2))
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    rId = pic._element.blip_rId
    layout.part.related_part(rId)._blob = buf.getvalue()


def _box(slide, x, y, w, h, fill, line=None):
    b = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x),
                               Inches(y), Inches(w), Inches(h))
    b.adjustments[0] = 0.08
    b.fill.solid()
    b.fill.fore_color.rgb = fill
    if line is None:
        b.line.fill.background()
    else:
        b.line.color.rgb = line
        b.line.width = Pt(1)
    b.shadow.inherit = False
    return b


def _card(slide, x, y, w, name, color, desc, h=1.28, muted=False):
    _box(slide, x, y, w, h, WHITE, line=RGBColor(0xD5, 0xDE, 0xE6))
    strip = _box(slide, x, y, 0.09, h, color)
    strip.adjustments[0] = 0.5
    text_block(slide, x + 0.22, y + 0.12, w - 0.35, [
        (name, 13.5, True, MUTED if muted else NAVY, 2),
        (desc, 10.5, False, MUTED if muted else GREY, 0),
    ])


# ---- the deck --------------------------------------------------------------
def build(iso, out=None):
    import geopandas as gpd
    sys.path.insert(0, os.path.dirname(SITE))
    from src import grade
    from src.config import country

    iso = iso.upper()
    fig = os.path.join(SITE, 'figures', iso)
    data = os.path.join(DOCS_DATA, iso)
    with open(os.path.join(data, 'meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    g = gpd.read_file(os.path.join(data, 'adm1.geojson'))
    T = meta['totals']
    YR = meta['deflator']['target_year']
    CTY = meta.get('name') or meta['country'].split(' (')[0]
    USD = f'constant {YR} US$'
    out = out or os.path.join(
        SITE, f'{CTY.replace(" ", "_")}_Exposure_Model_Comparison.pptx')
    notes = COUNTRY_NOTES.get(iso, {})
    M = meta['models']
    cov = meta.get('coverage', {})
    units = meta.get('units') or {'kind': 'adm1', 'count': len(g),
                                  'noun': 'region'}
    atolls = units['kind'] == 'atolls'
    noun = units['noun']
    has_msb = 'msb' in M
    gem_split = 'urban' in M['gem2026']['value']
    fps = [p for p in ('overture', 'gba', 'msb') if p in M]
    fp_label = {'overture': 'Overture', 'gba': 'GBA', 'msb': 'Microsoft'}
    n_models = len(M)
    VG = meta['vintages']['value_growth']
    FG = meta['vintages']['floor_growth']
    gdp_basis = VG.get('basis') == 'real_gdp'
    cagr = VG['trailing_cagr']
    # a shrinking series (Venezuela's GDP) reads better as "down x%/yr"
    rate_txt = (f'~{cagr:.1%}/yr recently' if cagr >= 0 else
                f'down ~{-cagr:.1%}/yr over the past decade')
    value_path = (
        f'real GDP (WDI NY.GDP.MKTP.KD, {rate_txt} - the WB Wealth Accounts '
        f'publish no produced capital for {CTY})' if gdp_basis else
        f'the WB produced-capital path (CWON NW.PCA.TO, {rate_txt})')
    # output can collapse while the buildings stay standing
    weak_path = (' GDP is a weak guide to the building stock here: output '
                 'fell far more than buildings did, so read the grown values '
                 'as indicative.' if gdp_basis and cagr < 0 else '')

    native = {'GAR15': ('gar15_usd_adj', 'gar15'),
              'GIRI': ('giri_total_usd_adj', 'giri'),
              'GEM v2023': ('gem23_bldg_repl_usd_adj', 'gem2023'),
              'GEM v2026': ('gem26_bldg_repl_usd_adj', 'gem2026')}
    native = {n: v for n, v in native.items() if v[1] in M}
    has_gar = 'gar15' in M
    nat = {n: T[c] for n, (c, _) in native.items()}
    nat_grown = {n: T[c] * VG['factors'][k] for n, (c, k) in native.items()}
    ratio = max(nat.values()) / min(nat.values())
    ratio_grown = max(nat_grown.values()) / min(nat_grown.values())
    fpv = {p: T[f'{p}_value_usd_adj'] for p in fps}

    shutil.copy2(TEMPLATE, out)
    prs = Presentation(out)
    # keep Cover (idx 0) and the light full-text disclaimer variant (idx 21,
    # layout "Acknowledgements and disclaimers 7" - wording lives on the
    # layout and is preserved untouched)
    keep_only(prs, {0, 21})
    replace_cover_photo(prs, iso)
    lay = layout_by_name(prs, 'Content slide 1')

    # ---- cover -------------------------------------------------------------
    # match placeholders by idx: python-pptx yields fresh proxies on every
    # iteration, so identity checks silently match nothing
    for ph in prs.slides[0].placeholders:
        if ph.placeholder_format.idx == 0:
            ph.text_frame.text = 'Comparing Building Exposure Models'
        elif ph.has_text_frame:
            ph.text_frame.text = CTY

    # ---- overview: what is being compared ----------------------------------
    s = content_slide(prs, lay, 'Datasets evaluated')
    ov_release = M['overture']['vintage'].split(' ')[0]
    if has_msb:
        sparse = cov.get('msb', {}).get('sparse_units') or []
        msb_card = ('Microsoft GlobalML (2026-02)', OLIVE,
                    'machine-learned footprints'
                    + (f'; partial coverage in {CTY}' if sparse else ''),
                    False)
    else:
        msb_card = ('Microsoft GlobalML — not available', MUTED,
                    f'no tiles published over {CTY}; {NUM_WORD[n_models]} '
                    'models are compared instead of seven', True)
    if has_gar:
        gar_card = ('GAR15 — Global Assessment Report 2015', BLUE,
                    'UN Int. Strategy for Disaster Reduction (UNISDR); ~5 km '
                    'point grid, ~2011 inputs; native urban/rural split',
                    False)
    else:
        gar_card = ('GAR15 — not available', MUTED,
                    f"UNISDR's per-country release has no file for {CTY}; "
                    f'{NUM_WORD[n_models]} models are compared instead of '
                    'seven', True)
    cols = [
        ('CAPITAL STOCK OF BUILDINGS', 'top-down, from WB produced capital', [
            gar_card,
            ('GIRI — Global Infrastructure Resilience Index', NAVY,
             'Building Exposure Model, UNEP/GRID-Geneva (~2023); 5 km '
             'rasters, ~2020 inputs; res / non-res layers', False),
        ]),
        ('BUILDING REPLACEMENT COST', 'bottom-up engineering, excl. contents', [
            ('GEM v2023.1.1 — Global Exposure Model', BRIGHT,
             'Global Earthquake Model Foundation; ADM1 x occupancy '
             'summaries; 2021 US$ price base', False),
            ('GEM v2026.0.0 — Global Exposure Model', BRIGHT,
             'stock updated to 2025, costs re-based to 2024-25', False),
        ]),
        ('ESTIMATED REPLACEMENT VALUE', 'floor area x GEM unit cost (UCC)', [
            (f'Overture Maps ({ov_release})', CYAN,
             'mapped footprints: OpenStreetMap + Microsoft + Google', False),
            ('GBA — Global Building Atlas', GREEN,
             'Technical University of Munich; LoD1 footprints WITH modelled '
             'heights (~2024)', False),
            msb_card,
        ]),
    ]
    x0, w, gap = 0.5, 4.0, 0.18
    for i, (hdr, sub, cards) in enumerate(cols):
        x = x0 + i * (w + gap)
        _box(s, x, 1.35, w, 0.78, NAVY)
        text_block(s, x + 0.18, 1.44, w - 0.3, [
            (hdr, 13, True, WHITE, 1), (sub, 10, False, TINT, 0)])
        for j, (name, color, desc, muted) in enumerate(cards):
            _card(s, x, 2.32 + j * 1.44, w, name, color, desc, muted=muted)
    _box(s, x0, 6.85, 3 * w + 2 * gap, 0.52, TINT)
    aligned = (f"aggregated to {units['count']} atolls (WB coastline, "
               f'split by atoll) · {USD} · structures only' if atolls
               else f'aligned to WB Official Boundaries Admin-1 · {USD} · '
               'structures only (contents excluded everywhere)')
    text_block(s, x0 + 0.2, 6.95, 3 * w + 2 * gap - 0.4, [
        (f'All {NUM_WORD[n_models]} {aligned}', 12, True, NAVY, 0)])

    # ---- section 1: the comparison -----------------------------------------
    section_slide(prs, lay, 1, 'Comparing the totals')

    s = content_slide(prs, lay, 'Country totals by model')
    pic_fit(s, os.path.join(fig, 'bars_totals.png'), 0.6, 1.45, 12.1, 4.35)
    lo_p, hi_p = min(fpv, key=fpv.get), max(fpv, key=fpv.get)
    if fpv[lo_p] > max(nat.values()):
        where = ('ABOVE every native-value model: the mapped building stock '
                 'implies more floor space than the top-down and '
                 'engineering models assume')
    elif fpv[hi_p] < min(nat.values()):
        where = 'BELOW every native-value model'
    else:
        where = 'inside the range spanned by the native-value models'
    text_block(s, 0.75, 5.95, 11.8, [
        ('After price-year alignment: '
         + ' · '.join(f'{n} {B(v)}' for n, v in nat.items())
         + '. All figures are structures-only (GEM contents dropped). The '
         'remaining spread is method, not price levels - see the vintage '
         'slide.', 12.5, False, GREY, 8),
        (f'With GBA-calibrated storeys the {NUM_WORD[len(fps)]} footprint '
         f'estimates sit between {B(fpv[lo_p])} ({fp_label[lo_p]}) and '
         f'{B(fpv[hi_p])} ({fp_label[hi_p]}) - {where}.',
         12.5, False, GREY, 0),
    ])

    s = content_slide(prs, lay,
                      f'Country totals, grown to {YR} for growth since each '
                      "model's vintage")
    pic_fit(s, os.path.join(fig, 'bars_totals_grown.png'), 0.6, 1.45, 12.1,
            4.35)
    if ratio_grown > ratio * 1.03:
        verdict = (f'makes the spread WIDER, not narrower ({ratio:.1f}× to '
                   f'{ratio_grown:.1f}× between the native-value models) - '
                   'the disagreements are about method, not vintage.')
    elif ratio_grown < ratio * 0.97:
        verdict = (f'narrows the native-value spread from {ratio:.1f}× to '
                   f'{ratio_grown:.1f}× but does not close it - most of the '
                   'disagreement is method, not vintage.')
    else:
        verdict = (f'leaves the native-value spread essentially unchanged '
                   f'(~{ratio_grown:.1f}×) - the disagreements are about '
                   'method, not vintage.')
    old_n = next(iter(native))          # oldest data vintage present
    old_k = native[old_n][1]
    old_f = VG['factors'][old_k]
    old_verb = ('rises to' if old_f > 1.005 else
                'falls to' if old_f < 0.995 else 'stays at')
    text_block(s, 0.75, 5.95, 11.8, [
        ('Identical charts to the previous slide, but each model is grown '
         f'from its data vintage: values along {value_path}, floor areas at '
         f"the GHSL built-up-volume rate (~{FG['rate']:.1%}/yr). {old_n} "
         f"({meta['vintages']['years'][old_k]} inputs, x{old_f:.2f}) "
         f'{old_verb} {B(nat_grown[old_n])}.', 12.5, False, GREY, 8),
        (f'Growing every model to a common stock year {verdict} Factors of '
         f'x1.00 mean the data already reflects {YR}.{weak_path}',
         12.5, False, GREY, 0),
    ])

    # ---- regional breakdown (all statements derived from the unit table) ---
    trio = [('GAR15', 'gar15_usd_adj'), ('GIRI', 'giri_total_usd_adj'),
            ('GEM v2026', 'gem26_bldg_repl_usd_adj')]
    trio = [t for t in trio if t[1] in g.columns]
    n_trio = len(trio)
    all_n = 'both' if n_trio == 2 else f'all {NUM_WORD[n_trio]}'
    nm = g['name'].str.split(' (', regex=False).str[0]
    share = {lab: g[col] / g[col].sum() for lab, col in trio}
    tops = {lab: nm[sh.idxmax()] for lab, sh in share.items()}
    order = nm[(sum(share.values()) / n_trio).sort_values(
        ascending=False).index]
    order = list(order)
    lead = order[0]
    lead_i = nm[nm == lead].index[0]
    if len(set(tops.values())) == 1:
        head = f'Same leading {noun} in {all_n} models'
        b1 = (f'{lead} leads in every model, followed by {order[1]} and '
              f'{order[2]}.')
    else:
        head = f'Models disagree on the leading {noun}'
        b1 = ('; '.join(f'{lab} puts {t} first' for lab, t in tops.items())
              + '.')
    b2 = (f'{lead} holds '
          + ', '.join(f'{share[lab][lead_i]:.0%} ({lab})' for lab, _ in trio)
          + ' of the national total.')
    # relative disagreement, among units that matter (>= 1% in some model)
    mat = g[[c for _, c in trio]]
    big = (sum(share.values()) / n_trio) >= 0.01
    spread = (mat.max(axis=1) / mat.min(axis=1).where(mat.min(axis=1) > 0))
    spread = spread[big].dropna().sort_values(ascending=False)
    worst = [f'{nm[i]} ({spread[i]:.1f}×)' for i in spread.index[:2]]
    lines = [(head, 15, True, NAVY, 8),
             ('–  ' + b1, 12.5, False, GREY, 7),
             ('–  ' + b2, 12.5, False, GREY, 7)]
    if worst:
        lines.append((f'–  Relative disagreement between them is '
                      f'largest in {join_names(worst)}.', 12.5, False, GREY,
                      7))
    shown = len(g) if len(g) <= 14 else 12
    if shown < len(g):
        rest = 1 - share['GIRI'].sort_values(ascending=False)[:shown].sum()
        lines.append((f'–  Chart shows the {shown} largest of {len(g)} '
                      f'{noun}s; the others hold about {rest:.0%} of the '
                      'GIRI total.', 12.5, False, GREY, 7))
    if notes.get('regional'):
        lines.append(('–  ' + notes['regional'], 12.5, False, GREY, 7))
    s = content_slide(prs, lay, 'Breakdown by atoll' if atolls else
                      'Regional breakdown by WB Admin-1 unit')
    pic_fit(s, os.path.join(fig, 'adm1_grouped.png'), 0.5, 1.4, 7.6, 5.6)
    text_block(s, 8.35, 1.7, 4.6, lines)

    # ---- section 2: the models ---------------------------------------------
    section_slide(prs, lay, 2, 'The models evaluated')

    def model_slide(title, img, headline, sub, bullets):
        sl = content_slide(prs, lay, title)
        pic_fit(sl, os.path.join(fig, img), 0.35, 1.35, 6.9, 5.7)
        ls = [(headline, 30, True, NAVY, 2), (sub, 13, False, BLUE, 16)]
        for b in bullets:
            ls.append(('–  ' + b, 12.5, False, GREY, 8))
        text_block(sl, 7.5, 1.6, 5.5, ls)

    def urban_bullet(p):
        return (f"urban share "
                f"{pct(T[f'{p}_floor_area_m2_urban'], T[f'{p}_floor_area_m2_rural'])} "
                'of floor area (GHSL DEGURBA 2020)')

    def attr_phrase(p):
        sh = cov.get(p, {}).get('attr_share', 0)
        if sh < 0.005:
            return 'essentially never populated'
        return f"populated for {'only ' if sh < 0.25 else ''}{sh:.0%} of footprint area"

    est_sub = f'ESTIMATED replacement value = floor area × GEM UCC, {USD}'

    if has_gar:
        model_slide('GAR15 — UNISDR Global Exposure Dataset (2015)',
            'map_gar15.png', B(T['gar15_usd_adj']),
            f'capital stock of buildings, {USD}', [
            f"{B(T['gar15_usd'])} in its native 2005 US$ (WB produced capital, "
            'structures - no contents)',
            f"urban {B(T['gar15_urban_usd_adj'])} · rural "
            f"{B(T['gar15_rural_usd_adj'])} "
            f"({pct(T['gar15_urban_usd'], T['gar15_rural_usd'])} urban, native "
            'split)',
            'top-down: national capital stock distributed on a ~5 km grid '
            '(1 km at the coast) using population and GDP proxies',
            'source: HDX per-country shapefiles'
            + (f"; {notes['gar15']}" if notes.get('gar15') else ''),
        ])
    model_slide('GIRI — Building Exposure Model (~2023)',
        'map_giri.png', B(T['giri_total_usd_adj']),
        f'capital stock of buildings, {USD}', [
        f"{B(T['giri_total_usd'])} in its native 2018 US$ (WB produced "
        'capital, structures - no contents)',
        f"residential {B(T['giri_res_usd_adj'])} · non-residential "
        f"{B(T['giri_nres_usd_adj'])}",
        'top-down 5×5 km global rasters by UNEP/GRID-Geneva; includes '
        'social infrastructure (health, education)',
        'no urban/rural split published; res / non-res layers instead',
    ])
    dv = T['gem26_bldg_repl_usd_adj'] / T['gem23_bldg_repl_usd_adj'] - 1
    df = T['gem26_floor_area_m2'] / T['gem23_floor_area_m2'] - 1
    model_slide('GEM — Global Exposure Model (v2023.1.1 and v2026.0.0)',
        'map_gem26.png', B(T['gem26_bldg_repl_usd_adj']),
        f'v2026 building replacement cost, {USD} (excl. contents)', [
        f"v2023.1.1: {B(T['gem23_bldg_repl_usd_adj'])} in {USD} "
        '(2021 US$ native; no urban/rural split published)',
        f"v2026.0.0: costs re-based to 2024-25, stock updated to 2025; "
        f"{ML(T['gem26_buildings'])} buildings · "
        f"{MM(T['gem26_floor_area_m2'])} floor area",
        f'v2023 -> v2026: {dv:+.0%} value in {USD}, {df:+.0%} floor area '
        '(stock update plus cost re-basing; see vintage slide)',
        f"GEM's own published total is "
        f"{B(T['gem26_bldg_repl_usd'] + T['gem26_contents_usd'])} INCLUDING "
        f"{B(T['gem26_contents_usd'])} contents - dropped here so all "
        'models are structures-only',
        'bottom-up engineering model; '
        + (notes.get('gem') or f'GEM regions matched to the {noun}s by name')
        + ' (map shows v2026)',
    ])
    model_slide(f'Overture Maps — building footprints ({ov_release})',
        'map_overture.png', B(T['overture_value_usd_adj']), est_sub, [
        f"{ML(T['overture_buildings'])} mapped buildings · "
        f"{MM(T['overture_floor_area_m2'])} estimated floor area",
        f"num_floors/height {attr_phrase('overture')} in {CTY}: reported "
        'attributes used where present, GBA-calibrated storey multipliers '
        f'(per {noun} x urban/rural) for the rest',
        'community/corporate footprints (OSM, Microsoft, Google) from the '
        'pinned S3 release, aggregated in DuckDB',
        urban_bullet('overture'),
    ])
    gba_top = max(fpv, key=fpv.get) == 'gba'
    miss = cov.get('gba', {}).get('missing_height_share', 0)
    model_slide('Global Building Atlas — LoD1 (~2024)',
        'map_gba.png', B(T['gba_value_usd_adj']), est_sub, [
        f"{ML(T['gba_buildings'])} buildings · "
        f"{MM(T['gba_floor_area_m2'])} floor area · "
        + (f"{T['gba_volume_m3'] / 1e9:,.1f} km³ volume"
           if T['gba_volume_m3'] >= 1e8 else
           f"{T['gba_volume_m3'] / 1e6:,.1f} million m³ volume"),
        'the only footprint source with modelled heights (TUM LoD1)'
        + (' — hence the largest floor area and estimated replacement value'
           if gba_top else '; it calibrates the storey estimate of the '
           'other footprint sources'),
        'floor area via 3-tier storey heights (3.0 / 3.25 / 3.5 m); '
        'missing heights ('
        + (f'{miss:.0%}' if miss >= 0.005 else 'under 1%')
        + ' of buildings) counted as one storey',
        urban_bullet('gba'),
    ])
    if has_msb:
        mc = cov.get('msb', {})
        sparse = mc.get('sparse_units') or []
        coverage = (
            f'coverage is PARTIAL in {CTY}: little or no data in '
            + (', '.join(sparse[:3]) + ' and others' if len(sparse) > 3
               else join_names(sparse))
            + ' - totals undercount' if sparse else
            f"coverage: {mc.get('vs_gba_footprint', 0):.0%} of GBA's "
            f'footprint area with no large gaps by {noun}, in fewer, larger '
            f"polygons ({mc.get('vs_gba_buildings', 0):.0%} of GBA's "
            'building count)')
        model_slide('Microsoft Buildings — GlobalML footprints (2026-02)',
            'map_msb.png', B(T['msb_value_usd_adj']), est_sub, [
            f"{ML(T['msb_buildings'])} buildings · "
            f"{MM(T['msb_footprint_m2'])} footprint · "
            f"{MM(T['msb_floor_area_m2'])} estimated floor area",
            f"native Microsoft GlobalML release; its height field is "
            f"{attr_phrase('msb')} in {CTY}, so storeys come from the GBA "
            'calibration for the rest',
            coverage,
            urban_bullet('msb'),
        ])

    # ---- section 3: assumptions & sensitivity ------------------------------
    section_slide(prs, lay, 3, 'Assumptions & sensitivity')

    if has_gar:
        gar_b, gar_g = nat['GAR15'], nat_grown['GAR15']
        giri_b, giri_g = nat['GIRI'], nat_grown['GIRI']
        gap_b = max(gar_b, giri_b) / min(gar_b, giri_b)
        gap_g = max(gar_g, giri_g) / min(gar_g, giri_g)
        if (gar_b < giri_b) != (gar_g < giri_g):
            gar_story = (f'OVERSHOOTING GIRI ({B(giri_g)}) rather than '
                         'converging: their building-share methods differ, '
                         'not their vintage.')
        elif gap_g > gap_b * 1.03:
            gar_story = (f'moving FURTHER from GIRI ({B(giri_g)}; gap '
                         f'{gap_b:.1f}× to {gap_g:.1f}×) rather than '
                         'converging: their building-share methods differ, '
                         'not their vintage.')
        else:
            gar_story = (f'closing only part of the gap to GIRI ({B(giri_g)}; '
                         f'{gap_b:.1f}× to {gap_g:.1f}×): most of the '
                         'difference is method, not vintage.')
        age_line = (f'Growing GAR15 along that series to {YR} yields '
                    f'{B(gar_g)} - {gar_story}')
    else:
        age_line = (f'Growing every native-value model to {YR} takes the '
                    f'spread between them from {ratio:.1f}× to '
                    f'{ratio_grown:.1f}×: the gap is method, not vintage.')
    g23_g = nat_grown['GEM v2023']
    g26 = nat['GEM v2026']
    if abs(g23_g - g26) < 0.6 * abs(nat['GEM v2023'] - g26):
        gem_story = ('The exception is GEM v2023 -> v2026, where growth '
                     'plus cost re-basing explains most of the change.')
    else:
        gem_story = (f'GEM v2023 -> v2026 is a model revision rather than '
                     f'growth: v2023 grown to {YR} is {B(g23_g)} against '
                     f"v2026's {B(g26)}.")
    series = (
        f'real GDP for {CTY} (WDI NY.GDP.MKTP.KD - the WB Wealth Accounts '
        'publish no produced capital here)' if gdp_basis else
        f'the WB Wealth Accounts produced-capital series for {CTY} '
        '(NW.PCA.TO - the same CWON data GAR15 and GIRI derive from)')
    s = content_slide(
        prs, lay, 'Does data age explain the gaps? '
        + ('Mostly not' if ratio_grown >= ratio * 0.9 else 'Only partly'))
    pic_fit(s, os.path.join(fig, 'vintage_growth.png'), 0.6, 1.45, 12.1, 4.35)
    text_block(s, 0.75, 5.95, 11.8, [
        (f'Growth rates are data-driven, not assumed: values follow {series}, '
         f'floor areas the GHSL built-up-volume rate. {age_line}',
         12.5, False, GREY, 8),
        ('(Floor areas grow far more slowly - GHSL built-up volume, ~'
         f"{FG['rate']:.1%}/yr - so age barely moves them.) {gem_story}",
         12.5, False, GREY, 0),
    ])

    # ---- storey-rule sensitivity -------------------------------------------
    SENS = meta['sensitivity']

    def sens_bounds(k):
        vals = [sc['models'][k]['value_usd_adj'] for sc in SENS.values()]
        return min(vals), max(vals)

    rng = {k: sens_bounds(k) for k in fps}
    sw_lo = min(rng[k][0] / fpv[k] - 1 for k in fps)
    sw_hi = max(rng[k][1] / fpv[k] - 1 for k in fps)
    # does any footprint estimate change rank against a native-value model?
    crossed = sorted({f'{fp_label[k]} / {n}' for k in fps
                      for n, v in nat.items()
                      if (rng[k][0] < v < rng[k][1])})
    if crossed:
        robust = ('The extreme rules can swap neighbours in the ranking ('
                  + join_names(crossed) + '), but they do not change which '
                  'models sit at the top and bottom of the range - the '
                  'spread between methods dwarfs the storey convention.')
    else:
        robust = ('Even the extreme rules do not move any footprint '
                  'estimate past a native-value model - the comparison\'s '
                  'conclusions are insensitive to the storey convention.')
    others = join_names(fp_label[k] for k in fps if k != 'gba')
    s = content_slide(prs, lay,
                      'Sensitivity analysis: storey height assumptions')
    pic_fit(s, os.path.join(fig, 'bars_sensitivity.png'), 0.6, 1.45, 12.1,
            4.35)
    text_block(s, 0.75, 5.95, 11.8, [
        (f'Extreme rules move footprint-model totals {sw_lo:+.0%} to '
         f'{sw_hi:+.0%} (vs a ~{ratio:.1f}× spread between the native-value '
         'models). Four alternative height-to-floor-area rules, recomputed '
         'per building for GBA and carried through the GBA-calibrated '
         f'multipliers for {others}: integer storeys rounded DOWN (min 1), '
         'rounded UP, and the 3-tier storey height (3.0 / 3.25 / 3.5 m) '
         'shifted by ±0.25 m.', 12.5, False, GREY, 8),
        (robust, 12.5, False, GREY, 0),
    ])

    # ---- urban / rural -------------------------------------------------------
    ur = {}
    if has_gar:
        ur['GAR15'] = (T['gar15_urban_usd_adj'], T['gar15_rural_usd_adj'])
    if gem_split:
        ur['GEM v2026'] = (T['gem26_res_urban_usd_adj'],
                           T['gem26_res_rural_usd_adj'])
    for p in fps:
        ur[fp_label[p]] = (T[f'{p}_floor_area_m2_urban'],
                           T[f'{p}_floor_area_m2_rural'])
    us = {k: u / (u + r) for k, (u, r) in ur.items() if u + r > 0}
    lo_k, hi_k = min(us, key=us.get), max(us, key=us.get)
    agree = us[hi_k] - us[lo_k] <= 0.25
    gem_res = '(residential only — COM/IND have no settlement tag)'
    if has_gar and gem_split:
        own = ('GAR15 and GEM v2026 publish their own urban/rural splits '
               f'(GEM: {gem_res[1:]}.')
    elif has_gar:
        own = ('GAR15 publishes its own urban/rural split; GEM publishes '
               f'none for {CTY}.')
    elif gem_split:
        own = f'GEM v2026 publishes its own urban/rural split {gem_res}.'
    else:
        own = f'No model publishes its own urban/rural split for {CTY}.'
    grid_note = (
        ('GAR15 applies its own urban mask to capital stock, while the '
         if has_gar else 'The ')
        + 'footprint sources share one DEGURBA grid - so differences among '
        'them reflect which buildings each maps, not definitions.')
    s = content_slide(prs, lay, 'Urban vs rural: '
                      + ('models broadly agree, definitions differ' if agree
                         else 'shares differ widely, and so do definitions'))
    pic_fit(s, os.path.join(fig, 'urban_rural.png'), 0.6, 1.5, 12.1, 4.4)
    text_block(s, 0.75, 6.15, 11.8, [
        (f'{own} {join_names(fp_label[p] for p in fps)} are classified with '
         'GHSL DEGURBA 2020 (urban = suburban through urban-centre classes) '
         "at each building's 1 km grid cell.", 12.5, False, GREY, 8),
        (f'Urban shares run from {us[lo_k]:.0%} ({lo_k}) to {us[hi_k]:.0%} '
         f'({hi_k}). '
         + grid_note, 12.5, False, GREY, 0),
    ])

    # ---- link to GRADE: what the spread means for a damage estimate ---------
    # Short bullets, one idea each; the method detail sits in the footnote.
    L = grade.link(iso, meta, g)
    G = L['grade']
    RV = grade.REVIEW
    SMALL = RGBColor(0x66, 0x66, 0x66)
    n_word = NUM_WORD[n_models]
    lo_v, hi_v = L['models'][L['lo']], L['models'][L['hi']]
    med_u = L['unit_spread_median']
    within = (f', and by more within a single {noun} (median {med_u:.1f}×)'
              if med_u and med_u > L['spread'] * 1.05 else '')
    s = content_slide(prs, lay, 'What this means for GRADE: the exposure base')
    pic_fit(s, os.path.join(fig, 'grade_link.png'), 0.35, 1.3, 6.9, 5.8)
    if G:
        dev = G['vs_median']
        pos = ('near the middle of' if abs(dev) <= 0.10 else
               'in the upper half of' if dev > 0 else 'in the lower half of')
        if G['ex_contents'] > hi_v:
            pos = 'above'
        elif G['ex_contents'] < lo_v:
            pos = 'below'
        lines = [
            (f"GRADE's exposure sits {pos} the {n_word} models",
             15, True, NAVY, 3),
            (f"{G['event']} GRADE: {B(G['native_total'])} of buildings and "
             f"contents ({G['price_year']} US$)", 12.5, False, BLUE, 10),
            (f"–  Like for like, GRADE's buildings are worth "
             f"{B(G['ex_contents'])} ({USD}, contents removed). The models "
             f"range from {B(lo_v)} ({L['lo']}) to {B(hi_v)} ({L['hi']}).",
             12.5, False, GREY, 8),
            (f"–  GRADE puts {G['nonres_share']:.0%} of building value in "
             'non-residential buildings. GEM v2026 puts '
             f"{L['nonres_share']['GEM v2026']:.0%} there and GIRI "
             f"{L['nonres_share']['GIRI']:.0%}.", 12.5, False, GREY, 8),
            ('–  Sector results are where past GRADEs and PDNAs differ most: '
             f"residential damage averaged {RV['residential_vs_pdna']:.0%} "
             "of the PDNA's, non-residential "
             f"{RV['non_residential_vs_pdna']:.0%} ({RV['cite']}).",
             12.5, False, GREY, 8),
            ('–  Exposure feeds straight into damage: switching models '
             f"changes a result by up to {L['spread']:.1f}× nationally"
             f'{within}.', 12.5, False, GREY, 8),
            ('–  For future GRADEs: check the exposure base against these '
             'models, report the range, and document unit costs and '
             'contents.', 12.5, False, GREY, 10),
        ]
        stock = ('' if G['stock_year'] == YR or G['stock_growth'] is None
                 else
                 f" Stock years are not aligned: GRADE's {G['stock_year']} "
                 f"stock taken to {YR} would be {G['stock_growth']:+.0%}.")
        lines.append((
            f"GRADE values converted from {G['price_year']} to {YR} US$ "
            f"with the US GDP deflator (×{G['factor']:.3f}"
            + (f", {G['price_year']} extrapolated" if G['extrapolated']
               else '')
            + "). Contents removed with GEM's contents-to-building ratio "
            f"({L['contents_ratio']:.0%}).{stock} Each source defines "
            'non-residential differently.', 9.5, False, SMALL, 0))
    else:
        fv = sorted(L['floor_vs_gem'].values())
        floor = (f'{fv[0]:.1f}–{fv[-1]:.1f}×' if len(fv) > 1
                 else f'{fv[0]:.1f}×')
        fp = [lab for lab, k in L['keys'].items() if k in grade.FOOTPRINT]
        ot = [lab for lab in L['keys'] if lab not in fp]

        def rng(pls, labs):
            r = sorted(pl['ratio'][x] for pl in pls for x in labs)
            return f'{r[0]:.0%}–{r[-1]:.0%}'

        def benchmark_lines():
            out, note = [], ''
            for b in L['benchmarks']:
                pls = b['places']
                out.append((
                    f"–  Benchmark: the {b['source']} values buildings in "
                    + join_names(f"{pl['name']} at about {B(pl['usd'])}"
                                 for pl in pls)
                    + '. The footprint models reach '
                    + join_names(f"{rng([pl], fp)} of that for {pl['name']}"
                                 if i == 0 else
                                 f"{rng([pl], fp)} for {pl['name']}"
                                 for i, pl in enumerate(pls))
                    + f'; the other models reach {rng(pls, ot)}. (City '
                    f'against whole {noun}, so indicative.)',
                    12.5, False, GREY, 8))
                note = (country(iso).get('benchmarks') or [{}])[0].get(
                    'note', '')
            return out, note

        bench, note = benchmark_lines()
        sub = (f"The {n_word} models range from {B(lo_v)} ({L['lo']}) to "
               f"{B(hi_v)} ({L['hi']}), a {L['spread']:.1f}× spread",
               12.5, False, BLUE, 10)
        if atolls:
            # Pacific atoll context: where the stock sits, why global
            # models struggle with islets, and the regional evidence
            mcols = [c for k, _, c in grade.MODELS if k in M]
            shares = g[mcols] / g[mcols].sum()
            top2 = shares.mean(axis=1).nlargest(2).index
            conc = shares.loc[top2].sum()
            v20, v23 = RV['vanuatu_vs_pdna']
            lines = [
                ('Pacific atolls: footprint-based models pick up additional '
                 'exposure', 15, True, NAVY, 3),
                sub,
                (f'–  Exposure is concentrated: {join_names(nm[top2])} hold '
                 f'{conc.min():.0%}–{conc.max():.0%} of national building '
                 'value across the models, so one event can reach most of '
                 'it.', 12.5, False, GREY, 8),
                ('–  Global grids fit atolls poorly: the 5 km cells of the '
                 'top-down models are wider than the islets. Mapped '
                 f'footprints show {floor} the floor area GEM assumes.',
                 12.5, False, GREY, 8),
            ] + bench + [
                (f'–  Pacific precedent: GRADE came in at {v20:.0%} and '
                 f"{v23:.0%} of PDNA damage for Vanuatu's 2020 and 2023 "
                 f"cyclones ({RV['cite']}).", 12.5, False, GREY, 8),
                ('–  For future Pacific GRADEs: build exposure from mapped '
                 'footprints, check unit costs against local construction '
                 'prices, and report the model range.', 12.5, False, GREY,
                 10),
            ]
        else:
            lines = [
                ('The choice of exposure model would drive any damage '
                 'estimate', 15, True, NAVY, 3),
                sub,
                (f'–  Mapped footprints show {floor} the floor area GEM '
                 'assumes.', 12.5, False, GREY, 8),
            ] + bench + [
                ('–  For future GRADEs: build exposure from footprints, '
                 'document unit costs and contents, and report the model '
                 'range.', 12.5, False, GREY, 10),
            ]
        if note:
            lines.append((note, 9.5, False, SMALL, 0))
    text_block(s, 7.45, 1.45, 5.5, lines)

    # ---- order: move the kept disclaimer slide to the end -------------------
    ids = list(prs.slides._sldIdLst)
    prs.slides._sldIdLst.remove(ids[1])
    prs.slides._sldIdLst.append(ids[1])

    prs.save(out)
    print('deck written:', out, f'({len(list(prs.slides._sldIdLst))} slides)')

    # mirror to the Drive Outputs folder so the shared copy never goes stale
    sys.path.insert(0, os.path.dirname(SITE))
    try:
        from src.config import OUTPUTS_DIR
        if OUTPUTS_DIR and os.path.isdir(OUTPUTS_DIR):
            shutil.copy2(out, os.path.join(OUTPUTS_DIR,
                                           os.path.basename(out)))
            print('copied to', OUTPUTS_DIR)
    except Exception as e:  # Drive offline is fine - repo copy is canonical
        print('Drive copy skipped:', e)
    return out


if __name__ == '__main__':
    for _iso in (sys.argv[1:] or ['MAR']):
        build(_iso)
