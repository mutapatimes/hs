"""Client-facing links resolve to the store's own domain first, never haliascore.com by default."""
import pytest

from halia import config
from halia.api import client_host, shopify_auth
from halia.api.tenant_auth import hash_token, new_token
from halia.store import ShopStore

SHOP = "maison.myshopify.com"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "ch.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    store.create_tenant(SHOP, "shopify", "Maison", hash_token(new_token()))
    monkeypatch.setattr(config, "HALIA_APP_URL", "https://haliascore.com")
    monkeypatch.setattr(config, "HALIA_CLIENT_URL", "")
    monkeypatch.setattr("halia.api.catalog._primary_domain", lambda shop: "")
    client_host._CACHE.clear()
    yield store
    client_host._CACHE.clear()


def test_shopify_store_domain_via_the_app_proxy(env, monkeypatch):
    monkeypatch.setattr("halia.api.catalog._primary_domain", lambda shop: "maison.com")
    assert client_host.client_url(SHOP, "i/tok") == "https://maison.com/a/catalogue/i/tok"
    assert client_host.client_url(SHOP, "c/slug?by=Ana") == "https://maison.com/a/catalogue/c/slug?by=Ana"


def test_woocommerce_store_domain_via_the_plugin(env):
    env.create_tenant("maison-example", "woocommerce", "Maison", hash_token(new_token()))
    env.save_woocommerce("maison-example", "https://maison.example/", "ck", "cs")
    assert client_host.client_url("maison-example", "i/tok") == "https://maison.example/?halia-page=i/tok"
    assert client_host.client_url("maison-example", "c/slug?by=Ana") == "https://maison.example/?halia-page=c/slug&by=Ana"


def test_cname_then_neutral_then_app(env, monkeypatch):
    import json
    env.save_settings(SHOP, json.dumps({"catalog_domain": "clients.maison.com"}))
    assert client_host.client_url(SHOP, "i/tok") == "https://clients.maison.com/i/tok"
    client_host.invalidate(SHOP)
    env.save_settings(SHOP, json.dumps({}))
    monkeypatch.setattr(config, "HALIA_CLIENT_URL", "https://yourvisit.link")
    assert client_host.client_url(SHOP, "i/tok") == "https://yourvisit.link/i/tok"
    assert client_host.cname_target() == "yourvisit.link"
    client_host.invalidate(SHOP)
    monkeypatch.setattr(config, "HALIA_CLIENT_URL", "")
    assert client_host.client_url(SHOP, "i/tok") == "https://haliascore.com/i/tok"


def test_resolution_is_cached_until_invalidated(env, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr("halia.api.catalog._primary_domain", lambda shop: calls.__setitem__("n", calls["n"] + 1) or "maison.com")
    client_host.client_url(SHOP, "i/a"); client_host.client_url(SHOP, "i/b")
    assert calls["n"] == 1
    client_host.invalidate(SHOP); client_host.client_url(SHOP, "i/c")
    assert calls["n"] == 2


def test_blank_home_on_a_client_host(env, monkeypatch):
    from fastapi.testclient import TestClient
    from halia.api.app import app
    c = TestClient(app)
    blank = c.get("/", headers={"host": "clients.maison.com"})
    assert blank.status_code == 200 and blank.text == "<!doctype html><title></title>"
    home = c.get("/", headers={"host": "haliascore.com"})
    assert home.status_code == 200 and "Halia" in home.text and len(home.text) > 1000


def test_rate_limit_key_uses_the_shop_for_proxied_traffic():
    from types import SimpleNamespace
    from halia.api.app import _rl_key
    req = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"), url=SimpleNamespace(path="/proxy/catalogue/c/x"),
                          query_params={"shop": "maison.myshopify.com"})
    assert _rl_key(req) == "shop:maison.myshopify.com"
    req.url.path = "/c/x"
    assert _rl_key(req) == "1.2.3.4"
