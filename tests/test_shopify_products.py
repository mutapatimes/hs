"""Shopify products pull for the catalog builder: mapping + cursor pagination."""
from scoring.shopify_fetch import fetch_products
from scoring.shopify_graphql import PRODUCTS_QUERY, product_node_to_dict


def test_product_node_mapping():
    node = {
        "id": "gid://shopify/Product/1", "title": "Cashmere coat", "handle": "coat",
        "vendor": "Aubin", "productType": "Outerwear", "tags": ["new", "aw25"], "status": "ACTIVE",
        "featuredImage": {"url": "http://cdn/1.jpg"},
        "priceRangeV2": {"minVariantPrice": {"amount": "1200.00", "currencyCode": "GBP"}},
        "collections": {"nodes": [{"title": "Outerwear"}, {"title": "New in"}]},
    }
    p = product_node_to_dict(node)
    assert p["title"] == "Cashmere coat" and p["vendor"] == "Aubin"
    assert p["price"] == "1200.00" and p["currency"] == "GBP"
    assert p["collections"] == ["Outerwear", "New in"] and p["tags"] == ["new", "aw25"]
    assert p["image_url"] == "http://cdn/1.jpg"


def test_image_falls_back_to_images_node():
    p = product_node_to_dict({"title": "Scarf", "images": {"nodes": [{"url": "http://cdn/s.jpg"}]}})
    assert p["image_url"] == "http://cdn/s.jpg"
    assert p["title"] == "Scarf" and p["tags"] == []


def test_product_node_maps_catalog_extras():
    # description / first-variant SKU / variant count are surfaced for the catalog builder
    p = product_node_to_dict({
        "title": "Coat", "description": "  A warm coat.  ",
        "variantsCount": {"count": 12}, "variants": {"nodes": [{"sku": "AUB-01"}]},
    })
    assert p["description"] == "A warm coat." and p["sku"] == "AUB-01" and p["variants"] == 12
    # absent gracefully -> empty/zero, never KeyError
    q = product_node_to_dict({"title": "Bare"})
    assert q["description"] == "" and q["sku"] == "" and q["variants"] == 0


def _page(nodes, has_next, cursor):
    return {"data": {"products": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "nodes": nodes}}}


def test_fetch_products_paginates_cursor():
    calls = []

    def transport(query, variables):
        assert query == PRODUCTS_QUERY
        calls.append(variables.get("cursor"))
        if variables.get("cursor") is None:
            return _page([{"id": "1", "title": "A"}], True, "c1")
        return _page([{"id": "2", "title": "B"}], False, "c2")

    got = fetch_products(transport)
    assert [p["title"] for p in got] == ["A", "B"]
    assert calls == [None, "c1"]


def test_fetch_products_caps_pages():
    def transport(query, variables):
        return _page([{"id": "9", "title": "X"}], True, "again")

    assert len(fetch_products(transport, max_pages=3)) == 3
