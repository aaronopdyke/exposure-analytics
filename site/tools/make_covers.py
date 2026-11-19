"""
Deck cover illustrations, one per country, in the shared flat style of the
original Morocco cover: navy-to-blue sky with a faint survey grid, a moon,
navy building silhouettes with cyan openings, and dashed "detected
footprint" boxes around a few buildings.

    py site/tools/make_covers.py            # every scene defined below
    py site/tools/make_covers.py COL MHL VEN

Writes site/deck/cover_<ISO>.png (3440x1936). build_deck.py uses
cover_<ISO>.png when it exists and cover_default.png otherwise. Morocco's
cover_MAR.png is hand-made artwork and is not regenerated here.

Covers carry no explicit religious symbols (crosses, crescents and the
like): places of worship may appear as buildings, without the emblem.

The Cover layout shows roughly the x = 160..1420 band of the 2000-unit
design width (the rest is cropped), so landmarks belong inside it.
"""
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
DECK = os.path.join(os.path.dirname(HERE), 'deck')

W, H = 2000, 1126                  # design units
OUT_W, OUT_H = 3440, 1936          # written size
SS = 2                             # supersampling for clean edges
K = OUT_W / W * SS

SKY_TOP = (23, 64, 109)
SKY_LOW = (14, 113, 198)
NAVY = (18, 46, 82)
CYAN = (11, 196, 206)
MOON = (189, 216, 234)
DASH = (25, 184, 216)
RIDGE_FAR = (17, 96, 170)
RIDGE_NEAR = (15, 110, 196)


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def qbez(p0, c, p2, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p2[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p2[1]))
    return out


