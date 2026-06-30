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


def test_onboard_json_creates_tenant_settings_and_link(client):
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://glennorah.co.uk", "consumer_key": "ck_x", "consumer_secret": "cs_x",
        "label": "Glen Norah", "vic_threshold": "8000", "sender_name": "Amara", "platform": "",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and d["link"].startswith("/app?t=") and d["platform_connected"] is False
    t = store.get_tenant("glennorah-co-uk")
    assert t and t["kind"] == "woocommerce" and t["label"] == "Glen Norah"
    import json
    s = json.loads(store.get_settings_raw("glennorah-co-uk"))
    assert s["vic_threshold"] == 8000 and s["sender_name"] == "Amara"


def test_onboard_captures_account_and_notify_emails(client):
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://x.com", "consumer_key": "ck", "consumer_secret": "cs", "platform": "",
        "email": "owner@x.com", "notify_emails": ["team@x.com", "not-an-email"]})
    assert r.status_code == 200
    import json
    s = json.loads(store.get_settings_raw("x-com"))
    assert s["account_email"] == "owner@x.com"
    assert "owner@x.com" in s["notify_emails"] and "team@x.com" in s["notify_emails"]
    assert "not-an-email" not in s["notify_emails"] and s["notify_enabled"] is True


def test_onboard_rejects_bad_woo(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(onboarding, "_validate_woo", lambda *a, **k: (False, "401 Unauthorized"))
    r = c.post("/v1/onboard", json={"store_url": "https://x.com", "consumer_key": "ck",
                                    "consumer_secret": "cs"})
    assert r.status_code == 400 and "WooCommerce" in r.json()["detail"]


def test_onboard_klaviyo_bad_key_warns_not_blocks(client):
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://x.com", "consumer_key": "ck", "consumer_secret": "cs",
        "platform": "klaviyo", "api_key": "not-a-pk-key"})
    assert r.status_code == 200
    d = r.json()
    assert d["platform_connected"] is False and "pk_" in d["platform_warning"]
    assert store.get_klaviyo("x-com") is None  # bad key never saved


def test_detect_platform_from_signals():
    sho = onboarding._detect_platform("http://x", fetch=lambda u: ("", "load //cdn.shopify.com m=acme.myshopify.com"))
    assert sho == {"platform": "shopify", "myshopify": "acme.myshopify.com"}
    woo = onboarding._detect_platform("http://x", fetch=lambda u: ("", "/wp-content/plugins/woocommerce/x"))
    assert woo["platform"] == "woocommerce"
    assert onboarding._detect_platform("http://x", fetch=lambda u: ("", "plain site"))["platform"] == "unknown"


