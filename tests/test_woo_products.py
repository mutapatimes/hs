"""WooCommerce products pull for the catalogue builder: mapping + pagination (fake transport)."""
from scoring.woocommerce_fetch import fetch_products


def _transport(pages):
    calls = {"n": 0}

    def t(path, params):
        if path == "data/currencies/current":
            return {"code": "GBP"}
        calls["n"] += 1
        return pages[params["page"] - 1] if params["page"] - 1 < len(pages) else []
    return t, calls


def test_woo_product_mapping():
    node = {"id": 42, "name": "Cashmere coat", "slug": "coat", "type": "variable", "status": "publish",
            "sku": "AUB-01", "price": "1200.00", "description": "<p>A <b>warm</b> coat.</p>",
            "images": [{"src": "http://cdn/1.jpg"}], "categories": [{"name": "Outerwear"}],
            "tags": [{"name": "new"}], "variations": [1, 2, 3]}
    t, _ = _transport([[node]])
    p = fetch_products(t)[0]
    assert p["id"] == "42" and p["title"] == "Cashmere coat" and p["price"] == "1200.00"
    assert p["currency"] == "GBP" and p["collections"] == ["Outerwear"] and p["tags"] == ["new"]
    assert p["sku"] == "AUB-01" and p["variants"] == 3 and p["image_url"] == "http://cdn/1.jpg"
    assert p["description"] == "A warm coat." and p["status"] == "ACTIVE"   # HTML stripped, published


def test_woo_products_paginate_until_short_page():
    full = [{"id": i, "name": f"P{i}", "status": "publish"} for i in range(100)]
    t, calls = _transport([full, full[:10]])   # 100 then 10 -> stop
    got = fetch_products(t, per_page=100)
    assert len(got) == 110 and calls["n"] == 2


def test_woo_currency_failure_is_graceful():
    def t(path, params):
        if path == "data/currencies/current":
            raise RuntimeError("no currency endpoint")
        return [{"id": 1, "name": "X", "status": "publish"}] if params["page"] == 1 else []
    p = fetch_products(t)[0]
    assert p["currency"] == "" and p["title"] == "X"