class Canvas:
    def __init__(self, sky_low_y=820):
        hh, ww = round(H * K), round(W * K)
        t = np.clip(np.arange(hh) / (sky_low_y * K), 0, 1)[:, None]
        col = (np.array(SKY_TOP)[None, :] * (1 - t)
               + np.array(SKY_LOW)[None, :] * t)
        arr = np.repeat(col[:, None, :], ww, axis=1)
        lw = max(1, round(1.2 * K))                   # faint survey grid
        for g in range(100, W, 100):
            arr[:, round(g * K):round(g * K) + lw] += (5, 4, 3)
        for g in range(100, H, 100):
            arr[round(g * K):round(g * K) + lw, :] += (5, 4, 3)
        self.im = Image.fromarray(np.clip(arr, 0, 255).astype('uint8'), 'RGB')
        self.d = ImageDraw.Draw(self.im)

    # ---- primitives (design units) -----------------------------------
    def rect(self, x0, y0, x1, y1, color=NAVY):
        self.d.rectangle([x0 * K, y0 * K, x1 * K, y1 * K], fill=color)

    def poly(self, pts, color=NAVY):
        self.d.polygon([(x * K, y * K) for x, y in pts], fill=color)

    def ellipse(self, cx, cy, rx, ry, color=NAVY):
        self.d.ellipse([(cx - rx) * K, (cy - ry) * K,
                        (cx + rx) * K, (cy + ry) * K], fill=color)

    def dome(self, cx, base_y, rx, ry, color=NAVY):
        self.d.pieslice([(cx - rx) * K, (base_y - ry) * K,
                         (cx + rx) * K, (base_y + ry) * K], 180, 360,
                        fill=color)

    def arch(self, cx, bottom, w, h, color=CYAN):
        """Round-headed opening, `h` tall including the arch."""
        self.rect(cx - w / 2, bottom - h + w / 2, cx + w / 2, bottom, color)
        self.dome(cx, bottom - h + w / 2, w / 2, w / 2, color)

    def windows(self, x, y, cols, rows, w=26, h=38, gx=28, gy=40, color=CYAN):
        for r in range(rows):
            for c in range(cols):
                x0, y0 = x + c * (w + gx), y + r * (h + gy)
                self.rect(x0, y0, x0 + w, y0 + h, color)

    def dashed_box(self, x0, y0, x1, y1, on=13, off=8, lw=3):
        def run(a, b, fixed, horizontal):
            p = a
            while p < b:
                q = min(p + on, b)
                if horizontal:
                    self.rect(p, fixed - lw / 2, q, fixed + lw / 2, DASH)
                else:
                    self.rect(fixed - lw / 2, p, fixed + lw / 2, q, DASH)
                p += on + off
        run(x0, x1, y0, True)
        run(x0, x1, y1, True)
        run(y0, y1, x0, False)
        run(y0, y1, x1, False)

    def moon(self, cx, cy, r=80):
        self.ellipse(cx, cy, r, r, MOON)

    def ridge(self, pts, color):
        self.poly([(pts[0][0], H)] + list(pts) + [(pts[-1][0], H)], color)

    # ---- vegetation ----------------------------------------------------
    def frond(self, x, y, ang, length, droop=0.4, width=0.16, color=NAVY):
        a = math.radians(ang)
        dx, dy = math.cos(a), -math.sin(a)
        tip = (x + dx * length, y + dy * length + droop * length)
        mid = (x + dx * length * 0.55, y + dy * length * 0.55 - 0.16 * length)
        nx, ny = dy, -dx
        if ny > 0:
            nx, ny = -nx, -ny
        up = (mid[0] + nx * width * length, mid[1] + ny * width * length)
        lo = (mid[0] - nx * width * length * 0.3,
              mid[1] - ny * width * length * 0.3)
        self.poly(qbez((x, y), up, tip) + qbez(tip, lo, (x, y))[1:], color)

    def trunk(self, x, ground, top_x, top_y, w0=15, w1=8, bow=0.0,
              color=NAVY):
        ctrl = ((x + top_x) / 2 + bow, (ground + top_y) / 2)
        line = qbez((x, ground), ctrl, (top_x, top_y), 30)
        left, right = [], []
        for i, (px, py) in enumerate(line):
            j0, j1 = max(i - 1, 0), min(i + 1, len(line) - 1)
            tx, ty = line[j1][0] - line[j0][0], line[j1][1] - line[j0][1]
            n = math.hypot(tx, ty) or 1
            w = (w0 + (w1 - w0) * i / (len(line) - 1)) / 2
            left.append((px - ty / n * w, py + tx / n * w))
            right.append((px + ty / n * w, py - tx / n * w))
        self.poly(left + right[::-1], color)

    def coconut_palm(self, x, ground, height, lean=40, size=1.0, color=NAVY):
        tx, ty = x + lean, ground - height
        self.trunk(x, ground, tx, ty, 15 * size, 8 * size, bow=-lean * 0.5,
                   color=color)
        L = 125 * size
        for ang, drp in ((-28, 0.62), (12, 0.5), (48, 0.36), (88, 0.12),
                         (128, 0.36), (164, 0.5), (205, 0.62)):
            self.frond(tx, ty, ang, L * (0.86 if abs(ang - 88) > 100 else 1),
                       droop=drp, width=0.17, color=color)
        for ox in (-9, 4, 13):
            self.ellipse(tx + ox * size, ty + 12 * size, 7 * size, 7 * size,
                         color)

    def wax_palm(self, x, ground, height, size=1.0, color=NAVY):
        """Quindio wax palm: a very tall, bare, slender trunk with a small
        tuft of fronds at the top."""
        ty = ground - height
        self.trunk(x, ground, x + 6, ty, 9 * size, 5 * size, bow=5,
                   color=color)
        for i in range(9):
            ang = -18 + i * 27
            self.frond(x + 6, ty, ang, 62 * size,
                       droop=0.42 if abs(ang - 90) > 60 else 0.12,
                       width=0.2, color=color)

    # ---- output --------------------------------------------------------
    def save(self, path):
        self.im.resize((OUT_W, OUT_H), Image.LANCZOS).save(path)
        print('wrote', path)


# ---------------------------------------------------------------- scenes

