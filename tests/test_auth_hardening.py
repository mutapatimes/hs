"""Pins on the authentication and input-handling hardening: each test is an attack that used to
work and must never work again."""
import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from halia.api import shopify_auth, staff_auth, tenant_auth
from halia.api.app import app
from halia.store import ShopStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "h.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", "shpss_test_secret")
    monkeypatch.setattr("halia.config.CONSOLE_KEY", "own3r")
    monkeypatch.setattr("halia.config.ADMIN_KEY", "s3cret")
    yield TestClient(app), store


# ── one key per purpose ─────────────────────────────────────────────────────────────
def test_a_tenant_session_for_a_shop_named_staff_is_not_a_staff_cookie(env):
    c, store = env
    raw = base64.urlsafe_b64decode(tenant_auth.make_session("staff")).decode()
    shop, exp, sig = raw.rsplit("|", 2)
    c.cookies.set(staff_auth.SESSION_COOKIE, f"{exp}|{sig}")     # the old forgery
    assert c.get("/console/data.json").status_code == 403
    assert "Access key" in c.get("/admin").text


def test_purpose_keys_differ_from_the_raw_secret_and_from_each_other():
    raw = tenant_auth._secret()
    assert tenant_auth._secret("tenant") != raw != tenant_auth._secret("staff")
    assert tenant_auth._secret("tenant") != tenant_auth._secret("staff") != tenant_auth._secret("console")


def test_a_far_future_session_is_void(env):
    c, store = env
    v = tenant_auth.make_session("acme.example", ttl=10 * 365 * 86400)
    assert tenant_auth.read_session(v) is None


# ── webhooks: the signed body names the target, or nothing happens ─────────────────
def _sig(body: bytes, secret: str = "shpss_test_secret") -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def test_a_signature_over_arbitrary_bytes_cannot_delete_a_shop_through_the_header(env):
    c, store = env
    store.create_tenant("victim.myshopify.com", "shopify", "Victim", "h")
    body = b"victim.myshopify.com|1900000000"                    # not JSON: whatever bytes were signed
    r = c.post("/webhooks/shopify", content=body,
               headers={"X-Shopify-Hmac-Sha256": _sig(body), "X-Shopify-Topic": "shop/redact",
                        "X-Shopify-Shop-Domain": "victim.myshopify.com"})
    assert r.status_code == 400
    assert store.get_tenant("victim.myshopify.com")


def test_webhook_refuses_a_body_naming_no_shop_and_an_unknown_topic(env):
    c, store = env
    body = b'{"payload":{}}'
    r = c.post("/webhooks/shopify", content=body,
               headers={"X-Shopify-Hmac-Sha256": _sig(body), "X-Shopify-Topic": "shop/redact",
                        "X-Shopify-Shop-Domain": "victim.myshopify.com"})
    assert r.status_code == 400
    body = b'{"shop_domain":"x.myshopify.com"}'
    r = c.post("/webhooks/shopify", content=body,
               headers={"X-Shopify-Hmac-Sha256": _sig(body), "X-Shopify-Topic": "orders/create"})
    assert r.status_code == 400


# ── a store is created once ────────────────────────────────────────────────────────
def test_a_lookalike_address_cannot_take_over_a_connected_store(env, monkeypatch):
    c, store = env
    from halia.api import onboarding
    monkeypatch.setattr(onboarding, "_validate_woo", lambda url, ck, cs, probe=None: (True, ""))
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    first = c.post("/v1/onboard", json={"source": "woocommerce", "store_url": "https://www.brand.com",
                                        "consumer_key": "ck", "consumer_secret": "cs", "label": "Brand", "accept_terms": True})
    assert first.status_code == 200
    original = store._run("SELECT token_hash FROM tenants WHERE shop = :s", {"s": "www-brand-com"}, fetch="one")["token_hash"]
    second = c.post("/v1/onboard", json={"source": "woocommerce", "store_url": "https://www-brand.com",
                                         "consumer_key": "ck2", "consumer_secret": "cs2", "label": "Evil", "accept_terms": True})
    assert second.status_code == 409
    row = store._run("SELECT token_hash, label FROM tenants WHERE shop = :s", {"s": "www-brand-com"}, fetch="one")
    assert row["token_hash"] == original and row["label"] == "Brand"


def test_create_tenant_never_overwrites():
    import tempfile, pathlib
    st = ShopStore(db_path=pathlib.Path(tempfile.mkdtemp()) / "t.db")
    assert st.create_tenant("a.example", "woocommerce", "A", "h1") is True
    assert st.create_tenant("a.example", "shopify", "B", "h2") is False
    assert st.get_tenant("a.example")["label"] == "A"


