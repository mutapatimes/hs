"""Where a client-facing page lives. A client opens two kinds of page, the appointment invite
(/i/<token>) and the capture form (/c/<slug>), and must never land on haliascore.com from either.
Resolved per store, best first: the store's own domain (Shopify app proxy, WooCommerce plugin),
a subdomain the store CNAMEs to Halia, a neutral Halia-owned domain, and only then the app URL.
"""
from __future__ import annotations

import time
from urllib.parse import quote

from halia import config

_CACHE: dict[str, dict] = {}
_TTL = 3600


def _resolve(shop: str) -> tuple[str, str]:
    from halia.api.shopify_auth import shop_store
    try:
        from halia.api.catalog import _primary_domain
        host = _primary_domain(shop)
    except Exception:  # noqa: BLE001
        host = ""
    if host:
        return "proxy", f"https://{host}/{config.PROXY_PREFIX}/{config.PROXY_SUBPATH}"
    try:
        woo = shop_store().get_woocommerce(shop) or {}
    except Exception:  # noqa: BLE001
        woo = {}
    if woo.get("store_url"):
        return "wp", str(woo["store_url"]).rstrip("/")
    try:
        from halia.api.settings import settings_for
        dom = (settings_for(shop) or {}).get("catalog_domain") or ""
    except Exception:  # noqa: BLE001
        dom = ""
    if dom:
        return "cname", f"https://{dom}"
    if config.HALIA_CLIENT_URL:
        return "neutral", config.HALIA_CLIENT_URL
    return "app", (config.HALIA_APP_URL or "https://haliascore.com").rstrip("/")


def _cached(shop: str) -> tuple[str, str]:
    ent = _CACHE.get(shop)
    if ent and time.monotonic() - ent["at"] < _TTL:
        return ent["kind"], ent["base"]
    kind, base = _resolve(shop)
    _CACHE[shop] = {"at": time.monotonic(), "kind": kind, "base": base}
    return kind, base


def invalidate(shop: str) -> None:
    _CACHE.pop(shop, None)


def client_url(shop: str, path: str) -> str:
    """``path`` is 'i/<token>' or 'c/<slug>', with an optional '?query'."""
    kind, base = _cached(shop)
    if kind == "wp":
        p, _, q = path.partition("?")
        return f"{base}/?halia-page={quote(p, safe='/.')}" + (f"&{q}" if q else "")
    return f"{base}/{path}"


def cname_target() -> str:
    """The host a store points its subdomain at."""
    base = config.HALIA_CLIENT_URL or config.HALIA_APP_URL or "https://haliascore.com"
    return base.replace("https://", "").replace("http://", "").strip("/")