def colombia():
    """Andean city: layered cordillera with a hilltop sanctuary, a colonial
    twin-towered church, balconied tile-roofed houses, wax palms and a
    modern high-rise."""
    c = Canvas()
    c.moon(1010, 215, 78)
    c.ridge([(0, 610), (130, 520), (250, 585), (400, 455), (520, 540),
             (640, 470), (790, 560), (930, 430), (1060, 520), (1200, 440),
             (1330, 530), (1480, 420), (1620, 520), (1780, 450), (2000, 560)],
            RIDGE_FAR)
    c.ridge([(0, 760), (120, 690), (260, 730), (420, 640), (560, 720),
             (720, 660), (880, 705), (1020, 560), (1090, 600), (1160, 640),
             (1300, 720), (1460, 650), (1620, 730), (1800, 670), (2000, 740)],
            RIDGE_NEAR)
    # hilltop sanctuary on the near ridge
    hill = mix(RIDGE_NEAR, NAVY, 0.55)
    c.rect(1002, 536, 1040, 562, hill)
    c.poly([(998, 536), (1021, 518), (1044, 536)], hill)
    c.rect(1040, 520, 1052, 566, hill)
    c.poly([(1038, 520), (1046, 504), (1054, 520)], hill)

    def house(x0, x1, top, roof=46, over=14, inset=30):
        c.rect(x0, top, x1, H)
        c.poly([(x0 - over, top), (x0 + inset, top - roof),
                (x1 - inset, top - roof), (x1 + over, top)])

    def balcony(x0, x1, y):
        c.rect(x0, y, x1, y + 7, CYAN)

    # far-left houses (mostly cropped on the slide)
    house(-20, 150, 930)
    c.windows(20, 965, 2, 1, 28, 44, 40)
    # two-storey balconied house
    house(185, 405, 842)
    c.windows(215, 872, 3, 1, 30, 62, 34)
    balcony(203, 387, 940)
    c.arch(255, H, 50, 108)
    c.windows(310, 1000, 2, 1, 30, 50, 30)
    # church: twin bell towers, pediment, dome
    for tx0 in (432, 652):
        c.rect(tx0, 540, tx0 + 78, H)
        c.rect(tx0 - 7, 668, tx0 + 85, 682)             # cornice
        c.rect(tx0 - 7, 536, tx0 + 85, 550)
        c.dome(tx0 + 39, 538, 30, 40)                    # cupola
        c.rect(tx0 + 33, 478, tx0 + 45, 502)
        c.arch(tx0 + 39, 652, 30, 70)                    # belfry opening
        c.arch(tx0 + 39, 800, 24, 56)
    c.rect(505, 770, 657, H)                             # nave
    c.poly([(498, 772), (581, 704), (664, 772)])         # pediment
    c.rect(548, 668, 614, 730)                           # drum
    c.dome(581, 670, 40, 52)
    c.rect(576, 598, 586, 622)
    c.ellipse(581, 832, 24, 24, CYAN)                    # rose window
    c.arch(581, H, 62, 150)
    c.dashed_box(414, 432, 528, 700)
    # wax palms
    c.wax_palm(790, H, 760, 1.0)
    c.wax_palm(868, H, 640, 0.9)
    # low infill + colonial row
    c.rect(735, 985, 905, H)
    c.windows(752, 1012, 3, 1, 26, 40, 26)
    house(915, 1120, 868, roof=42)
    c.windows(940, 896, 3, 1, 28, 58, 32)
    balcony(930, 1105, 960)
    c.arch(1010, H, 46, 100)
    c.windows(1052, 1018, 1, 1, 30, 48)
    c.dashed_box(896, 806, 1140, 992)
    # modern high-rise + stepped mid-rise
    c.rect(1155, 452, 1262, H)
    c.rect(1170, 436, 1247, 452)
    c.rect(1205, 380, 1211, 436)                         # mast
    for band in range(4):
        for i in range(3):
            x = 1176 + i * 30
            c.rect(x, 492 + band * 150, x + 9, 492 + band * 150 + 104, CYAN)
    c.rect(1275, 700, 1386, H)
    c.rect(1297, 660, 1364, 700)
    c.windows(1288, 730, 2, 3, 30, 44, 26, 46)
    c.dashed_box(1262, 640, 1399, 890)
    # right-hand houses (mostly cropped)
    house(1425, 1600, 900)
    c.windows(1450, 930, 2, 1, 30, 56, 40)
    balcony(1440, 1585, 992)
    c.rect(1600, 960, 1760, H)
    c.windows(1622, 990, 2, 1, 28, 42, 40)
    house(1770, 2020, 860)
    c.windows(1800, 890, 3, 1, 30, 58, 34)
    c.arch(1900, H, 50, 104)
    return c


