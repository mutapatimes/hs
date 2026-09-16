"""The Halia asterism, drawn once, emitted everywhere.

The mark is the typographic asterism ⁂ (U+2042): three FIVE-armed asterisks in a triangle,
apex up. Everything below is generated from the same geometry so the favicon, the app icons,
the extension icons, the listing icons and the inline nav mark are identical.

Run: .venv/bin/python scripts/build_brand_marks.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
CREAM = (244, 241, 234, 255)
GREEN_TOP = (27, 74, 63)
GREEN_BOTTOM = (14, 43, 36)
GREEN_FLAT = (22, 62, 52)


# ── geometry (unit space: the mark fits in a 1×1 box) ────────────────────────

def _arm(cx, cy, angle_deg, length, w_center, w_tip):
    """One tapered arm as a 4-point polygon: narrow at the centre, wider at the tip."""
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), math.sin(a)
    px, py = -dy, dx                     # perpendicular
    tip = (cx + dx * length, cy + dy * length)
    return [
        (cx + px * w_center / 2, cy + py * w_center / 2),
        (tip[0] + px * w_tip / 2, tip[1] + py * w_tip / 2),
        (tip[0] - px * w_tip / 2, tip[1] - py * w_tip / 2),
        (cx - px * w_center / 2, cy - py * w_center / 2),
    ]


ARMS = 5   # the house asterisk has FIVE arms, like the typographic ⁂ in a serif face. Enforced below.


def asterisk_polys(cx, cy, r):
    """Five arms, one pointing straight up (the typographic ✱ orientation)."""
    assert ARMS == 5, "The Halia asterisk is five-armed; do not change this without a brand decision."
    return [_arm(cx, cy, -90 + k * (360 / ARMS), r, r * 0.30, r * 0.44) for k in range(ARMS)]


def asterism_polys(scale=1.0, cx=0.5, cy=0.5):
    """Three asterisks in an equilateral triangle, apex up, centred on (cx, cy)."""
    s = 0.46 * scale                     # triangle side
    r = 0.155 * scale                    # asterisk radius
    h = s * math.sqrt(3) / 2
    centres = [(cx, cy - 2 * h / 3), (cx - s / 2, cy + h / 3), (cx + s / 2, cy + h / 3)]
    polys = []
    for (x, y) in centres:
        polys += asterisk_polys(x, y, r)
    return polys


# ── SVG ──────────────────────────────────────────────────────────────────────

def svg_paths(polys, size=100):
    d = []
    for poly in polys:
        pts = " ".join(f"{x*size:.2f},{y*size:.2f}" for x, y in poly)
        d.append(f"M{pts}Z")
    return "".join(d)


def svg_mark(color="currentColor", size=100):
    """The bare mark, inheriting the text colour. Used inline in the nav and footer."""
    return (f'<svg viewBox="0 0 {size} {size}" width="1em" height="1em" aria-hidden="true" '
            f'style="vertical-align:-.12em"><path fill="{color}" d="{svg_paths(asterism_polys(1.0), size)}"/></svg>')


def svg_tile(size=64):
    """Favicon: cream mark on a deep-green rounded tile."""
    r = size * 0.22
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
            f'<rect width="{size}" height="{size}" rx="{r:.1f}" fill="#163e34"/>'
            f'<path fill="#f4f1ea" d="{svg_paths(asterism_polys(0.72), size)}"/></svg>')


# ── PNG ──────────────────────────────────────────────────────────────────────

def _gradient(w, h=None):
    h = w if h is None else h
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(GREEN_TOP[i] + (GREEN_BOTTOM[i] - GREEN_TOP[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = c + (255,)
    return img


def png_tile(size, *, gradient=True, mark_scale=0.72, rounded=False, transparent_mark_only=False):
    ss = 4                               # supersample for clean edges
    S = size * ss
    if transparent_mark_only:
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        fill = (255, 255, 255, 255)
    else:
        img = _gradient(S) if gradient else Image.new("RGBA", (S, S), GREEN_FLAT + (255,))
        fill = CREAM
    draw = ImageDraw.Draw(img)
    for poly in asterism_polys(mark_scale):
        draw.polygon([(x * S, y * S) for x, y in poly], fill=fill)
    if rounded:
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
        img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


def png_rect(w, h, *, mark_scale=0.72):
    """The mark centred on a green rectangle. iMessage wants 4:3 icons, not squares."""
    ss = 4
    W, H = w * ss, h * ss
    img = _gradient(W, H)
    draw = ImageDraw.Draw(img)
    m = min(W, H)
    ox, oy = (W - m) / 2, (H - m) / 2
    for poly in asterism_polys(mark_scale):
        draw.polygon([(ox + x * m, oy + y * m) for x, y in poly], fill=CREAM)
    return img.resize((w, h), Image.LANCZOS)


# The Messages drawer icon set: eight rectangles plus two marketing sizes. App Store Connect
# rejects an upload missing any of them (error 90649), and actool writes
# MSMessagesExtensionStoreIconName (error 90642) only when the whole set assigns cleanly, which
# it does only for a .stickersiconset with these exact idiom / scale / platform keys.
IMESSAGE_ICONS = [
    # (w, h, {asset-catalog metadata})
    (1024, 1024, {"idiom": "ios-marketing", "size": "1024x1024", "scale": "1x"}),
    (1024, 768, {"idiom": "ios-marketing", "size": "1024x768", "scale": "1x", "platform": "ios"}),
    (120, 90, {"idiom": "iphone", "size": "60x45", "scale": "2x"}),
    (180, 135, {"idiom": "iphone", "size": "60x45", "scale": "3x"}),
    (134, 100, {"idiom": "ipad", "size": "67x50", "scale": "2x"}),
    (148, 110, {"idiom": "ipad", "size": "74x55", "scale": "2x"}),
    (54, 40, {"idiom": "universal", "size": "27x20", "scale": "2x", "platform": "ios"}),
    (81, 60, {"idiom": "universal", "size": "27x20", "scale": "3x", "platform": "ios"}),
    (64, 48, {"idiom": "universal", "size": "32x24", "scale": "2x", "platform": "ios"}),
    (96, 72, {"idiom": "universal", "size": "32x24", "scale": "3x", "platform": "ios"}),
]


def build_imessage_iconset(folder: Path):
    import json

    folder.mkdir(parents=True, exist_ok=True)
    images = []
    for w, h, meta in IMESSAGE_ICONS:
        name = f"icon-{w}x{h}.png"
        png_rect(w, h, mark_scale=0.86 if min(w, h) < 100 else 0.72).save(folder / name)
        images.append({"filename": name, **meta})
    (folder / "Contents.json").write_text(
        json.dumps({"images": images, "info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
    return folder


# ── The brand kit: every mark, lockup and wordmark on /brand, as SVG and PNG ──────────────
#
# The wordmark is Cormorant Garamond Light. For the SVGs its letters are converted to outlines
# from the OFL-licensed variable font in scripts/assets, so a downloaded file needs no font
# installed and looks identical everywhere. The PNGs are drawn with the same font at 2x and
# downsampled, so both formats come from one geometry.

FONT_PATH = ROOT / "scripts/assets/CormorantGaramond[wght].ttf"
WORDMARK = "Halia"
INK, OFFWHITE, SLATE, SILVER, NEARBLACK = "#1a1a1d", "#f6f6f4", "#5E6B74", "#D7DADE", "#0a0a0b"


def _rgb(hexs):
    h = hexs.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


_FONT = {}


def light_font():
    """Cormorant Garamond at weight 300, instanced once from the variable font."""
    if "ttf" not in _FONT:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
        f = instancer.instantiateVariableFont(TTFont(str(FONT_PATH)), {"wght": 300})
        import io
        buf = io.BytesIO(); f.save(buf)
        _FONT["ttf"] = f
        _FONT["bytes"] = buf.getvalue()
    return _FONT["ttf"]


def wordmark_svg(size, x, baseline, fill):
    """The wordmark as outlines: one <path> per letter, advanced by the font's own widths."""
    from fontTools.pens.svgPathPen import SVGPathPen
    f = light_font()
    gs, cmap = f.getGlyphSet(), f.getBestCmap()
    upm = f["head"].unitsPerEm
    k = size / upm
    parts, cx = [], x
    for ch in WORDMARK:
        g = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[g].draw(pen)
        d = pen.getCommands()
        if d:
            parts.append(f'<path fill="{fill}" transform="translate({cx:.2f},{baseline:.2f}) scale({k:.5f},{-k:.5f})" d="{d}"/>')
        cx += f["hmtx"][g][0] * k
    return "".join(parts), cx - x          # markup, advance width in user units


