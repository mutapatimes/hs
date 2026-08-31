"""WooCommerce baskets and cart links: unpaid checkouts become open baskets with a pay link, and
the cart builder (dashboard + extension) links straight into the store's cart."""
import pytest
from fastapi.testclient import TestClient

from halia.api import catalog, data, onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

SHOP = "maison-woo"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "wc.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "woocommerce", "Maison Woo", hash_token(tok))
    store.save_woocommerce(SHOP, "https://maison.example", "ck", "cs")
    ext = new_token(); store.set_extension_token(SHOP, hash_token(ext))
    products = [{"id": "12", "title": "Camel coat", "handle": "camel-coat", "image_url": None, "price": "1200",
                 "sku": "CC1", "collections": ["Outerwear"], "sizes": ["S", "M"], "tags": [], "vendor": "Aubin"},
                {"id": "45", "title": "Silk scarf", "handle": "silk-scarf", "image_url": None, "price": "180",
                 "sku": "SS9", "collections": ["Accessories"], "sizes": [], "tags": [], "vendor": "Aubin"}]
    monkeypatch.setattr(catalog, "_products", lambda shop, force=False: products)
    cache.clear()
    yield TestClient(app, cookies={COOKIE: tok}), store, ext
    cache.clear()


def test_unpaid_checkouts_become_open_baskets(env, monkeypatch):
    client, store, ext = env
    import scoring.woocommerce_fetch as wf
    pending = [{"id": 501, "status": "pending", "order_key": "wc_order_abc", "total": "1380.00",
                "date_created": "2026-08-20T10:00:00", "customer_id": 77, "billing": {"email": "grace@x.com"},
                "line_items": [{"name": "Camel coat", "quantity": 1}, {"name": "Silk scarf", "quantity": 1}]},
               {"id": 502, "status": "failed", "order_key": "wc_order_def", "total": "180.00",
                "date_created": "2026-08-21T10:00:00", "customer_id": 0, "billing": {"email": "guest@x.com"},
                "line_items": [{"name": "Silk scarf", "quantity": 1}]}]
    monkeypatch.setattr(wf, "fetch_orders", lambda transport, **kw: pending)
    monkeypatch.setattr(wf, "http_transport", lambda *a, **k: (lambda path, params: []))
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no helper")))
    carts = data._woo_carts(SHOP)
    assert set(carts) == {"77", "guest@x.com"}
    c = carts["77"]
    assert c["value"] == 1380 and c["count"] == 2 and c["started"] == "2026-08-20"
    assert c["url"] == "https://maison.example/checkout/order-pay/501/?pay_for_order=true&key=wc_order_abc"


def test_dashboard_cart_link_single_and_multi(env):
    client, store, ext = env
    d = client.post("/v1/cart-link", json={"items": [{"id": "12", "qty": 1}]}).json()
    assert d["url"].startswith("https://maison.example/?add-to-cart=12&quantity=1") and d["needs_helper"] is False
    assert "utm_campaign=halia-cart" in d["url"]
    d = client.post("/v1/cart-link", json={"items": [{"id": "12", "qty": 1}, {"id": "45", "qty": 2}]}).json()
    assert d["url"].startswith("https://maison.example/?halia-cart=12:1,45:2") and d["needs_helper"] is True


def test_extension_products_and_cart_link_on_woo(env):
    client, store, ext = env
    d = client.get("/v1/extension/products?q=scarf", headers={"X-Halia-Ext-Token": ext}).json()
    assert d["cart_base"] == "https://maison.example" and [p["title"] for p in d["products"]] == ["Silk scarf"]
    assert d["products"][0]["variants"][0]["id"] == "45"
    assert d["ids"] == ["45"]                                   # the view, ready to send whole
    d = client.post("/v1/extension/cart_link", headers={"X-Halia-Ext-Token": ext}, json={"product_ids": ["45"]}).json()
    assert "add-to-cart=45" in d["url"] and d["needs_helper"] is False


def test_a_view_can_be_narrowed_by_collection_and_size_then_sent_whole(env):
    # An associate sends what suits one client: narrow the range, then take the whole view rather
    # than ticking it piece by piece.
    client, store, ext = env
    h = {"X-Halia-Ext-Token": ext}
    d = client.get("/v1/extension/products", headers=h).json()
    assert d["facets"] == {"collections": ["Accessories", "Outerwear"], "sizes": ["S", "M"]}
    assert d["ids"] == ["12", "45"]                             # everything, when nothing is chosen
    d = client.get("/v1/extension/products?collection=Outerwear", headers=h).json()
    assert [p["title"] for p in d["products"]] == ["Camel coat"] and d["ids"] == ["12"]
    d = client.get("/v1/extension/products?size=m", headers=h).json()
    assert d["ids"] == ["12"]                                   # sizes match whatever the case
    assert client.get("/v1/extension/products?collection=Outerwear&size=S", headers=h).json()["ids"] == ["12"]
    assert client.get("/v1/extension/products?collection=Accessories&size=S", headers=h).json()["ids"] == []