def marshall_islands():
    """Low coral atoll: lagoon to the horizon, distant islets, coconut
    palms, tin-roofed houses, a rainwater tank, a small church and an
    outrigger sailing canoe."""
    c = Canvas(sky_low_y=770)
    horizon = 770
    # lagoon: deepens toward the foreground
    hh = round((H - horizon) * K)
    t = (np.arange(hh) / hh)[:, None]
    col = (np.array((16, 104, 184))[None, :] * (1 - t)
           + np.array((17, 72, 130))[None, :] * t)
    water = np.repeat(col[:, None, :], round(W * K), axis=1).astype('uint8')
    c.im.paste(Image.fromarray(water, 'RGB'), (0, round(horizon * K)))
    c.rect(0, horizon - 1.5, W, horizon + 1.5, (40, 136, 214))
    c.moon(760, 268, 82)
    for i, (dy, hw) in enumerate(((22, 70), (46, 54), (72, 40), (100, 30),
                                  (130, 20))):
        c.rect(760 - hw, horizon + dy, 760 + hw, horizon + dy + 4,
               mix(MOON, (16, 104, 184), 0.45 + i * 0.08))
    rnd = random.Random(7)
    for _ in range(46):
        x, y = rnd.uniform(0, W), rnd.uniform(horizon + 14, 960)
        ln = rnd.uniform(34, 96)
        c.rect(x, y, x + ln, y + 2.2, (34, 122, 200))
    # distant islets on the horizon
    far = mix(NAVY, SKY_LOW, 0.42)
    for x0, x1, hgt in ((170, 560, 11), (640, 760, 7), (1180, 1560, 10)):
        c.poly([(x0, horizon + 2), (x0 + 30, horizon - hgt),
                (x1 - 40, horizon - hgt), (x1, horizon + 2)], far)
        for k in range(int((x1 - x0) / 46)):
            px = x0 + 34 + k * 46 + rnd.uniform(-8, 8)
            c.coconut_palm(px, horizon - hgt + 2, rnd.uniform(26, 44),
                           lean=rnd.uniform(-6, 6), size=0.2, color=far)
    # outrigger sailing canoe
    c.poly(qbez((1218, 858), (1275, 884), (1338, 852))
           + qbez((1338, 852), (1275, 872), (1218, 858))[1:])
    c.rect(1240, 880, 1316, 885)                              # outrigger float
    c.rect(1262, 866, 1266, 882)
    c.rect(1292, 866, 1296, 882)
    c.poly([(1276, 862), (1281, 862), (1272, 742), (1269, 742)])   # mast
    c.poly(qbez((1270, 746), (1318, 790), (1346, 846))
           + qbez((1346, 846), (1300, 838), (1262, 852))[1:]
           + [(1270, 746)])                                  # sail
    # the islet
    c.poly([(0, 1000), (180, 972), (420, 962), (700, 972), (980, 958),
            (1240, 966), (1480, 984), (1750, 978), (2000, 996),
            (2000, H), (0, H)])

    def cabin(x0, x1, wall_top, base, roof=44, over=16):
        c.rect(x0, wall_top, x1, base)
        c.poly([(x0 - over, wall_top), ((x0 + x1) / 2, wall_top - roof),
                (x1 + over, wall_top)])

    c.coconut_palm(70, 992, 430, lean=50)
    cabin(204, 344, 902, 980)
    c.windows(222, 922, 1, 1, 30, 30)
    c.rect(288, 918, 318, 978, CYAN)
    c.dashed_box(180, 836, 368, 996)
    c.coconut_palm(385, 966, 520, lean=-46, size=1.08)
    c.coconut_palm(452, 966, 400, lean=58)
    # stilt house with steps and a rainwater tank
    cabin(540, 690, 858, 930, roof=46)
    for sx in (548, 596, 640, 682):
        c.rect(sx - 4, 930, sx + 4, 976)
    c.poly([(690, 930), (722, 972), (712, 972), (684, 936)])
    c.windows(566, 876, 1, 1, 32, 30)
    c.rect(636, 872, 664, 928, CYAN)
    c.rect(748, 900, 808, 972)                               # tank
    c.dome(778, 902, 30, 12)
    c.rect(700, 896, 752, 901)                               # downpipe
    # two-storey concrete block
    c.rect(850, 838, 980, 966)
    c.rect(842, 830, 988, 842)
    c.windows(868, 858, 2, 2, 32, 30, 30, 26)
    c.dashed_box(826, 810, 1004, 982)
    c.coconut_palm(1010, 960, 470, lean=-34, size=0.98)
    # church with a steeple
    cabin(1058, 1196, 892, 964, roof=50)
    c.rect(1104, 800, 1150, 900)
    c.poly([(1098, 802), (1127, 718), (1156, 802)])
    c.arch(1127, 872, 20, 40)
    c.arch(1127, 964, 32, 58)
    c.windows(1070, 912, 1, 1, 18, 34)
    c.windows(1168, 912, 1, 1, 18, 34)
    c.coconut_palm(1385, 978, 500, lean=44, size=1.04)
    cabin(1440, 1590, 912, 984)
    c.windows(1462, 930, 2, 1, 30, 30, 30)
    c.coconut_palm(1640, 982, 380, lean=-40, size=0.9)
    cabin(1700, 1850, 906, 980)
    c.rect(1756, 922, 1786, 978, CYAN)
    c.coconut_palm(1915, 988, 450, lean=30)
    return c


