"""The brand kit behind /brand: every mark, lockup and wordmark, as SVG and PNG.

Every download the page offers must exist, parse, and be the shape it claims; the zip must hold
the lot; and the wordmark files must carry letter OUTLINES, not a <text> element that would fall
back to Times on a machine without Cormorant Garamond.
"""
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "web/site/img/brand"


def _links():
    html = (ROOT / "web/site/brand.html").read_text()
    return sorted(set(re.findall(r'href="/img/brand/([^"]+)"', html)))


def test_every_download_on_the_brand_page_exists():
    links = _links()
    assert links, "the brand page offers no kit downloads"
    for name in links:
        assert (KIT / name).is_file(), name


def test_each_asset_comes_in_both_formats():
    names = {n.rsplit(".", 1)[0] for n in _links() if n.endswith((".svg", ".png"))}
    for base in names:
        assert (KIT / f"{base}.svg").is_file() and (KIT / f"{base}.png").is_file(), base
    for kind in ("mark", "wordmark", "lockup", "icon", "stacked"):
        assert any(n.startswith(f"halia-{kind}-") for n in names), kind


def test_svgs_are_self_contained_outlines():
    for svg in KIT.glob("*.svg"):
        root = ET.fromstring(svg.read_text())
        assert root.tag.endswith("svg") and root.get("viewBox"), svg.name
        assert root.findall(".//{http://www.w3.org/2000/svg}path"), svg.name
        assert "<text" not in svg.read_text(), f"{svg.name} relies on an installed font"


def test_pngs_are_large_and_the_right_shape():
    for png in KIT.glob("*.png"):
        im = Image.open(png)
        assert im.mode == "RGBA" and min(im.size) >= 1024, (png.name, im.size)
        if any(k in png.name for k in ("icon", "stacked")):
            assert im.size[0] == im.size[1], png.name
        if "mark-" in png.name or "wordmark-" in png.name:
            assert im.getpixel((0, 0))[3] == 0, f"{png.name} should be transparent"


def test_the_zip_holds_every_file_and_the_font_licence():
    with zipfile.ZipFile(KIT / "halia-brand-kit.zip") as z:
        names = set(z.namelist())
    for f in KIT.glob("halia-*.*"):
        if f.suffix != ".zip":
            assert f.name in names, f.name
    assert "OFL-CormorantGaramond.txt" in names


def test_the_kit_is_regenerated_from_the_one_geometry():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_brand_marks as b
    svg = b.kit_mark("#5E6B74")
    assert svg.count("M") == 15                        # three five-armed asterisks, one path each arm
    body, adv = b.wordmark_svg(100, 0, 78, "#1a1a1d")
    assert body.count("<path") == 5 and adv > 150      # H a l i a, each as outlines
