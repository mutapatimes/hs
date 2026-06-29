"""Auth for self-service (non-Shopify) tenants — a private dashboard link.

A WooCommerce/standalone client has no Shopify admin to identify them, so onboarding
mints a long random token. We store only its sha256 hash (`tenants.token_hash`); the
client reaches their dashboard at /app?t=<token>, and we set it as an httpOnly cookie so
later requests (Settings, refresh) carry it. The raw token is shown once, at onboarding.
"""
from __future__ import annotations

import hashlib
import secrets

from fastapi import HTTPException, Request

from halia.api.shopify_auth import shop_store

COOKIE = "halia_t"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_from_request(request: Request) -> str | None:
    return request.query_params.get("t") or request.cookies.get(COOKIE)


def resolve_tenant(request: Request) -> str | None:
    """Return the tenant's shop key for a valid access token, else None."""
    token = token_from_request(request)
    if not token:
        return None
    row = shop_store().tenant_for_token(hash_token(token))
    return row["shop"] if row else None


def require_tenant(request: Request) -> str:
    shop = resolve_tenant(request)
    if not shop:
        raise HTTPException(401, "Invalid or missing access link")
    return shop
