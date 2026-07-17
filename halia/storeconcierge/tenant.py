"""Which brand a connected tenant belongs to, stored in the shop's settings.

A tenant is "halia" (the wealth engine) by default, or "storeconcierge" (the clienteling desk,
no scoring). The Store Concierge connect flow marks a shop here; the hosted dashboard reads it
to decide which product to serve. Nothing about customers is involved: this is a per-shop flag.
"""
from __future__ import annotations

import json

from halia.api.shopify_auth import shop_store


def brand_of(shop: str) -> str:
    """The brand key for a shop ('halia' | 'storeconcierge'), defaulting to 'halia'."""
    from halia.api.settings import settings_for
    return settings_for(shop).get("brand") or "halia"


def is_storeconcierge(shop: str) -> bool:
    return brand_of(shop) == "storeconcierge"


def set_brand(shop: str, key: str) -> None:
    """Mark a shop's brand, merging into its existing settings JSON."""
    store = shop_store()
    raw = store.get_settings_raw(shop)
    d = json.loads(raw) if raw else {}
    d["brand"] = (key or "halia").strip().lower()
    store.save_settings(shop, json.dumps(d))
