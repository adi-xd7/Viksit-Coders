"""Generate the deck's raster assets: backgrounds, agent emblems, motif marks and screenshot crops.

Usage: python make_assets.py <screenshots_dir> <out_dir>
Everything is drawn procedurally (no stock imagery); screenshots are real captures of the dashboard.
"""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SHOTS = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

W, H = 2667, 1500  # 13.333 x 7.5 in at 200 dpi
OBSIDIAN = (9, 11, 16)
ICE = (118, 185, 255)
GOLD = (197, 166, 106)
IVORY = (232, 229, 220)
SILVER = (146, 153, 166)
CRIMSON = (184, 75, 84)

random.seed(7)
CS = 0.72  # citadel scale


def peaks(draw, y_base, color, seed):
    """Jagged far mountains, kept away from the centre so the citadel stands clear."""
    rnd = random.Random(seed)
    pts = [(0, H), (0, y_base)]
    x = 0
    while x < W:
        x += rnd.uniform(90, 220)
        centre = abs(x - W / 2) < W * 0.16
        h = rnd.uniform(30, 70) if centre else rnd.uniform(90, 260)
        pts.append((x - rnd.uniform(30, 70), y_base - h))
        pts.append((x, y_base - rnd.uniform(0, 40)))
    pts += [(W, y_base), (W, H)]
    draw.polygon(pts, fill=color)


def vgradient(stops):
    """stops: list of (y_frac, rgb)."""
    img = Image.new("RGB", (1, H))
    px = img.load()
    for y in range(H):
        f = y / (H - 1)
        for (f0, c0), (f1, c1) in zip(stops, stops[1:]):
            if f0 <= f <= f1:
                t = (f - f0) / (f1 - f0) if f1 > f0 else 0
                px[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
                break
    return img.resize((W, H))


def glow(base, cx, cy, rx, ry, color, strength):
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=int(255 * strength))
    mask = mask.filter(ImageFilter.GaussianBlur(max(rx, ry) * 0.45))
    layer = Image.new("RGB", (W, H), color)
    return Image.composite(layer, base, mask)


def mist(base, y0, y1, color, alpha, seed):
    rnd = random.Random(seed)
    small = Image.new("L", (96, 54))
    sp = small.load()
    for y in range(54):
        for x in range(96):
            sp[x, y] = rnd.randint(0, 255)
    noise = small.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(40))
    band = Image.new("L", (W, H), 0)
    bd = ImageDraw.Draw(band)
    for y in range(int(y0 * H), int(y1 * H)):
        t = (y - y0 * H) / ((y1 - y0) * H)
        bd.line([(0, y), (W, y)], fill=int(255 * math.sin(math.pi * t)))
    band = band.filter(ImageFilter.GaussianBlur(30))
    mask = Image.composite(noise, Image.new("L", (W, H), 0), band)
    mask = mask.point(lambda v: int(v * alpha))
    return Image.composite(Image.new("RGB", (W, H), color), base, mask)


def ridge(draw, y_base, amp, color, seed, step=60):
    rnd = random.Random(seed)
    pts = [(0, H)]
    y = y_base
    for x in range(0, W + step, step):
        y += rnd.uniform(-amp, amp)
        y = min(max(y, y_base - amp * 3), y_base + amp * 1.5)
        pts.append((x, y))
    pts.append((W, H))
    draw.polygon(pts, fill=color)


def citadel(draw, cx, base_y, s, fill, rim=None):
    """Stave-hall silhouette: tiered gabled roofs, spire and flanking towers. s = scale."""
    def poly(points):
        p = [(cx + x * s, base_y - y * s) for x, y in points]
        draw.polygon(p, fill=fill)
        if rim:
            draw.line(p + [p[0]], fill=rim, width=max(1, int(s * 1.2)))

    def horns(x, y, size):
        # crossed gable boards above a roof apex, the Norse longhouse mark
        p0 = (cx + (x - size) * s, base_y - (y - size * 0.9) * s)
        p1 = (cx + (x + size * 0.55) * s, base_y - (y + size * 0.6) * s)
        q0 = (cx + (x + size) * s, base_y - (y - size * 0.9) * s)
        q1 = (cx + (x - size * 0.55) * s, base_y - (y + size * 0.6) * s)
        for a, b in ((p0, p1), (q0, q1)):
            draw.line([a, b], fill=rim or fill, width=max(2, int(s * 5)))

    # terrace
    poly([(-620, 0), (-620, 30), (620, 30), (620, 0)])
    # longhouses either side: low bodies, steep roofs
    for side in (-1, 1):
        x0, x1 = side * 210, side * 560
        lo, hi = min(x0, x1), max(x0, x1)
        poly([(lo, 30), (lo, 95), (hi, 95), (hi, 30)])
        mid = (lo + hi) / 2
        poly([(lo - 25, 95), (mid, 250), (hi + 25, 95)])
        horns(mid, 250, 34)
    # watch towers
    for side in (-1, 1):
        x = side * 205
        poly([(x - 24, 30), (x - 24, 330), (x, 470), (x + 24, 330), (x + 24, 30)])
    # central stave hall: stacked steep gables
    poly([(-120, 30), (-120, 150), (120, 150), (120, 30)])
    poly([(-165, 150), (0, 380), (165, 150)])
    horns(0, 380, 40)
    poly([(-72, 300), (-72, 360), (72, 360), (72, 300)])
    poly([(-100, 360), (0, 540), (100, 360)])
    horns(0, 540, 30)
    poly([(-38, 500), (-38, 545), (38, 545), (38, 500)])
    poly([(-55, 545), (0, 660), (55, 545)])
    # spire
    poly([(-9, 640), (0, 760), (9, 640)])


