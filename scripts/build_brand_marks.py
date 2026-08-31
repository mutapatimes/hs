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
    for p in out:
        print("wrote", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