def wordmark_width(size):
    f = light_font()
    cmap = f.getBestCmap()
    k = size / f["head"].unitsPerEm
    return sum(f["hmtx"][cmap[ord(c)]][0] for c in WORDMARK) * k


def _svg(w, h, body, bg=None):
    rect = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{rect}{body}</svg>'


def _mark_svg(x, y, size, fill):
    """The asterism inside a size×size box whose top-left is (x, y)."""
    d = []
    for poly in asterism_polys(1.0):
        pts = " ".join(f"{x + px * size:.2f},{y + py * size:.2f}" for px, py in poly)
        d.append(f"M{pts}Z")
    return f'<path fill="{fill}" d="{"".join(d)}"/>'


def kit_mark(fill):
    return _svg(100, 100, _mark_svg(0, 0, 100, fill))


def kit_wordmark(fill):
    size = 100
    w = wordmark_width(size)
    body, _ = wordmark_svg(size, 0, 78, fill)          # baseline at 78: ascender room above, no descenders
    return _svg(round(w, 2), 100, body)


def kit_lockup(bg, mark_fill, word_fill):
    """Horizontal: mark left of the wordmark, both at one em, as the site's nav sets them."""
    em, gap, pad = 100, 31, 80
    ww = wordmark_width(em)
    w, h = round(pad * 2 + em + gap + ww, 2), pad * 2 + em
    baseline = pad + em * 0.78
    mark = _mark_svg(pad, baseline - em * 0.88, em, mark_fill)   # vertical-align -.12em, as on the site
    word, _ = wordmark_svg(em, pad + em + gap, baseline, word_fill)
    return _svg(w, h, mark + word, bg=bg)