def stars(draw, n, y_max, seed, color=(200, 210, 225)):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.uniform(0, W), rnd.uniform(0, y_max * H)
        r = rnd.choice([1, 1, 1, 1.5, 2])
        a = rnd.uniform(0.25, 0.8)
        c = tuple(int(OBSIDIAN[i] + (color[i] - OBSIDIAN[i]) * a) for i in range(3))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)


def blend(c, a, bg=OBSIDIAN):
    return tuple(int(bg[i] + (c[i] - bg[i]) * a) for i in range(3))


def astrolabe(draw, cx, cy, r, color, alpha, fragmented, seed):
    rnd = random.Random(seed)
    col = blend(color, alpha)
    for rr, width in ((r, 2), (r * 0.82, 1), (r * 1.08, 1)):
        if fragmented:
            a = rnd.uniform(0, 30)
            while a < 360:
                span = rnd.uniform(14, 48)
                draw.arc([cx - rr, cy - rr, cx + rr, cy + rr], a, a + span, fill=col, width=width)
                a += span + rnd.uniform(8, 26)
        else:
            draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=width)
    for deg in range(0, 360, 5):
        if fragmented and rnd.random() < 0.35:
            continue
        ln = 22 if deg % 30 == 0 else 9
        t = math.radians(deg)
        x0, y0 = cx + math.cos(t) * r, cy + math.sin(t) * r
        x1, y1 = cx + math.cos(t) * (r - ln), cy + math.sin(t) * (r - ln)
        draw.line([(x0, y0), (x1, y1)], fill=col, width=2 if deg % 30 == 0 else 1)


def vignette(img, strength=0.65):
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-W * 0.15, -H * 0.25, W * 1.15, H * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(260))
    dark = Image.new("RGB", (W, H), (3, 4, 6))
    out = Image.composite(img, dark, mask)
    return Image.blend(img, out, strength)


def hero(kind):
    img = vgradient([(0, (6, 8, 12)), (0.55, (10, 14, 21)), (0.72, (14, 19, 28)), (1, (5, 6, 9))])
    img = glow(img, W / 2, H * 0.70, W * 0.42, H * 0.20, (40, 64, 92), 0.55)
    d = ImageDraw.Draw(img)
    stars(d, 170, 0.6, 3)
    cx, cy, r = W / 2, H * 0.40, H * 0.36
    if kind == "open":
        astrolabe(d, cx, cy, r, ICE, 0.22, True, 11)
        rnd = random.Random(5)
        for _ in range(16):  # scattered evidence fragments
            x, y = rnd.uniform(W * 0.08, W * 0.92), rnd.uniform(H * 0.08, H * 0.62)
            ang = rnd.uniform(0, math.pi)
            ln = rnd.uniform(40, 120)
            d.line([(x, y), (x + math.cos(ang) * ln, y + math.sin(ang) * ln)], fill=blend(ICE, 0.16), width=1)
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=blend(ICE, 0.35))
    else:
        astrolabe(d, cx, cy, r, ICE, 0.20, False, 11)
        apex = (cx, H * 0.88 - 760 * CS)
        for k in range(12):  # lines converging on the spire
            t = math.radians(200 + k * (140 / 11))
            p = (cx + math.cos(t) * r * 1.08, cy + math.sin(t) * r * 1.08)
            d.line([p, apex], fill=blend(GOLD, 0.20 if k % 3 else 0.32), width=1)
            d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=blend(GOLD, 0.45))
    ridge_layer = ImageDraw.Draw(img)
    peaks(ridge_layer, H * 0.70, (17, 22, 32), 21)
    ridge(ridge_layer, H * 0.77, 7, (13, 17, 25), 22)
    img = mist(img, 0.62, 0.86, (120, 140, 165), 0.10, 4)
    d = ImageDraw.Draw(img)
    citadel(d, W / 2, H * 0.88, CS, (8, 10, 15), rim=blend(ICE, 0.22))
    ridge(d, H * 0.86, 5, (7, 9, 13), 33, step=45)
    img = mist(img, 0.80, 1.0, (110, 128, 150), 0.12, 9)
    if kind == "close":
        apex = (W / 2, H * 0.88 - 760 * CS)
        img = glow(img, apex[0], apex[1], 70, 70, GOLD, 0.55)
        d = ImageDraw.Draw(img)
        d.ellipse([apex[0] - 5, apex[1] - 5, apex[0] + 5, apex[1] + 5], fill=GOLD)
    return vignette(img)


