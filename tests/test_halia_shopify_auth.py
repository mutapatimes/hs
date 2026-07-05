"""Embedded-app auth: session-token verification + token exchange (no network)."""
import time

import jwt
import pytest
from fastapi import HTTPException

from halia.api import shopify_auth

SECRET = "test-app-secret"
KEY = "test-api-key"
SHOP = "acme.myshopify.com"


def _token(dest=f"https://{SHOP}", aud=KEY, exp_offset=3600, secret=SECRET):
    payload = {"iss": f"https://{SHOP}/admin", "dest": dest, "aud": aud,
               "sub": "1", "exp": int(time.time()) + exp_offset}
    return jwt.encode(payload, secret, algorithm="HS256")


def test_verify_valid_token_returns_shop():
    assert shopify_auth.verify_session_token(_token(), secret=SECRET, api_key=KEY) == SHOP


def test_verify_rejects_bad_signature():
    with pytest.raises(HTTPException) as e:
        shopify_auth.verify_session_token(_token(secret="wrong"), secret=SECRET, api_key=KEY)
    assert e.value.status_code == 401


def test_verify_rejects_wrong_audience():
    with pytest.raises(HTTPException):
        shopify_auth.verify_session_token(_token(aud="someone-else"), secret=SECRET, api_key=KEY)


def test_verify_rejects_expired():
    with pytest.raises(HTTPException):
        shopify_auth.verify_session_token(_token(exp_offset=-3600), secret=SECRET, api_key=KEY)


def test_token_exchange_builds_correct_body(monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    captured = {}

    def fake_post(url, body):
        captured["url"] = url
        captured["body"] = body
        return 200, {"access_token": "shpat_offline_abc"}

    token = shopify_auth.token_exchange(SHOP, "sess.tok.en", transport=fake_post)
    assert token == "shpat_offline_abc"
    assert captured["url"] == f"https://{SHOP}/admin/oauth/access_token"
    b = captured["body"]
    assert b["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert b["subject_token"] == "sess.tok.en"
    assert b["subject_token_type"] == "urn:ietf:params:oauth:token-type:id_token"
    assert b["requested_token_type"] == "urn:shopify:params:oauth:token-type:offline-access-token"
    assert b["client_id"] == KEY and b["client_secret"] == SECRET


def test_token_exchange_raises_on_failure():
    with pytest.raises(HTTPException):
        shopify_auth.token_exchange(SHOP, "x", transport=lambda u, b: (401, {"error": "bad"}))


# ── offline-token caching + self-heal ────────────────────────────────────────
class _FakeStore:
    def __init__(self, token=None):
        self.token = token
        self.saved = []

    def get_token(self, shop):
        return self.token

    def save_shop(self, shop, tok):
        self.saved.append(tok)
        self.token = tok


def _boom(*_a, **_k):
    raise AssertionError("token_exchange should not be called")


def test_ensure_offline_token_uses_stored_token(monkeypatch):
    monkeypatch.setattr(shopify_auth, "shop_store", lambda: _FakeStore(token="stored"))
    monkeypatch.setattr(shopify_auth, "token_exchange", _boom)
    assert shopify_auth.ensure_offline_token(SHOP, "sess") == "stored"


def test_ensure_offline_token_exchanges_when_missing(monkeypatch):
    store = _FakeStore(token=None)
    monkeypatch.setattr(shopify_auth, "shop_store", lambda: store)
    monkeypatch.setattr(shopify_auth, "token_exchange", lambda s, t: "fresh")
    assert shopify_auth.ensure_offline_token(SHOP, "sess") == "fresh"
    assert store.saved == ["fresh"]


def test_ensure_offline_token_force_re_exchanges_over_a_stale_token(monkeypatch):
    store = _FakeStore(token="stale")
    monkeypatch.setattr(shopify_auth, "shop_store", lambda: store)
    monkeypatch.setattr(shopify_auth, "token_exchange", lambda s, t: "fresh")
    assert shopify_auth.ensure_offline_token(SHOP, "sess", force=True) == "fresh"
    assert store.saved == ["fresh"]        # the stale token was overwritten


def test_sync_shop_authed_reexchanges_once_on_auth_error(monkeypatch):
    from halia.api import data
    from scoring.shopify_fetch import ShopifyAuthError

    calls = {"forces": [], "syncs": 0}

    def fake_ensure(shop, sess, force=False):
        calls["forces"].append(force)
        return "good" if force else "stale"

    def fake_sync(shop, token):
        calls["syncs"] += 1
        if token == "stale":
            raise ShopifyAuthError("revoked")
        return {"ok": True, "token": token}

    monkeypatch.setattr("halia.api.shopify_auth.ensure_offline_token", fake_ensure)
    monkeypatch.setattr(data, "sync_shop", fake_sync)
    entry = data.sync_shop_authed(SHOP, "sess")
    assert entry == {"ok": True, "token": "good"}
    assert calls["forces"] == [False, True]    # tried stored, then forced a fresh exchange
    assert calls["syncs"] == 2


def test_sync_shop_authed_does_not_retry_non_auth_errors(monkeypatch):
    from halia.api import data

    monkeypatch.setattr("halia.api.shopify_auth.ensure_offline_token",
                        lambda shop, sess, force=False: "tok")
    monkeypatch.setattr(data, "sync_shop",
                        lambda shop, token: (_ for _ in ()).throw(RuntimeError("scoring blew up")))
    with pytest.raises(RuntimeError):
        data.sync_shop_authed(SHOP, "sess")
