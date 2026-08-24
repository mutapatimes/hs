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
import time

import jwt
from fastapi import HTTPException, Request

from halia import config
from halia.store import ShopStore


def credentials_for_shop(shop: str) -> tuple[str | None, str | None]:
    """(client_id, client_secret) for the app THIS shop installs through: its custom-distribution
    bridge app when one is configured (HALIA_SHOPIFY_CUSTOM_APPS), else the public Halia app."""
    custom = config.SHOPIFY_CUSTOM_APPS.get((shop or "").strip().lower())
    if custom:
        return custom
    return config.SHOPIFY_API_KEY, config.SHOPIFY_API_SECRET


def _all_secrets() -> list[str]:
    """Every app secret this deployment answers for: the public app + each custom bridge app."""
    out = [s for s in [config.SHOPIFY_API_SECRET] if s]
    out.extend(secret for _, secret in config.SHOPIFY_CUSTOM_APPS.values())
    return out


def _creds_for_session_token(token: str) -> tuple[str | None, str | None]:
    """Resolve which app a session token belongs to by peeking its (unverified) ``aud`` claim,
    then return that app's (client_id, secret). The caller still verifies the signature — the
    peek only picks WHICH key to verify with, it grants nothing by itself."""
    try:
        aud = jwt.decode(token, options={"verify_signature": False}).get("aud")
    except jwt.PyJWTError:
        aud = None
    if aud:
        for cid, secret in config.SHOPIFY_CUSTOM_APPS.values():
            if cid == aud:
                return cid, secret
    return config.SHOPIFY_API_KEY, config.SHOPIFY_API_SECRET


def verify_app_proxy(request: Request, secret: str | None = None) -> bool:
    """Verify a Shopify **App Proxy** request. Shopify signs proxied requests with an HMAC-SHA256
    of the sorted query params (minus ``signature``), keyed by the app's shared secret. This lets us
    serve the catalogue under the merchant's OWN storefront domain (theirbrand.com/a/catalogue/…)
    so a client never sees Halia. Returns True only for genuine, correctly-signed proxy requests."""
    secrets = [secret] if secret else _all_secrets()
    if not secrets:
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
    for s in secrets:
        digest = hmac.new(s.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(digest, sig):
            return True
    return False

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
    if secret is None and api_key is None:
        api_key, secret = _creds_for_session_token(token)   # custom bridge app or the public app
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
    if secret is None and api_key is None:
        api_key, secret = _creds_for_session_token(token)   # custom bridge app or the public app
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


def token_exchange(shop: str, session_token: str, transport=None) -> dict:
    """Exchange a session token for an EXPIRING offline Admin API token for `shop`.

    Returns the raw payload: ``access_token`` plus ``expires_in`` / ``refresh_token`` /
    ``refresh_token_expires_in`` (the expiring-token fields). Callers persist it via ``_persist_token``.
    """
    cid, secret = credentials_for_shop(shop)
    body = {
        "client_id": cid,
        "client_secret": secret,
        "grant_type": _GRANT_TYPE,
        "subject_token": session_token,
        "subject_token_type": _SUBJECT_TOKEN_TYPE,
        "requested_token_type": _OFFLINE_TOKEN_TYPE,
        # Shopify no longer accepts non-expiring (permanent) offline tokens on the Admin API:
        # such tokens now 403 with "Non-expiring access tokens are no longer accepted". `expiring=1`
        # asks for an EXPIRING offline token (carries expires_in + a refresh_token) which Shopify
        # accepts. https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens
        "expiring": 1,
    }
    url = f"https://{shop}/admin/oauth/access_token"
    status, payload = (transport or _http_post)(url, body)
    if not (200 <= status < 300) or "access_token" not in payload:
        raise HTTPException(401, f"Token exchange failed (HTTP {status}): {str(payload)[:200]}")
    return payload


def refresh_offline_token(shop: str, refresh_token: str, transport=None) -> dict:
    """Renew an expiring offline token with its refresh token. Needs NO App Bridge session, so any
    code path (background syncs, extension lookups, the catalogue proxy) can self-renew."""
    cid, secret = credentials_for_shop(shop)
    body = {
        "client_id": cid,
        "client_secret": secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    url = f"https://{shop}/admin/oauth/access_token"
    status, payload = (transport or _http_post)(url, body)
    if not (200 <= status < 300) or "access_token" not in payload:
        raise HTTPException(401, f"Token refresh failed (HTTP {status}): {str(payload)[:200]}")
    return payload


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


def _persist_token(shop: str, payload: dict) -> str:
    """Store an offline-token payload (from exchange or refresh) with its expiries, return the token."""
    now = int(time.time())
    ein = payload.get("expires_in")
    rein = payload.get("refresh_token_expires_in")
    shop_store().save_shop(
        shop, payload["access_token"],
        access_expires_at=(now + int(ein)) if ein else None,
        refresh_token=payload.get("refresh_token"),
        refresh_expires_at=(now + int(rein)) if rein else None)
    return payload["access_token"]


def get_valid_token(shop: str) -> str | None:
    """The shop's offline token, refreshed if it has expired (or is about to).

    Uses the stored refresh token when needed, so this works with NO App Bridge session and is
    safe for background jobs and the extension/catalogue surfaces. Returns None if the shop has no
    token at all. A legacy non-expiring token (no expiry recorded) is handed back as-is: the Admin
    API will 403 it, and the embedded path's force re-exchange then swaps in an expiring one.
    """
    auth = shop_store().get_shop_auth(shop)
    if not auth:
        return None
    now, skew = int(time.time()), 120
    aexp = auth["access_expires_at"]
    if not aexp or now < aexp - skew:
        return auth["access_token"]                       # still valid, or legacy (no expiry)
    rtok, rexp = auth["refresh_token"], auth["refresh_expires_at"]
    if rtok and (not rexp or now < rexp - skew):
        try:
            return _persist_token(shop, refresh_offline_token(shop, rtok))
        except Exception:  # noqa: BLE001 — fall through to the stale token; the caller self-heals
            pass
    return auth["access_token"]


def ensure_offline_token(shop: str, session_token: str, force: bool = False) -> str:
    """Return the shop's offline token, exchanging (or refreshing) + persisting as needed.

    Normal path uses ``get_valid_token`` (which auto-refreshes an expiring token). ``force``
    re-exchanges from the session token even when one is stored — used to self-heal a token the
    Admin API has started rejecting (app reinstalled, scopes changed, or a legacy non-expiring token).
    """
    if not force:
        token = get_valid_token(shop)
        if token:
            return token
    return _persist_token(shop, token_exchange(shop, session_token))


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
