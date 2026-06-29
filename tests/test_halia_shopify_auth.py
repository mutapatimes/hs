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