def test_detect_endpoint(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(onboarding, "_detect_platform",
                        lambda url: {"platform": "shopify", "myshopify": "acme.myshopify.com"})
    r = c.post("/v1/detect", json={"store_url": "https://acme.com"})
    assert r.status_code == 200 and r.json()["platform"] == "shopify"


def test_onboard_shopify_creates_tenant_and_saves_token(client, monkeypatch):
    c, store = client
    monkeypatch.setattr(onboarding, "_validate_shopify", lambda *a, **k: (True, ""))
    r = c.post("/v1/onboard", json={"source": "shopify", "shop_domain": "acme.myshopify.com",
                                    "admin_token": "shpat_xyz", "label": "Acme", "platform": ""})
    assert r.status_code == 200 and r.json()["link"].startswith("/app?t=")
    t = store.get_tenant("acme.myshopify.com")
    assert t and t["kind"] == "shopify"
    assert store.get_token("acme.myshopify.com") == "shpat_xyz"


def test_onboard_shopify_bad_token_rejected(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(onboarding, "_validate_shopify", lambda *a, **k: (False, "401 Unauthorized"))
    r = c.post("/v1/onboard", json={"source": "shopify", "shop_domain": "acme.myshopify.com",
                                    "admin_token": "bad"})
    assert r.status_code == 400 and "Shopify" in r.json()["detail"]


def test_woo_authorize_needs_https(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.config.HALIA_APP_URL", "")
    r = c.post("/v1/woo/authorize", json={"store_url": "https://shop.com"})
    assert r.status_code == 400 and "https" in r.json()["detail"]


def test_woo_oneclick_flow_end_to_end(client, monkeypatch):
    c, store = client
    monkeypatch.setattr("halia.config.HALIA_APP_URL", "https://halia.test")
    # 1. start the authorise: get a token + a wc-auth URL
    a = c.post("/v1/woo/authorize", json={"store_url": "https://shop.com"}).json()
    tok = a["token"]
    assert "/wc-auth/v1/authorize" in a["url"] and tok in a["url"]
    assert c.get(f"/v1/woo/authorized/{tok}").json() == {"ready": False}
    # 2. WooCommerce posts the keys back to our callback
    c.post(f"/connect/woo/callback/{tok}",
           json={"consumer_key": "ck_auto", "consumer_secret": "cs_auto"})
    assert c.get(f"/v1/woo/authorized/{tok}").json() == {"ready": True}
    # 3. onboarding finishes using the keys from the flow (no manual entry)
    r = c.post("/v1/onboard", json={"source": "woocommerce", "store_url": "https://shop.com",
                                    "woo_token": tok, "platform": ""})
    assert r.status_code == 200
    creds = store.get_woocommerce("shop-com")
    assert creds["consumer_key"] == "ck_auto" and creds["consumer_secret"] == "cs_auto"


def test_shopify_installed_endpoint(client):
    c, store = client
    assert c.get("/v1/shopify/installed", params={"shop": "acme.myshopify.com"}).json()["ready"] is False
    store.save_shop("acme.myshopify.com", "shpat_installed")
    r = c.get("/v1/shopify/installed", params={"shop": "acme"}).json()  # handle accepted, normalised
    assert r["ready"] is True and r["shop_domain"] == "acme.myshopify.com"


def test_onboard_shopify_uses_installed_token(client, monkeypatch):
    c, store = client
    monkeypatch.setattr(onboarding, "_validate_shopify", lambda *a, **k: (True, ""))
    store.save_shop("acme.myshopify.com", "shpat_installed")  # saved when they installed via the link
    r = c.post("/v1/onboard", json={"source": "shopify", "shop_domain": "acme.myshopify.com",
                                    "platform": ""})  # no admin_token: picked up from the install
    assert r.status_code == 200
    assert store.get_tenant("acme.myshopify.com")["kind"] == "shopify"


def test_shopify_authorize_needs_config(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", None)
    r = c.post("/v1/shopify/authorize", json={"shop_domain": "acme.myshopify.com"})
    assert r.status_code == 400


def test_shopify_oauth_flow_end_to_end(client, monkeypatch):
    import hashlib
    import hmac as _hmac
    c, store = client
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", "key")
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", "secret")
    monkeypatch.setattr("halia.config.HALIA_APP_URL", "https://halia.test")
    monkeypatch.setattr(onboarding, "_shopify_exchange", lambda shop, code: "shpat_oauth")
    monkeypatch.setattr(onboarding, "_validate_shopify", lambda *a, **k: (True, ""))
    # 1. start install
    a = c.post("/v1/shopify/authorize", json={"shop_domain": "acme.myshopify.com"}).json()
    tok = a["token"]
    assert "/admin/oauth/authorize" in a["url"] and "state=" + tok in a["url"]
    assert c.get(f"/v1/shopify/authorized/{tok}").json()["ready"] is False
    # 2. Shopify redirects back to our callback (sign it like Shopify does)
    params = {"code": "abc", "shop": "acme.myshopify.com", "state": tok}
    msg = "&".join(f"{k}={params[k]}" for k in sorted(params))
    params["hmac"] = _hmac.new(b"secret", msg.encode(), hashlib.sha256).hexdigest()
    assert c.get("/connect/shopify/callback", params=params).status_code == 200
    auth = c.get(f"/v1/shopify/authorized/{tok}").json()
    assert auth["ready"] is True and auth["shop_domain"] == "acme.myshopify.com"
    # 3. onboarding finishes using the OAuth token (no manual entry)
    r = c.post("/v1/onboard", json={"source": "shopify", "shopify_token": tok, "platform": ""})
    assert r.status_code == 200
    assert store.get_tenant("acme.myshopify.com")["kind"] == "shopify"
    assert store.get_token("acme.myshopify.com") == "shpat_oauth"


def test_shopify_callback_rejects_bad_hmac(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", "key")
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", "secret")
    monkeypatch.setattr("halia.config.HALIA_APP_URL", "https://halia.test")
    tok = c.post("/v1/shopify/authorize", json={"shop_domain": "acme.myshopify.com"}).json()["token"]
    r = c.get("/connect/shopify/callback",
              params={"code": "abc", "shop": "acme.myshopify.com", "state": tok, "hmac": "bad"})
    assert r.status_code == 400


def test_newsletter_subscribe(client):
    c, _ = client
    assert c.post("/subscribe", json={"email": "jane@halia.app"}).status_code == 200
    assert c.post("/subscribe", json={"email": "jane@halia.app"}).status_code == 200  # idempotent
    assert c.post("/subscribe", json={"email": "not-an-email"}).status_code == 422


def test_settings_authorised_by_tenant_cookie(client):
    """The same /v1/* routes serve a hosted tenant via the cookie (require_shop fallback)."""
    c, store = client
    tok = _make_tenant(store)
    c.cookies.set(COOKIE, tok)
    r = c.get("/v1/settings")
    assert r.status_code == 200 and "vic_threshold" in r.json()