# ── text stays text ────────────────────────────────────────────────────────────────
def test_blog_tag_filter_is_not_reflected_as_markup(env):
    c, store = env
    r = c.get('/blog?tag="><script>alert(1)</script>')
    assert "<script>alert(1)</script>" not in r.text


def test_signin_echo_is_escaped(env):
    c, store = env
    r = c.post("/app/signin", data={"email": "<img src=x onerror=alert(1)>@x.com"})
    assert "<img src=x" not in r.text and "&lt;img" in r.text


def test_cms_override_cannot_carry_a_handler(env):
    from halia.api import content
    store = env[1]
    store.set_content("home.hero.title", '<em onmouseover="alert(1)">Hi</em><script>x()</script>')
    content._bust()
    out = content.apply_overrides('<h1><!--cms:home.hero.title-->Default<!--/cms--></h1>')
    assert "<em>Hi</em>" in out and "onmouseover" not in out and "<script" not in out
    content._bust()


def test_blog_body_is_reduced_to_safe_markup():
    from halia.api.blog import _sanitize
    out = _sanitize('<p class="x" onclick="a()">hi</p><img src="x" onerror="b()"><a href="javascript:c()">l</a>')
    assert 'onclick' not in out and 'onerror' not in out and 'javascript:' not in out and 'class="x"' in out


def test_blog_upload_accepts_only_raster_images():
    from halia.api.blog import _image_mime
    assert _image_mime(b"\x89PNG\r\n\x1a\n" + b"\0" * 8) == "image/png"
    assert _image_mime(b"<svg xmlns='http://www.w3.org/2000/svg' onload='x()'/>") is None
    assert _image_mime(b"<html><script>x()</script>") is None


def test_capture_page_escapes_the_store_name(env, monkeypatch):
    from halia.api.capture import _qr_page
    monkeypatch.setattr("halia.i18n.client_lang", lambda shop: "en")
    page = _qr_page("<script>alert(1)</script>", "shop.example")
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_colours_and_mailchimp_dc_are_validated():
    from halia.api.catalog import _hex_color
    from halia.adapters.mailchimp_sink import dc_from_key, MailchimpError
    assert _hex_color("</style><script>", "#1f564a") == "#1f564a" and _hex_color("#ABCDEF", "#000") == "#ABCDEF"
    assert dc_from_key("abc-us21") == "us21"
    with pytest.raises(MailchimpError):
        dc_from_key("abc-evil.com/#")


def test_public_scoring_caps_the_batch(env):
    c, store = env
    r = c.post("/v1/score", json=[{"Email": "a@b.com"}] * 101)
    assert r.status_code == 413


# ── the server fetches only public addresses ─────────────────────────────────────
def test_private_and_metadata_addresses_are_refused():
    from halia.netguard import UnsafeAddress, assert_public
    for bad in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://localhost:8000/",
                "http://10.0.0.5/", "file:///etc/passwd", "http://metadata.google.internal/"):
        with pytest.raises(UnsafeAddress):
            assert_public(bad)


def test_woo_validation_refuses_internal_addresses_and_hides_raw_errors(monkeypatch):
    from halia.api import onboarding
    ok, why = onboarding._validate_woo("http://127.0.0.1/wp", "ck", "cs")
    assert ok is False and "127.0.0.1" not in why and len(why) < 40


def test_pdf_fetcher_never_reads_files():
    from halia.catalog_render import _pdf_url_fetcher
    with pytest.raises(ValueError):
        _pdf_url_fetcher("file:///etc/passwd")


def test_slack_text_is_escaped():
    from halia.notify import slack_escape
    assert slack_escape("<!channel> <https://evil|Reset>") == "&lt;!channel&gt; &lt;https://evil|Reset&gt;"


def test_session_token_issuer_must_match_the_shop(monkeypatch):
    import jwt
    from halia.api.shopify_auth import verify_session_token
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", "sek")
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", "key")
    import time
    claims = {"dest": "https://acme.myshopify.com", "aud": "key", "exp": int(time.time()) + 60,
              "iss": "https://other.myshopify.com/admin"}
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        verify_session_token(jwt.encode(claims, "sek", algorithm="HS256"))
    claims["iss"] = "https://acme.myshopify.com/admin"
    assert verify_session_token(jwt.encode(claims, "sek", algorithm="HS256")) == "acme.myshopify.com"


def test_api_responses_are_never_cached(env):
    c, store = env
    r = c.get("/v1/hidden-vics")
    assert r.headers.get("cache-control") == "no-store"
