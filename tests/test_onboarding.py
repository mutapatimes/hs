"""Self-service onboarding + tenant-link auth (WooCommerce hosted path)."""
import pytest
from fastapi.testclient import TestClient

from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "t.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)        # all surfaces share this store
    monkeypatch.setattr(onboarding, "_validate_woo", lambda *a, **k: (True, ""))  # no network
    monkeypatch.setattr(onboarding, "_start_sync", lambda shop: None)             # no background pull
    monkeypatch.setattr("halia.config.SIGNUP_CODE", None)
    return TestClient(app), store


def _make_tenant(store, shop="shopx"):
    tok = new_token()
    store.create_tenant(shop, "woocommerce", "Shop X", hash_token(tok))
    return tok


def test_connect_form_renders(client):
    c, _ = client
    r = c.get("/connect")
    assert r.status_code == 200 and "Connect your store" in r.text


def test_connect_creates_tenant_and_link(client):
    c, store = client
    r = c.post("/connect", data={"store_url": "https://glennorah.co.uk", "consumer_key": "ck_x",
                                 "consumer_secret": "cs_x", "label": "Glen Norah"})
    assert r.status_code == 200 and "/app?t=" in r.text
    t = store.get_tenant("glennorah-co-uk")
    assert t and t["kind"] == "woocommerce" and t["label"] == "Glen Norah"
    creds = store.get_woocommerce("glennorah-co-uk")
    assert creds["consumer_key"] == "ck_x" and creds["store_url"] == "https://glennorah.co.uk"


def test_signup_code_enforced(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.config.SIGNUP_CODE", "letmein")
    bad = c.post("/connect", data={"store_url": "https://x.com", "consumer_key": "ck",
                                   "consumer_secret": "cs", "code": "nope"})
    assert bad.status_code == 403
    good = c.post("/connect", data={"store_url": "https://x.com", "consumer_key": "ck",
                                    "consumer_secret": "cs", "code": "letmein"})
    assert good.status_code == 200 and "/app?t=" in good.text


def test_bad_credentials_rejected(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(onboarding, "_validate_woo", lambda *a, **k: (False, "401 Unauthorized"))
    r = c.post("/connect", data={"store_url": "https://x.com", "consumer_key": "ck",
                                 "consumer_secret": "cs"})
    assert r.status_code == 400 and "reach WooCommerce" in r.text and "401 Unauthorized" in r.text


def test_app_link_sets_cookie_and_redirects(client):
    c, store = client
    tok = _make_tenant(store)
    r = c.get(f"/app?t={tok}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app"
    assert COOKIE in r.cookies


def test_app_shows_preparing_without_cache(client):
    c, store = client
    tok = _make_tenant(store)
    c.cookies.set(COOKIE, tok)
    r = c.get("/app")
    assert r.status_code == 200 and "Scoring your store" in r.text


def test_app_rejects_bad_token(client):
    c, _ = client
    c.cookies.set(COOKIE, "not-a-real-token")
    assert c.get("/app").status_code == 401


def test_settings_authorised_by_tenant_cookie(client):
    """The same /v1/* routes serve a hosted tenant via the cookie (require_shop fallback)."""
    c, store = client
    tok = _make_tenant(store)
    c.cookies.set(COOKIE, tok)
    r = c.get("/v1/settings")
    assert r.status_code == 200 and "vic_threshold" in r.json()