def content_bg():
    img = vgradient([(0, (10, 12, 18)), (1, (7, 9, 13))])
    d = ImageDraw.Draw(img)
    g = blend(ICE, 0.035, (9, 11, 16))
    for x in range(0, W, 133):
        d.line([(x, 0), (x, H)], fill=g, width=1)
    for y in range(0, H, 133):
        d.line([(0, y), (W, y)], fill=g, width=1)
    # faint celestial arc in the top-right corner (the deck's recurring motif)
    cx, cy, r = W * 1.02, -H * 0.10, H * 0.62
    col = blend(ICE, 0.07, (9, 11, 16))
    d.arc([cx - r, cy - r, cx + r, cy + r], 90, 180, fill=col, width=2)
    d.arc([cx - r * 0.86, cy - r * 0.86, cx + r * 0.86, cy + r * 0.86], 90, 180, fill=col, width=1)
    for deg in range(90, 181, 6):
        t = math.radians(deg)
        ln = 18 if deg % 30 == 0 else 8
        d.line([(cx + math.cos(t) * r, cy + math.sin(t) * r), (cx + math.cos(t) * (r - ln), cy + math.sin(t) * (r - ln))], fill=col, width=1)
    return vignette(img, 0.5)


# ---------- emblems (transparent, supersampled) ----------
S = 4
E = 600 * S


