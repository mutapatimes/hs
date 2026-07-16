"""scripts/check_shopify.py — platform classifier (no network; pure marker logic)."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_shopify", Path(__file__).resolve().parents[1] / "scripts" / "check_shopify.py")
cs = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(cs)


def test_norm_strips_scheme_and_path():
    assert cs._norm("https://www.Brand.com/shop/") == "www.brand.com"
    assert cs._norm("brand.com") == "brand.com"


def test_shopify_markers_classic_and_headless():
    assert cs._shopify_markers({}, '<script src="//cdn.shopify.com/x.js">')          # classic
    assert cs._shopify_markers({}, 'monorail-edge.shopifysvc.com/v1/produce')          # headless beacon
    assert cs._shopify_markers({"x-shopify-stage": "production"}, "")                   # header
    assert cs._shopify_markers({}, "shopifycloud/checkout")                            # cloud


def test_non_shopify_not_flagged():
    assert not cs._shopify_markers({}, "<html>a bespoke next.js site</html>")
    assert not cs._shopify_markers({"server": "nginx"}, "demandware.static/x")
