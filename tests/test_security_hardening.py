"""Regression tests for the pre-launch security audit fixes."""
import time

import pytest
from fastapi.testclient import TestClient

from halia.api.app import app

client = TestClient(app)


# ---- CRITICAL: /v1/onboard must not authenticate via a server-stored token ----
def test_onboard_shopify_without_token_is_rejected(monkeypatch):
    # An attacker naming a victim shop, supplying no admin_token, must be refused — never handed
    # the victim's stored token. We stub get_token to prove it is NOT used as a fallback.
    from halia.api import onboarding
    from halia.store import ShopStore
    monkeypatch.setattr(ShopStore, "get_token", lambda self, shop: "victim-secret-token")
    r = client.post("/v1/onboard", json={
        "source": "shopify", "shop_domain": "victim.myshopify.com",
        "email": "attacker@evil.com", "accept_terms": True,
    })
    assert r.status_code == 400
    assert "admin api access token" in r.text.lower()


# ---- HIGH: Stripe webhook fails closed when billing is live but no secret ----
def test_stripe_webhook_fails_closed_without_secret(monkeypatch):
    from halia import config
    from halia.api import billing
    monkeypatch.setattr(billing, "billing_enabled", lambda: True)
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", None)
    r = client.post("/webhooks/stripe", json={
        "type": "checkout.session.completed",
        "data": {"object": {"client_reference_id": "attacker.myshopify.com"}},
    })
    assert r.status_code == 503


def test_stripe_sig_rejects_stale_timestamp(monkeypatch):
    import hashlib
    import hmac as _h
    from halia.api import billing
    secret = "whsec_test"
    body = b'{"type":"x"}'
    old = str(int(time.time()) - 10_000)                       # far outside the 300s tolerance
    sig = _h.new(secret.encode(), old.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert billing._verify_sig(body, f"t={old},v1={sig}", secret) is False
    fresh = str(int(time.time()))
    sig2 = _h.new(secret.encode(), fresh.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert billing._verify_sig(body, f"t={fresh},v1={sig2}", secret) is True


# ---- MEDIUM: encryption fails closed in production ----
def test_encrypt_refuses_plaintext_in_production(monkeypatch):
    from halia import crypto
    monkeypatch.delenv("HALIA_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    with pytest.raises(RuntimeError):
        crypto.encrypt("shpat_secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)          # local dev still degrades gracefully
    assert crypto.encrypt("x") == "x"


# ---- MEDIUM: session secret never uses the public literal when a real key exists ----
def test_session_secret_chains_to_encryption_key(monkeypatch):
    from halia import config
    from halia.api import tenant_auth
    monkeypatch.setattr(config, "SHOPIFY_API_SECRET", None)
    monkeypatch.setenv("HALIA_ENCRYPTION_KEY", "a-real-per-deploy-key")
    assert tenant_auth._secret() == b"a-real-per-deploy-key"
    assert tenant_auth._secret() != b"halia-dev-session-secret"


# ---- LOW: redact target comes from the signed body, mismatched header rejected ----
def test_shopify_redact_rejects_shop_mismatch(monkeypatch):
    import base64
    import hashlib
    import hmac as _h
    from halia import config
    monkeypatch.setattr(config, "SHOPIFY_API_SECRET", "shh")
    body = b'{"shop_domain":"real.myshopify.com"}'
    digest = base64.b64encode(_h.new(b"shh", body, hashlib.sha256).digest()).decode()
    r = client.post("/webhooks/shopify", content=body, headers={
        "X-Shopify-Hmac-Sha256": digest,
        "X-Shopify-Topic": "shop/redact",
        "X-Shopify-Shop-Domain": "attacker.myshopify.com",   # unsigned header disagrees with body
        "content-type": "application/json",
    })
    assert r.status_code == 400


# ---- CSV export defuses formula injection ----
def test_csv_export_neutralizes_formula_injection(monkeypatch):
    from halia.api import data as _data
    payload = {"data": [{"name": "=cmd()|'/c calc'!A1", "email": "+44@x.com", "phone": "0",
                         "loc": "London", "grade": "A", "score": 90, "spend": 100, "latent": 5000,
                         "signals": [{"d": "=HYPERLINK(evil)"}], "reco": "-2+2"}]}
    monkeypatch.setattr(_data, "results_for", lambda shop: {"payload": payload})
    from halia.api.shopify_auth import require_shop
    from halia.api.app import app as _app
    _app.dependency_overrides[require_shop] = lambda: "shopx"
    try:
        r = client.get("/v1/export")
    finally:
        _app.dependency_overrides.pop(require_shop, None)
    assert r.status_code == 200
    body = r.text
    # every dangerous leading char is now quoted as text
    assert "'=cmd()" in body and "'+44@x.com" in body and "'=HYPERLINK" in body and "'-2+2" in body
    assert "\n=cmd" not in body   # no bare formula at a field start
