"""Auth for self-service (non-Shopify) tenants.

Two ways a request proves who it is:

1. **Access token** (`?t=<token>` or the legacy `halia_t` cookie): a long random secret minted
   at onboarding. We store only its sha256 hash (`tenants.token_hash`). This is the capability
   handed over once at onboarding — a bearer credential.
2. **Signed session** (`halia_s` cookie): an HMAC-signed, expiring `shop|exp|sig` value set after
   a successful sign-in (magic link, or first arrival on an access link). It carries no secret you
   can replay elsewhere and it expires, so it — not the raw token — is what lives in the browser.

The magic-link flow (see onboarding.py) proves control of the tenant's email, then hands out a
session. The raw access link keeps working as a fallback.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request

from halia.api.shopify_auth import shop_store

COOKIE = "halia_t"          # legacy/bearer: the raw access token
SESSION_COOKIE = "halia_s"  # signed, expiring session
SESSION_TTL = 60 * 60 * 24 * 365  # 1 year


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _secret() -> bytes:
    """Server-side signing secret for sessions (never leaves the server)."""
    from halia import config
    return (config.SHOPIFY_API_SECRET or "halia-dev-session-secret").encode("utf-8")


def make_session(shop: str, ttl: int = SESSION_TTL) -> str:
    """A tamper-proof, expiring session value binding this browser to one tenant."""
    exp = int(time.time()) + ttl
    msg = f"{shop}|{exp}"
    sig = hmac.new(_secret(), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{msg}|{sig}".encode("utf-8")).decode("ascii")


def read_session(value: str) -> str | None:
    """Return the shop for a valid, unexpired session cookie, else None."""
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
        shop, exp, sig = raw.rsplit("|", 2)
        expect = hmac.new(_secret(), f"{shop}|{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        if int(exp) < int(time.time()):
            return None
        return shop or None
    except Exception:
        return None


def token_from_request(request: Request) -> str | None:
    return request.query_params.get("t") or request.cookies.get(COOKIE)


def resolve_tenant(request: Request) -> str | None:
    """Return the tenant's shop key for a valid access token OR session, else None."""
    token = token_from_request(request)
    if token:
        row = shop_store().tenant_for_token(hash_token(token))
        if row:
            return row["shop"]
    session = request.cookies.get(SESSION_COOKIE)
    if session:
        shop = read_session(session)
        if shop:
            return shop
    return None


def require_tenant(request: Request) -> str:
    shop = resolve_tenant(request)
    if not shop:
        raise HTTPException(401, "Please sign in")
    return shop