def venezuela():
    """Caracas under the Avila: one long mountain wall with a cable car up
    to a round hilltop tower, twin modernist towers, a long slab apartment
    block, self-built houses stepping up a hillside, and palms."""
    c = Canvas()
    c.moon(455, 190, 76)
    # the Avila: a single long wall behind the valley
    c.ridge([(0, 540), (140, 486), (300, 440), (460, 392), (600, 356),
             (760, 330), (900, 298), (1010, 280), (1120, 300), (1260, 344),
             (1400, 334), (1560, 384), (1720, 426), (1880, 474), (2000, 506)],
            RIDGE_FAR)
    c.ridge([(0, 720), (200, 668), (420, 706), (640, 646), (860, 694),
             (1100, 652), (1340, 704), (1600, 664), (1820, 712), (2000, 682)],
            RIDGE_NEAR)
    # round tower and station on the summit, cable car up from the valley
    hill = mix(RIDGE_FAR, NAVY, 0.55)
    c.rect(962, 266, 1058, 284, hill)                    # station
    c.rect(992, 226, 1028, 270, hill)                    # round tower
    c.dome(1010, 227, 18, 10, hill)
    x0, y0, x1, y1 = 596, 640, 964, 270
    c.poly([(x0, y0), (x1, y1), (x1, y1 + 2.4), (x0, y0 + 2.4)], hill)
    for t in (0.3, 0.62):                                # pylons
        px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        c.rect(px - 2.5, py - 4, px + 2.5, py + 34, hill)
    for t in (0.16, 0.47, 0.8):                          # cabins
        px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        c.rect(px - 1, py, px + 1, py + 8, hill)
        c.rect(px - 8, py + 8, px + 8, py + 21, hill)

    # self-built houses stepping up a hillside
    rnd = random.Random(11)
    x = -30
    while x < 486:
        w = rnd.choice((44, 52, 60))
        top = 770 + max(x, 0) * 0.42 - rnd.choice((0, 16, 34))
        c.rect(x, top, x + w + 1, H)
        if rnd.random() < 0.35:                          # rooftop tank
            c.rect(x + 10, top - 12, x + 26, top)
        y = top + 16
        while y < H - 30:
            if rnd.random() < 0.72:
                wx = x + rnd.choice((8, 14, w - 26))
                c.rect(wx, y, wx + 15, y + 20, CYAN)
            y += rnd.choice((46, 54, 62))
        x += w
    c.dashed_box(196, 756, 372, 936)
    # long slab apartment block with stair towers
    c.rect(510, 716, 772, H)
    c.rect(510, 692, 548, 716)
    c.rect(734, 692, 772, 716)
    c.windows(530, 744, 8, 5, 15, 24, 14, 36)
    c.dashed_box(494, 672, 788, 900)
    # palms and low infill
    c.rect(772, 968, 890, H)
    c.coconut_palm(808, H, 470, lean=10, size=0.92)
    c.coconut_palm(858, H, 360, lean=-14, size=0.8)
    # twin modernist towers
    for tx in (896, 1000):
        c.rect(tx, 424, tx + 84, H)
        c.rect(tx + 12, 406, tx + 72, 424)               # crown
        c.rect(tx + 24, 392, tx + 60, 406)
        for band in range(5):
            for i in range(3):
                wx = tx + 14 + i * 24
                c.rect(wx, 462 + band * 132, wx + 9,
                       462 + band * 132 + 96, CYAN)
    c.dashed_box(880, 372, 1100, 610)
    # stepped mid-rise and a second slab
    c.rect(1112, 770, 1246, H)
    c.rect(1140, 728, 1218, 770)
    c.windows(1128, 800, 2, 3, 30, 44, 28, 46)
    c.rect(1262, 838, 1436, H)
    c.rect(1262, 820, 1294, 838)
    c.windows(1280, 866, 5, 3, 16, 26, 16, 40)
    c.dashed_box(1248, 800, 1450, 990)
    # right-hand blocks (mostly cropped on the slide)
    c.rect(1452, 640, 1560, H)
    c.windows(1470, 676, 2, 5, 26, 40, 24, 46)
    c.rect(1575, 880, 1730, H)
    c.windows(1596, 908, 3, 2, 26, 40, 24, 44)
    c.rect(1745, 730, 1860, H)
    c.windows(1764, 762, 2, 4, 28, 42, 24, 46)
    c.rect(1875, 900, 2020, H)
    c.windows(1896, 930, 2, 2, 28, 40, 30, 44)
    return c