def kit_square(bg, mark_fill, word_fill=None, size=1024):
    """Square: the mark alone as an icon, or above the wordmark as a stacked lockup."""
    if word_fill is None:
        m = size * 0.44
        return _svg(size, size, _mark_svg((size - m) / 2, (size - m) / 2, m, mark_fill), bg=bg)
    m, fs, gap = size * 0.30, size * 0.15, size * 0.05
    total = m + gap + fs * 0.78
    top = (size - total) / 2
    ww = wordmark_width(fs)
    word, _ = wordmark_svg(fs, (size - ww) / 2, top + m + gap + fs * 0.78, word_fill)
    return _svg(size, size, _mark_svg((size - m) / 2, top, m, mark_fill) + word, bg=bg)


def png_from_layout(w, h, *, bg, marks, words, scale=1.0):
    """Render a kit layout with PIL at the requested pixel size (2x supersampled).

    marks: [(x, y, size, hex)]  words: [(x, baseline, font_size, hex)]  in the SVG's user units."""
    from PIL import ImageFont
    import io
    ss = 2
    W, H = int(round(w * scale * ss)), int(round(h * scale * ss))
    img = Image.new("RGBA", (W, H), _rgb(bg) if bg else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    k = scale * ss
    for (x, y, size, fill) in marks:
        for poly in asterism_polys(1.0):
            draw.polygon([((x + px * size) * k, (y + py * size) * k) for px, py in poly], fill=_rgb(fill))
    for (x, baseline, fs, fill) in words:
        light_font()
        font = ImageFont.truetype(io.BytesIO(_FONT["bytes"]), int(round(fs * k)))
        draw.text((x * k, baseline * k), WORDMARK, font=font, fill=_rgb(fill), anchor="ls")
    return img.resize((W // ss, H // ss), Image.LANCZOS)


def build_brand_kit(folder: Path):
    """Everything shown on /brand, as SVG and PNG, plus one zip of the lot."""
    import zipfile
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    em, gap, pad = 100, 31, 80
    ww = wordmark_width(em)
    lw, lh = round(pad * 2 + em + gap + ww, 2), pad * 2 + em
    lbase = pad + em * 0.78
    S = 1024
    m_icon = S * 0.44
    m_st, fs_st, gap_st = S * 0.30, S * 0.15, S * 0.05
    top_st = (S - (m_st + gap_st + fs_st * 0.78)) / 2
    ww_st = wordmark_width(fs_st)

    items = [
        # name, svg, png (w, h, bg, marks, words, scale)
        ("halia-mark-slate", kit_mark(SLATE), (100, 100, None, [(0, 0, 100, SLATE)], [], 10.24)),
        ("halia-mark-ink", kit_mark(INK), (100, 100, None, [(0, 0, 100, INK)], [], 10.24)),
        ("halia-mark-cream", kit_mark(OFFWHITE), (100, 100, None, [(0, 0, 100, OFFWHITE)], [], 10.24)),
        ("halia-wordmark-ink", kit_wordmark(INK), (round(ww, 2), 100, None, [], [(0, 78, 100, INK)], 10.24)),
        ("halia-wordmark-cream", kit_wordmark(OFFWHITE), (round(ww, 2), 100, None, [], [(0, 78, 100, OFFWHITE)], 10.24)),
        ("halia-lockup-cream", kit_lockup(OFFWHITE, SLATE, INK),
         (lw, lh, OFFWHITE, [(pad, lbase - em * 0.88, em, SLATE)], [(pad + em + gap, lbase, em, INK)], 4)),
        ("halia-lockup-dark", kit_lockup(NEARBLACK, SILVER, OFFWHITE),
         (lw, lh, NEARBLACK, [(pad, lbase - em * 0.88, em, SILVER)], [(pad + em + gap, lbase, em, OFFWHITE)], 4)),
        ("halia-icon-ink", kit_square(INK, OFFWHITE), (S, S, INK, [((S - m_icon) / 2, (S - m_icon) / 2, m_icon, OFFWHITE)], [], 1)),
        ("halia-icon-slate", kit_square(SLATE, OFFWHITE), (S, S, SLATE, [((S - m_icon) / 2, (S - m_icon) / 2, m_icon, OFFWHITE)], [], 1)),
        ("halia-stacked-cream", kit_square(OFFWHITE, INK, INK),
         (S, S, OFFWHITE, [((S - m_st) / 2, top_st, m_st, INK)], [((S - ww_st) / 2, top_st + m_st + gap_st + fs_st * 0.78, fs_st, INK)], 1)),
        ("halia-stacked-dark", kit_square(NEARBLACK, SILVER, OFFWHITE),
         (S, S, NEARBLACK, [((S - m_st) / 2, top_st, m_st, SILVER)], [((S - ww_st) / 2, top_st + m_st + gap_st + fs_st * 0.78, fs_st, OFFWHITE)], 1)),
    ]
    for name, svg, (w, h, bg, marks, words, scale) in items:
        (folder / f"{name}.svg").write_text(svg); out.append(folder / f"{name}.svg")
        png_from_layout(w, h, bg=bg, marks=marks, words=words, scale=scale).save(folder / f"{name}.png")
        out.append(folder / f"{name}.png")
    licence = ROOT / "scripts/assets/OFL-CormorantGaramond.txt"
    with zipfile.ZipFile(folder / "halia-brand-kit.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in out:
            z.write(p, p.name)
        if licence.exists():
            z.write(licence, "OFL-CormorantGaramond.txt")
    out.append(folder / "halia-brand-kit.zip")
    return out


def main():
    out = []
    # iOS app icon set (Apple applies its own corner mask; supply square).
    ios = ROOT / "ios/HaliaTemplates/HaliaTemplates/Assets.xcassets/AppIcon.appiconset"
    png_tile(1024).save(ios / "AppIcon-1024.png"); out.append(ios / "AppIcon-1024.png")
    png_tile(1024).save(ios / "AppIcon-1024-dark.png"); out.append(ios / "AppIcon-1024-dark.png")
    png_tile(1024, transparent_mark_only=True).save(ios / "AppIcon-1024-tinted.png")
    out.append(ios / "AppIcon-1024-tinted.png")
    # The Messages extension has its own icon set, in its own shape.
    out.append(build_imessage_iconset(
        ROOT / "ios/HaliaTemplates/HaliaIMessage/Assets.xcassets/iMessage App Icon.stickersiconset"))
    # Chrome extension
    for s in (16, 48, 128):
        p = ROOT / f"extension/icons/icon{s}.png"
        png_tile(s, gradient=s >= 48, mark_scale=0.8 if s == 16 else 0.72).save(p); out.append(p)
    # Shopify listing assets
    for s in (16, 48, 128, 512, 1200):
        p = ROOT / f"docs/listing-assets/icon-{s}.png"
        png_tile(s, gradient=s >= 48, mark_scale=0.8 if s == 16 else 0.72).save(p); out.append(p)
    # Site: favicon SVG + PNG fallbacks + apple-touch-icon
    img = ROOT / "web/site/img"
    (img / "favicon.svg").write_text(svg_tile(64)); out.append(img / "favicon.svg")
    png_tile(32, gradient=False, mark_scale=0.8, rounded=True).save(img / "favicon-32.png"); out.append(img / "favicon-32.png")
    png_tile(180, rounded=False).save(img / "apple-touch-icon.png"); out.append(img / "apple-touch-icon.png")
    # The inline mark (for the nav/footer replacement)
    (img / "asterism.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        f'<path fill="#5E6B74" d="{svg_paths(asterism_polys(1.0), 100)}"/></svg>')
    out.append(img / "asterism.svg")
    # The downloadable brand kit behind /brand
    out += build_brand_kit(img / "brand")
    for p in out:
        print("wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
