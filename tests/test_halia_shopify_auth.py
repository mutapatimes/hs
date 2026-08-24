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
    assert token["access_token"] == "shpat_offline_abc"
    assert captured["url"] == f"https://{SHOP}/admin/oauth/access_token"
    b = captured["body"]
    assert b["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert b["subject_token"] == "sess.tok.en"
    assert b["subject_token_type"] == "urn:ietf:params:oauth:token-type:id_token"
    assert b["requested_token_type"] == "urn:shopify:params:oauth:token-type:offline-access-token"
    assert b["expiring"] == 1  # ask for an EXPIRING offline token (non-expiring ones are refused)
    assert b["client_id"] == KEY and b["client_secret"] == SECRET


def test_token_exchange_raises_on_failure():
    with pytest.raises(HTTPException):
        shopify_auth.token_exchange(SHOP, "x", transport=lambda u, b: (401, {"error": "bad"}))


# ── custom-distribution bridge apps: per-shop credentials during the review window ──

BRIDGE_SHOP = "brand.myshopify.com"
BRIDGE_KEY, BRIDGE_SECRET = "bridge-key", "bridge-secret"


def _with_bridge(monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    monkeypatch.setattr("halia.config.SHOPIFY_CUSTOM_APPS",
                        {BRIDGE_SHOP: (BRIDGE_KEY, BRIDGE_SECRET)})


def test_credentials_for_shop_prefers_bridge_app(monkeypatch):
    _with_bridge(monkeypatch)
    assert shopify_auth.credentials_for_shop(BRIDGE_SHOP) == (BRIDGE_KEY, BRIDGE_SECRET)
    assert shopify_auth.credentials_for_shop(SHOP) == (KEY, SECRET)


def test_verify_resolves_bridge_app_token_by_aud(monkeypatch):
    """A session token signed by a bridge app (aud = its client_id) verifies without explicit
    creds — the aud peek picks the right secret; the public app's tokens still verify too."""
    _with_bridge(monkeypatch)
    bridge_tok = _token(dest=f"https://{BRIDGE_SHOP}", aud=BRIDGE_KEY, secret=BRIDGE_SECRET)
    assert shopify_auth.verify_session_token(bridge_tok) == BRIDGE_SHOP
    assert shopify_auth.verify_session_token(_token()) == SHOP
    # a token claiming the bridge aud but signed with the WRONG secret must still fail
    forged = _token(dest=f"https://{BRIDGE_SHOP}", aud=BRIDGE_KEY, secret="wrong")
    with pytest.raises(HTTPException):
        shopify_auth.verify_session_token(forged)


def test_token_exchange_uses_bridge_credentials(monkeypatch):
    _with_bridge(monkeypatch)
    captured = {}

    def fake_post(url, body):
        captured["body"] = body
        return 200, {"access_token": "shpat_bridge"}

    shopify_auth.token_exchange(BRIDGE_SHOP, "sess.tok.en", transport=fake_post)
    assert captured["body"]["client_id"] == BRIDGE_KEY
    assert captured["body"]["client_secret"] == BRIDGE_SECRET


# ── expiring offline tokens (Phase 2): persist expiry + refresh, renew without a session ──

def _temp_store(tmp_path, monkeypatch):
    from halia.store import ShopStore
    st = ShopStore(db_path=str(tmp_path / "shops.db"), database_url=None)
    monkeypatch.setattr(shopify_auth, "_shop_store", st)
    return st


def test_exchange_persists_expiry_and_refresh_token(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    st = _temp_store(tmp_path, monkeypatch)

    def fake_post(url, body):
        assert body["expiring"] == 1
        return 200, {"access_token": "at1", "expires_in": 3600,
                     "refresh_token": "rt1", "refresh_token_expires_in": 7776000}
    monkeypatch.setattr(shopify_auth, "_http_post", fake_post)

    assert shopify_auth.ensure_offline_token(SHOP, "sess", force=True) == "at1"
    auth = st.get_shop_auth(SHOP)
    assert auth["access_token"] == "at1" and auth["refresh_token"] == "rt1"
    assert auth["access_expires_at"] and auth["refresh_expires_at"]
    # still fresh -> returned with no network call
    assert shopify_auth.get_valid_token(SHOP) == "at1"


def test_get_valid_token_refreshes_when_expired(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    st = _temp_store(tmp_path, monkeypatch)

    def fake_post(url, body):
        assert body.get("grant_type") == "refresh_token" and body["refresh_token"] == "rt1"
        return 200, {"access_token": "at2", "expires_in": 3600,
                     "refresh_token": "rt2", "refresh_token_expires_in": 7776000}
    monkeypatch.setattr(shopify_auth, "_http_post", fake_post)

    now = int(time.time())
    st.save_shop(SHOP, "at1", access_expires_at=now - 10,   # already expired
                 refresh_token="rt1", refresh_expires_at=now + 9999)
    # refresh token renews it with NO App Bridge session token
    assert shopify_auth.get_valid_token(SHOP) == "at2"
    auth = st.get_shop_auth(SHOP)
    assert auth["access_token"] == "at2" and auth["refresh_token"] == "rt2"


def test_get_valid_token_legacy_and_missing(tmp_path, monkeypatch):
    st = _temp_store(tmp_path, monkeypatch)
    st.save_shop(SHOP, "legacy-permanent")          # no expiry, no refresh token
    assert shopify_auth.get_valid_token(SHOP) == "legacy-permanent"
    assert shopify_auth.get_valid_token("nobody.myshopify.com") is None


# ── offline-token caching + self-heal ────────────────────────────────────────
class _FakeStore:
    def __init__(self, token=None):
        self.token = token
        self.saved = []

    def get_token(self, shop):
        return self.token

    def get_shop_auth(self, shop):
        if not self.token:
            return None
        return {"access_token": self.token, "access_expires_at": None,
                "refresh_token": None, "refresh_expires_at": None}

    def save_shop(self, shop, tok, *, access_expires_at=None, refresh_token=None,
                  refresh_expires_at=None):
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
    monkeypatch.setattr(shopify_auth, "token_exchange", lambda s, t: {"access_token": "fresh"})
    assert shopify_auth.ensure_offline_token(SHOP, "sess") == "fresh"
    assert store.saved == ["fresh"]


def test_ensure_offline_token_force_re_exchanges_over_a_stale_token(monkeypatch):
    store = _FakeStore(token="stale")
    monkeypatch.setattr(shopify_auth, "shop_store", lambda: store)
    monkeypatch.setattr(shopify_auth, "token_exchange", lambda s, t: {"access_token": "fresh"})
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
