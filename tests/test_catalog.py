"""Catalog builder: HTML render, store round-trip, endpoints, active-catalog URL, PDF serving."""
import pytest
from fastapi.testclient import TestClient

import halia.api.catalog as catmod
import halia.catalog_render as cr
from halia.api import shopify_auth
from halia.api.app import app
from halia.api.shopify_auth import require_shop
from halia.catalog_render import PdfEngineUnavailable, catalog_html
from halia.store import ShopStore

SHOP = "brand.myshopify.com"
PRODUCTS = [
    {"id": "gid://P/1", "title": "Cashmere coat", "vendor": "Aubin", "type": "", "tags": ["new"],
     "collections": ["Outerwear"], "image_url": "http://cdn/1.jpg", "price": "1200.00",
     "currency": "GBP", "status": "ACTIVE"},
    {"id": "gid://P/2", "title": "Silk scarf", "vendor": "Aubin", "type": "", "tags": ["sale"],
     "collections": ["Accessories"], "image_url": None, "price": "120.00", "currency": "GBP",
     "status": "ACTIVE"},
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "c.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(catmod, "_products", lambda shop, force=False: list(PRODUCTS))
    app.dependency_overrides[require_shop] = lambda: SHOP
    yield TestClient(app), store
    app.dependency_overrides.pop(require_shop, None)


# ── pure render ──
def test_catalog_html_lists_products():
    html = catalog_html({"name": "Autumn", "brand_color": "#123456", "template": "grid"},
                        PRODUCTS, "Aubin London")
    assert "Cashmere coat" in html and "Silk scarf" in html
    assert "£1,200.00" in html and "#123456" in html and "Aubin London" in html


def test_catalog_html_honours_layout_and_field_options():
    prods = [{"id": "1", "title": "Cashmere coat", "vendor": "Aubin", "image_url": "http://c/1.jpg",
              "price": "1200.00", "currency": "GBP", "description": "Warm and elegant.",
              "sku": "AUB-01", "variants": 12}]
    # list layout, no cover, Letter, description + sku + variants shown, price hidden
    h = catalog_html({"name": "X", "template": "list", "page_size": "Letter", "cover": False,
                      "fields": {"price": False, "description": True, "sku": True, "variants": True}},
                     prods, "Aubin")
    assert "items list" in h and "size: Letter" in h
    assert 'class="cover"' not in h                      # cover suppressed
    assert "Warm and elegant." in h and "AUB-01" in h and "12 variants" in h
    assert "£1,200.00" not in h                           # price field off
    # minimal + custom columns/colours
    h2 = catalog_html({"template": "minimal", "columns": 4, "text_color": "#222222"}, prods)
    assert "items minimal" in h2 and "repeat(4, 1fr)" in h2 and "#222222" in h2
    # legacy lookbook still renders as a 2-column grid
    h3 = catalog_html({"template": "lookbook"}, prods)
    assert "items grid" in h3 and "repeat(2, 1fr)" in h3


def test_html_to_pdf_unavailable_locally():
    # WeasyPrint isn't installed in local/CI, so this degrades to a typed error, not a crash.
    with pytest.raises(PdfEngineUnavailable):
        cr.html_to_pdf("<p>hi</p>")


# ── endpoints ──
def test_products_endpoint_lists_and_facets(client):
    c, _ = client
    r = c.get("/v1/catalog/products")
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 2 and d["all_total"] == 2
    assert "Outerwear" in d["facets"]["collections"] and "Aubin" in d["facets"]["vendors"]
    assert d["ids"] == ["gid://P/1", "gid://P/2"]


def test_products_search_filter(client):
    c, _ = client
    r = c.get("/v1/catalog/products?search=scarf")
    assert [p["title"] for p in r.json()["items"]] == ["Silk scarf"]
    r2 = c.get("/v1/catalog/products?collection=Outerwear")
    assert [p["title"] for p in r2.json()["items"]] == ["Cashmere coat"]


def test_save_generate_serve_and_active_url(client, monkeypatch):
    c, store = client
    monkeypatch.setattr(cr, "html_to_pdf", lambda html: b"%PDF-1.4 fake")
    # save an active catalog with one product
    save = c.post("/v1/catalog/save", json={"name": "Autumn", "active": True,
                                             "product_ids": ["gid://P/1"], "template": "grid"})
    cid = save.json()["id"]
    assert store.get_catalog(cid)["active"] == 1
    # not generated yet -> no active URL
    from halia.api.catalog import catalog_url_for
    assert catalog_url_for(SHOP) == ""
    # generate -> pdf stored, url returned
    gen = c.post(f"/v1/catalog/{cid}/generate")
    assert gen.status_code == 200 and gen.json()["count"] == 1
    assert gen.json()["url"].endswith(f"/catalog/{cid}.pdf")
    # public PDF serves the bytes
    pdf = c.get(f"/catalog/{cid}.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content == b"%PDF-1.4 fake"
    # active + generated -> {catalog_link} now resolves
    assert catalog_url_for(SHOP).endswith(f"/catalog/{cid}.pdf")


def test_generate_503_without_pdf_engine(client):
    c, _ = client                       # no html_to_pdf monkeypatch -> WeasyPrint missing
    cid = c.post("/v1/catalog/save", json={"name": "X", "product_ids": ["gid://P/1"]}).json()["id"]
    assert c.post(f"/v1/catalog/{cid}/generate").status_code == 503


def test_list_and_delete(client):
    c, _ = client
    cid = c.post("/v1/catalog/save", json={"name": "Winter", "product_ids": ["gid://P/1", "gid://P/2"]}).json()["id"]
    lst = c.get("/v1/catalog/list").json()["catalogs"]
    assert len(lst) == 1 and lst[0]["name"] == "Winter" and lst[0]["count"] == 2
    assert c.request("DELETE", f"/v1/catalog/{cid}").status_code == 200
    assert c.get("/v1/catalog/list").json()["catalogs"] == []


def test_save_persists_and_returns_full_config(client):
    c, _ = client
    cid = c.post("/v1/catalog/save", json={
        "name": "AW", "product_ids": ["gid://P/1"], "template": "minimal", "columns": 4,
        "page_size": "Letter", "brand_color": "#abcdef", "text_color": "#111111",
        "footer_text": "© Aubin", "cover": False,
        "fields": {"description": True, "price": False},
    }).json()["id"]
    got = next(x for x in c.get("/v1/catalog/list").json()["catalogs"] if x["id"] == cid)
    assert got["template"] == "minimal" and got["columns"] == 4 and got["page_size"] == "Letter"
    assert got["brand_color"] == "#abcdef" and got["text_color"] == "#111111"
    assert got["footer_text"] == "© Aubin" and got["cover"] is False
    assert got["fields"]["description"] is True and got["fields"]["price"] is False


def test_save_clamps_columns_and_rejects_bad_enums(client):
    c, _ = client
    cid = c.post("/v1/catalog/save", json={"name": "Z", "product_ids": ["gid://P/1"],
                                           "columns": 99, "page_size": "A3", "template": "bogus"}).json()["id"]
    got = next(x for x in c.get("/v1/catalog/list").json()["catalogs"] if x["id"] == cid)
    assert got["columns"] == 4 and got["page_size"] == "A4" and got["template"] == "grid"


def test_generate_requires_a_product(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(cr, "html_to_pdf", lambda html: b"%PDF")
    cid = c.post("/v1/catalog/save", json={"name": "Empty", "product_ids": ["gid://MISSING"]}).json()["id"]
    assert c.post(f"/v1/catalog/{cid}/generate").status_code == 400   # nothing resolves