def emblem(fn, color, draw_fn):
    img = Image.new("RGBA", (E, E), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = E / 2
    ring = color + (150,)
    d.ellipse([c - 280 * S, c - 280 * S, c + 280 * S, c + 280 * S], outline=ring, width=5 * S)
    for ang in (0, 90, 180, 270):
        t = math.radians(ang)
        d.line([(c + math.cos(t) * 280 * S, c + math.sin(t) * 280 * S), (c + math.cos(t) * 252 * S, c + math.sin(t) * 252 * S)], fill=ring, width=5 * S)
    draw_fn(d, c, color + (255,))
    img.resize((600, 600), Image.LANCZOS).save(OUT / fn)


def L(d, pts, col, w=14):
    d.line([(x, y) for x, y in pts], fill=col, width=w * S, joint="curve")


def heimdall(d, c, col):
    u = S
    L(d, [(c - 150 * u, c + 150 * u), (c + 150 * u, c + 150 * u)], col, 10)  # horizon
    L(d, [(c - 32 * u, c + 150 * u), (c - 32 * u, c - 30 * u)], col)
    L(d, [(c + 32 * u, c + 150 * u), (c + 32 * u, c - 30 * u)], col)
    L(d, [(c - 52 * u, c - 30 * u), (c, c - 90 * u), (c + 52 * u, c - 30 * u), (c - 52 * u, c - 30 * u)], col)
    for k, r in enumerate((60, 100, 140)):
        a = col[:3] + (255 - k * 70,)
        d.arc([c - r * u, c - 110 * u - r * u, c + r * u, c - 110 * u + r * u], 220, 320, fill=a, width=9 * u)


def thor(d, c, col):
    u = S
    L(d, [(c - 150 * u, c - 110 * u), (c - 10 * u, c), (c - 150 * u, c + 110 * u)], col, 18)
    L(d, [(c - 70 * u, c - 110 * u), (c + 70 * u, c), (c - 70 * u, c + 110 * u)], col, 18)
    L(d, [(c + 120 * u, c - 150 * u), (c + 120 * u, c + 150 * u)], col, 12)
    for dy in (-90, 0, 90):
        L(d, [(c + 150 * u, c + dy * u), (c + 190 * u, c + dy * u * 1.25)], col, 7)


def loki(d, c, col):
    u = S
    L(d, [(c - 190 * u, c), (c - 40 * u, c)], col, 14)
    L(d, [(c - 40 * u, c), (c + 90 * u, c - 120 * u), (c + 141 * u, c - 120 * u)], col, 14)
    # second branch dashed
    pts = [(c - 40 * u, c), (c + 90 * u, c + 120 * u), (c + 141 * u, c + 120 * u)]
    segs = 11
    for i in range(segs):
        if i % 2:
            continue
        t0, t1 = i / segs, (i + 1) / segs

        def at(t):
            total = 2
            if t < 0.6:
                tt = t / 0.6
                return (pts[0][0] + (pts[1][0] - pts[0][0]) * tt, pts[0][1] + (pts[1][1] - pts[0][1]) * tt)
            tt = (t - 0.6) / 0.4
            return (pts[1][0] + (pts[2][0] - pts[1][0]) * tt, pts[1][1] + (pts[2][1] - pts[1][1]) * tt)
        L(d, [at(t0), at(t1)], col, 14)
    for y in (-120, 120):
        d.ellipse([c + 165 * u - 22 * u, c + y * u - 22 * u, c + 165 * u + 22 * u, c + y * u + 22 * u], outline=col, width=10 * u)
    d.ellipse([c - 40 * u - 16 * u, c - 16 * u, c - 40 * u + 16 * u, c + 16 * u], fill=col)


def odin(d, c, col):
    u = S
    L(d, [(c, c - 150 * u), (c, c + 160 * u)], col, 12)
    L(d, [(c - 70 * u, c + 160 * u), (c + 70 * u, c + 160 * u)], col, 12)
    L(d, [(c - 170 * u, c - 60 * u), (c + 170 * u, c - 60 * u)], col, 12)
    for sx in (-1, 1):
        x = c + sx * 150 * u
        L(d, [(x, c - 60 * u), (x - 50 * u, c + 50 * u)], col, 6)
        L(d, [(x, c - 60 * u), (x + 50 * u, c + 50 * u)], col, 6)
        d.arc([x - 60 * u, c + 10 * u, x + 60 * u, c + 90 * u], 0, 180, fill=col, width=10 * u)
    d.ellipse([c - 34 * u, c - 210 * u, c + 34 * u, c - 142 * u], outline=col, width=10 * u)
    d.ellipse([c - 12 * u, c - 188 * u, c + 12 * u, c - 164 * u], fill=col)


def stave(fn, color):
    """Small original motif mark: a stave with a centred diamond."""
    img = Image.new("RGBA", (80 * S, 160 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = 40 * S
    d.line([(cx, 8 * S), (cx, 152 * S)], fill=color + (255,), width=7 * S)
    d.polygon([(cx, 52 * S), (cx + 26 * S, 80 * S), (cx, 108 * S), (cx - 26 * S, 80 * S)], outline=color + (255,), width=6 * S)
    img.resize((80, 160), Image.LANCZOS).save(OUT / fn)


def crop(src, box_disp, fn, pad_scale=1.6):
    im = Image.open(SHOTS / src).convert("RGB")
    x0, y0, x1, y1 = (round(v * pad_scale) for v in box_disp)
    im.crop((x0, y0, x1, y1)).save(OUT / fn, optimize=True)


if __name__ == "__main__":
    hero("open").save(OUT / "bg_open.jpg", quality=92)
    hero("close").save(OUT / "bg_close.jpg", quality=92)
    content_bg().save(OUT / "bg_content.jpg", quality=92)
    emblem("em_heimdall.png", ICE, heimdall)
    emblem("em_thor.png", IVORY, thor)
    emblem("em_loki.png", SILVER, loki)
    emblem("em_odin.png", GOLD, odin)
    stave("stave_ice.png", ICE)
    stave("stave_gold.png", GOLD)
    # screenshot crops; boxes are in 2000-px display coordinates of the 3200-px captures
    crop("exposure.png", (540, 222, 1705, 838), "shot_exposure.png")
    crop("clickthrough.png", (1295, 468, 1712, 1004), "shot_reader.png")
    crop("start.png", (535, 110, 1705, 860), "thumb_ask.png")
    crop("trial.png", (535, 110, 1705, 860), "thumb_casefile.png")
    crop("map.png", (535, 380, 1705, 1130), "thumb_map.png")
    crop("clickthrough.png", (1090, 455, 1712, 856), "thumb_reader.png")
    crop("exposure.png", (535, 110, 1705, 860), "thumb_exposure.png")
    crop("trace.png", (535, 110, 1705, 860), "thumb_trace.png")
    crop("briefing.png", (535, 110, 1705, 860), "thumb_briefing.png")
    print("assets written to", OUT)
