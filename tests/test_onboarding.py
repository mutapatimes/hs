"""Self-service onboarding + tenant-link auth (WooCommerce hosted path)."""
import pytest
from fastapi.testclient import TestClient

from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, SESSION_COOKIE, hash_token, new_token
from halia.store import ShopStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "t.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)        # all surfaces share this store
    monkeypatch.setattr(onboarding, "_validate_woo", lambda *a, **k: (True, ""))  # no network
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)             # no background pull
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


def test_onboard_bigcommerce_creates_tenant_and_saves_creds(client, monkeypatch):
    c, store = client
    monkeypatch.setattr(onboarding, "_validate_bigcommerce", lambda *a, **k: (True, ""))
    r = c.post("/v1/onboard", json={"source": "bigcommerce", "store_hash": "abc12def",
                                    "access_token": "tok", "platform": "", "accept_terms": True})
    assert r.status_code == 200
    t = store.get_tenant("abc12def")
    assert t and t["kind"] == "bigcommerce"
    creds = store.get_bigcommerce("abc12def")
    assert creds["store_hash"] == "abc12def" and creds["access_token"] == "tok"


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


def test_app_link_sets_session_and_redirects(client):
    # The raw access link is exchanged for a signed session cookie (not a permanent bearer token).
    c, store = client
    tok = _make_tenant(store)
    r = c.get(f"/app?t={tok}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app"
    assert SESSION_COOKIE in r.cookies and COOKIE not in r.cookies


def test_magic_link_flow_signs_in(client, monkeypatch):
    import json

    c, store = client
    _make_tenant(store, "shopx")
    # Give the tenant an account email.
    store.save_settings("shopx", json.dumps({"account_email": "owner@shopx.com"}))
    sent = {}
    monkeypatch.setattr("halia.notify.email_configured", lambda: True)
    monkeypatch.setattr("halia.notify.send_email",
                        lambda to, subj, html, text=None: sent.update(to=to, html=html) or True)
    # Request a link — neutral response, email dispatched.
    r = c.post("/app/signin", data={"email": "owner@shopx.com"})
    assert r.status_code == 200 and "Check your inbox" in r.text
    assert sent["to"] == "owner@shopx.com"
    import re
    k = re.search(r"/app/verify\?k=([A-Za-z0-9_\-]+)", sent["html"]).group(1)
    # Consume it -> session cookie, redirect to /app.
    v = c.get(f"/app/verify?k={k}", follow_redirects=False)
    assert v.status_code == 303 and SESSION_COOKIE in v.cookies
    # Single-use: a second consume fails.
    assert c.get(f"/app/verify?k={k}", follow_redirects=False).status_code == 400


def test_signin_is_neutral_for_unknown_email(client):
    c, _ = client
    r = c.post("/app/signin", data={"email": "nobody@nowhere.com"})
    assert r.status_code == 200 and "Check your inbox" in r.text  # no account disclosure


def test_hosted_head_is_halia_branded_not_shopify():
    # The hosted (WooCommerce/standalone) dashboard must hide the template's fake Shopify chrome
    # and show a Halia-branded bar with the store's name.
    h = onboarding._hosted_head("Glen Norah")
    assert ".topbar,.sidenav,.crumb{display:none!important}" in h   # fake Shopify chrome hidden
    assert "#halia-top" in h and "Halia" in h                       # Halia's own bar
    assert '"Glen Norah"' in h                                      # store name injected (JSON-escaped)
    assert "/app/refresh" in h and "/app/logout" in h              # controls preserved


def test_verify_rejects_bad_key(client):
    c, _ = client
    r = c.get("/app/verify?k=bogus", follow_redirects=False)
    assert r.status_code == 400 and "expired" in r.text.lower()


def test_app_shows_preparing_without_cache(client):
    c, store = client
    tok = _make_tenant(store)
    c.cookies.set(COOKIE, tok)
    r = c.get("/app")
    assert r.status_code == 200 and "Setting up your Halia account" in r.text


def test_notify_me_adds_email_to_recipients(client):
    """The setup screen's 'notify me' capture merges the email into the tenant's alert list."""
    import json
    c, store = client
    tok = _make_tenant(store)
    c.cookies.set(COOKIE, tok)
    r = c.post("/app/notify", json={"email": " Owner@Store.com "})
    assert r.status_code == 200 and r.json()["ok"] and r.json()["email"] == "Owner@Store.com"
    saved = json.loads(store.get_settings_raw("shopx"))
    assert "Owner@Store.com" in saved["notify_emails"] and saved["notify_enabled"] is True
    # Additive, with case-insensitive de-dup: re-adding (any case) doesn't duplicate; a new one appends.
    c.post("/app/notify", json={"email": "owner@store.com"})
    c.post("/app/notify", json={"email": "pa@store.com"})
    saved = json.loads(store.get_settings_raw("shopx"))
    lower = [e.lower() for e in saved["notify_emails"]]
    assert lower.count("owner@store.com") == 1 and "pa@store.com" in saved["notify_emails"]


def test_notify_me_rejects_bad_email(client):
    c, store = client
    tok = _make_tenant(store)
    c.cookies.set(COOKIE, tok)
    assert c.post("/app/notify", json={"email": "not-an-email"}).status_code == 400


def test_app_status_done_with_counts(client):
    from halia.cache import cache
    c, store = client
    tok = _make_tenant(store)
    cache.set("shopx", [], {"stat_count": "9", "stat_latent": "£50,000"}, {})
    try:
        c.cookies.set(COOKIE, tok)
        d = c.get("/app/status").json()
        assert d["state"] == "done" and d["count"] == "9" and d["latent"] == "£50,000"
    finally:
        cache.evict("shopx")


def test_app_status_running_without_cache(client):
    c, store = client
    tok = _make_tenant(store)
    c.cookies.set(COOKIE, tok)
    assert c.get("/app/status").json()["state"] in ("running", "idle")


def test_app_shows_signin_without_valid_session(client):
    # A bad/absent session isn't a hard 401 any more — it shows the sign-in page.
    c, _ = client
    c.cookies.set(COOKIE, "not-a-real-token")
    r = c.get("/app")
    assert r.status_code == 200 and "Sign in" in r.text


def test_onboard_json_creates_tenant_settings_and_signs_in(client):
    from halia.api.tenant_auth import SESSION_COOKIE
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://glennorah.co.uk", "consumer_key": "ck_x", "consumer_secret": "cs_x",
        "label": "Glen Norah", "vic_threshold": "8000", "sender_name": "Amara", "platform": "",
        "accept_terms": True,
    })
    assert r.status_code == 200
    d = r.json()
    # No raw token handed back; the browser is signed in via a session cookie instead.
    assert d["ok"] and d["app_url"] == "/app" and "link" not in d
    assert d["platform_connected"] is False
    assert SESSION_COOKIE in r.cookies
    t = store.get_tenant("glennorah-co-uk")
    assert t and t["kind"] == "woocommerce" and t["label"] == "Glen Norah"
    import json
    s = json.loads(store.get_settings_raw("glennorah-co-uk"))
    assert s["vic_threshold"] == 8000 and s["sender_name"] == "Amara"


