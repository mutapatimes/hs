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

import hashlib
import hmac

import jwt
from fastapi import HTTPException, Request

from halia import config
from halia.store import ShopStore


def verify_app_proxy(request: Request, secret: str | None = None) -> bool:
    """Verify a Shopify **App Proxy** request. Shopify signs proxied requests with an HMAC-SHA256
    of the sorted query params (minus ``signature``), keyed by the app's shared secret. This lets us
    serve the catalogue under the merchant's OWN storefront domain (theirbrand.com/a/catalogue/…)
    so a client never sees Halia. Returns True only for genuine, correctly-signed proxy requests."""
    secret = secret or config.SHOPIFY_API_SECRET
    if not secret:
        return False
    params: dict[str, list[str]] = {}
    sig = None
    for k, v in request.query_params.multi_items():
        if k == "signature":
            sig = v
        else:
            params.setdefault(k, []).append(v)
    if not sig:
        return False
    msg = "".join(f"{k}={','.join(params[k])}" for k in sorted(params))
    digest = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)

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


def session_claims(token: str, secret: str | None = None, api_key: str | None = None) -> dict:
    """Verified claims of an App Bridge session token, or {} if it can't be verified.

    Non-raising sibling of verify_session_token, used to read the optional staff-user claim.
    """
    secret = secret or config.SHOPIFY_API_SECRET
    api_key = api_key or config.SHOPIFY_API_KEY
    if not (secret and api_key):
        return {}
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], audience=api_key, leeway=10,
                          options={"require": ["exp", "dest", "aud"]})
    except jwt.PyJWTError:
        return {}


def current_staff_id(request: Request) -> str | None:
    """The logged-in Shopify staff user id (session-token ``sub``), best-effort.

    Online session tokens carry the staff user id in ``sub``; offline tokens / non-Shopify
    tenants don't, so this returns None there. Used to attribute pipeline actions.
    """
    try:
        token = token_for_request(request)
    except HTTPException:
        return None
    sub = session_claims(token).get("sub")
    return str(sub) if sub else None


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


def ensure_offline_token(shop: str, session_token: str, force: bool = False) -> str:
    """Return the shop's offline token, exchanging + persisting it on first sight.

    ``force`` re-exchanges even when a token is already stored, overwriting it — used to
    self-heal a revoked/stale token (app reinstalled, scopes changed) that the Admin API has
    started rejecting, instead of returning the bad token forever.
    """
    store = shop_store()
    token = None if force else store.get_token(shop)
    if not token:
        token = token_exchange(shop, session_token)
        store.save_shop(shop, token)
    return token


def require_shop(request: Request) -> str:
    """FastAPI dependency: verify the App Bridge session token and return the shop.

    Pure (no network) so read routes stay cheap and unit-testable. Routes that need to
    call the Admin API (the embedded entry + /v1/sync) call ``ensure_offline_token``
    themselves to get/refresh the offline token.

    Falls back to a self-service tenant's private-link cookie (WooCommerce etc.) so the
    same /v1/* routes — Settings, lookups — serve hosted clients too.
    """
    try:
        return verify_session_token(token_for_request(request))
    except HTTPException:
        from halia.api.tenant_auth import resolve_tenant

        shop = resolve_tenant(request)
        if shop:
            return shop
        raise