def default():
    """Neutral mid-rise skyline for countries without their own scene."""
    c = Canvas()
    c.moon(1050, 230, 78)
    c.ridge([(0, 760), (220, 690), (480, 740), (760, 660), (1040, 730),
             (1320, 650), (1600, 735), (1820, 680), (2000, 730)], RIDGE_NEAR)
    rnd = random.Random(3)
    x = -30
    boxes = []
    while x < W:
        w = rnd.choice((120, 150, 170, 200))
        top = rnd.choice((560, 640, 720, 800, 860, 920))
        c.rect(x, top, x + w, H)
        if rnd.random() < 0.4:
            c.rect(x + w * 0.3, top - 34, x + w * 0.7, top)
        cols = max(1, int((w - 30) // 56))
        rows = max(1, int((H - top - 60) // 86))
        c.windows(x + (w - cols * 56 + 28) / 2, top + 34, cols, rows,
                  28, 42, 28, 44)
        if 200 < x < 1300 and rnd.random() < 0.34:
            boxes.append((x - 14, top - 50, x + w + 14, top + 190))
        x += w + rnd.choice((0, 0, 16))
    for b in boxes[:3]:
        c.dashed_box(*b)
    return c


SCENES = {'COL': colombia, 'MHL': marshall_islands, 'VEN': venezuela,
          'default': default}


if __name__ == '__main__':
    for key in (sys.argv[1:] or list(SCENES)):
        scene = SCENES[key if key == 'default' else key.upper()]
        name = key if key == 'default' else key.upper()
        scene().save(os.path.join(DECK, f'cover_{name}.png'))