def test_onboard_emails_signin_link_when_email_configured(client, monkeypatch):
    c, store = client
    sent = {}
    monkeypatch.setattr("halia.notify.email_configured", lambda: True)
    monkeypatch.setattr("halia.notify.send_email",
                        lambda to, subj, html, text=None: sent.update(to=to, html=html) or True)
    r = c.post("/v1/onboard", json={
        "store_url": "https://mayfair.co.uk", "consumer_key": "ck", "consumer_secret": "cs",
        "email": "owner@mayfair.co.uk", "label": "Mayfair", "accept_terms": True, "platform": ""})
    d = r.json()
    assert d["emailed"] is True and d["email"] == "owner@mayfair.co.uk"
    assert sent["to"] == "owner@mayfair.co.uk" and "/app?t=" in sent["html"]


def test_onboard_requires_terms_acceptance(client):
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://noterms.co.uk", "consumer_key": "ck", "consumer_secret": "cs",
        "platform": ""})  # accept_terms omitted
    assert r.status_code == 400 and "Terms" in r.json()["detail"]
    assert store.get_tenant("noterms-co-uk") is None  # nothing created without acceptance


def test_onboard_records_terms_acceptance(client):
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://yesterms.co.uk", "consumer_key": "ck", "consumer_secret": "cs",
        "platform": "", "accept_terms": True})
    assert r.status_code == 200
    import json
    s = json.loads(store.get_settings_raw("yesterms-co-uk"))
    assert s["terms_accepted"] is True and s["terms_version"] == onboarding.TERMS_VERSION
    assert s["terms_accepted_at"].endswith("Z")  # recorded UTC timestamp for the audit trail


def test_onboard_captures_account_and_notify_emails(client):
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://x.com", "consumer_key": "ck", "consumer_secret": "cs", "platform": "",
        "email": "owner@x.com", "notify_emails": ["team@x.com", "not-an-email"], "accept_terms": True})
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
                                    "consumer_secret": "cs", "accept_terms": True})
    assert r.status_code == 400 and "WooCommerce" in r.json()["detail"]


def test_onboard_klaviyo_bad_key_warns_not_blocks(client):
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://x.com", "consumer_key": "ck", "consumer_secret": "cs",
        "platform": "klaviyo", "api_key": "not-a-pk-key", "accept_terms": True})
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
                                    "admin_token": "shpat_xyz", "label": "Acme", "platform": "",
                                    "accept_terms": True})
    assert r.status_code == 200 and r.json()["app_url"] == "/app"
    t = store.get_tenant("acme.myshopify.com")
    assert t and t["kind"] == "shopify"
    assert store.get_token("acme.myshopify.com") == "shpat_xyz"


def test_onboard_shopify_bad_token_rejected(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(onboarding, "_validate_shopify", lambda *a, **k: (False, "401 Unauthorized"))
    r = c.post("/v1/onboard", json={"source": "shopify", "shop_domain": "acme.myshopify.com",
                                    "admin_token": "bad", "accept_terms": True})
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
                                    "woo_token": tok, "platform": "", "accept_terms": True})
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
                                    "platform": "", "accept_terms": True})  # no admin_token: from the install
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
    r = c.post("/v1/onboard", json={"source": "shopify", "shopify_token": tok, "platform": "", "accept_terms": True})
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
