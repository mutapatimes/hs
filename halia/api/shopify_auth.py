"""Embedded-app auth: App Bridge session tokens + Shopify managed install / token exchange.

Flow (Shopify's current recommendation, no OAuth redirects):
  1. App Bridge puts a signed **session token** (JWT) on every request from the admin —
     either the `Authorization: Bearer …` header, or `?id_token=…` on the first load.
  2. We **verify** it (HS256, signed with the app's API secret) and read the shop from `dest`.
  3. First time we see a shop, we **exchange** that session token for a long-lived offline
     Admin API access token and persist it (`ShopStore`), so background syncs can call the
     Admin API for that shop.

`verify_session_token` and `token_exchange` are pure + injectable so they unit-test with
no network and no real app.
"""
from __future__ import annotations

import jwt
from fastapi import HTTPException, Request

from halia import config
from halia.store import ShopStore

# Shopify token-exchange constants (researched from shopify.dev token-exchange docs).
_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
_SUBJECT_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id_token"
_OFFLINE_TOKEN_TYPE = "urn:shopify:params:oauth:token-type:offline-access-token"


def _shop_from_dest(dest: str) -> str:
    """'https://acme.myshopify.com' -> 'acme.myshopify.com'."""
    return str(dest).replace("https://", "").replace("http://", "").strip("/")


def verify_session_token(token: str, secret: str | None = None, api_key: str | None = None) -> str:
    """Verify an App Bridge session token (JWT) and return the shop domain.

    Raises HTTPException(401) on any problem.
    """
    secret = secret or config.SHOPIFY_API_SECRET
    api_key = api_key or config.SHOPIFY_API_KEY
    if not secret or not api_key:
        raise HTTPException(500, "App not configured (SHOPIFY_API_KEY/SECRET missing)")
    try:
        claims = jwt.decode(
            token, secret, algorithms=["HS256"], audience=api_key, leeway=10,
            options={"require": ["exp", "dest", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Invalid session token: {exc}")
    shop = _shop_from_dest(claims["dest"])
    if not shop.endswith(".myshopify.com"):
        raise HTTPException(401, "Session token has an unexpected shop")
    return shop


def token_for_request(request: Request) -> str:
    """Pull the session token from the Authorization header or the ?id_token= param."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    token = request.query_params.get("id_token")
    if not token:
        raise HTTPException(401, "Missing session token")
    return token


def token_exchange(shop: str, session_token: str, transport=None) -> str:
    """Exchange a session token for an offline Admin API access token for `shop`."""
    body = {
        "client_id": config.SHOPIFY_API_KEY,
        "client_secret": config.SHOPIFY_API_SECRET,
        "grant_type": _GRANT_TYPE,
        "subject_token": session_token,
        "subject_token_type": _SUBJECT_TOKEN_TYPE,
        "requested_token_type": _OFFLINE_TOKEN_TYPE,
    }
    url = f"https://{shop}/admin/oauth/access_token"
    status, payload = (transport or _http_post)(url, body)
    if not (200 <= status < 300) or "access_token" not in payload:
        raise HTTPException(401, f"Token exchange failed (HTTP {status}): {str(payload)[:200]}")
    return payload["access_token"]


def _http_post(url: str, body: dict) -> tuple[int, dict]:
    import requests

    resp = requests.post(url, json=body, timeout=30)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"raw": resp.text}


# One ShopStore handle for the process (created lazily so importing is cheap).
_shop_store: ShopStore | None = None


def shop_store() -> ShopStore:
    global _shop_store
    if _shop_store is None:
        _shop_store = ShopStore()
    return _shop_store


def ensure_offline_token(shop: str, session_token: str) -> str:
    """Return the shop's offline token, exchanging + persisting it on first sight."""
    store = shop_store()
    token = store.get_token(shop)
    if not token:
        token = token_exchange(shop, session_token)
        store.save_shop(shop, token)
    return token


def require_shop(request: Request) -> str:
    """FastAPI dependency: verify the App Bridge session token and return the shop.

    Pure (no network) so read routes stay cheap and unit-testable. Routes that need to
    call the Admin API (the embedded entry + /v1/sync) call ``ensure_offline_token``
    themselves to get/refresh the offline token.
    """
    return verify_session_token(token_for_request(request))
