"""Merchant-configurable settings — the in-app Settings panel.

Lets each merchant self-serve: connect/disconnect Klaviyo, set their hidden-VIC spend
threshold, edit their email templates, and set a sign-off name. None of this is customer
data; it's the merchant's own config, stored as plain JSON per shop (zero-retention for
customers is unaffected).

    GET  /v1/settings   — current settings (+ klaviyo_connected)
    POST /v1/settings   — save threshold / sender / email templates (evicts cache so a new
                          threshold re-scores on next load)
    POST /v1/klaviyo/disconnect — forget the shop's Klaviyo key
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import Body, Depends, HTTPException

from halia import config
from halia.api.shopify_auth import require_shop, shop_store
from halia.cache import cache

DEFAULT_VIC_THRESHOLD = 5000

# Seed templates the merchant starts with (they can edit/add/delete). Placeholders:
# {first_name} = the client's first name, {sender} = the merchant's sign-off name.
DEFAULT_TEMPLATES = [
    {"name": "Personal welcome", "subject": "A personal note",
     "body": "Dear {first_name},\n\nThank you for being one of our valued clients. I wanted to "
             "reach out personally — if there's ever anything you're looking for, it would be my "
             "pleasure to help you find it.\n\nWarm regards,\n{sender}"},
    {"name": "Private preview invite", "subject": "An early preview, just for you",
     "body": "Dear {first_name},\n\nWe have a private preview of our new pieces coming up, and I "
             "immediately thought of you. I'd love to set aside some time for you ahead of "
             "everyone else.\n\nWarmly,\n{sender}"},
    {"name": "Private appointment", "subject": "A personal appointment",
     "body": "Dear {first_name},\n\nWould you enjoy a private appointment with our team? We'd love "
             "to show you a few pieces we think you'll love, at a time that suits you.\n\n"
             "Kind regards,\n{sender}"},
    {"name": "New arrival for you", "subject": "Something I thought you'd love",
     "body": "Dear {first_name},\n\nA new arrival came in that reminded me of your taste. I've set "
             "one aside in case you'd like to see it — no obligation at all.\n\nWarm regards,\n{sender}"},
    {"name": "Concierge check-in", "subject": "Checking in",
     "body": "Dear {first_name},\n\nJust a note to say we're here whenever you need us — a gift, a "
             "particular piece, or simply a recommendation. It's always a pleasure to look after "
             "you.\n\nWarmly,\n{sender}"},
]


def settings_for(shop: str) -> dict:
    """The shop's settings, with defaults filled in."""
    raw = shop_store().get_settings_raw(shop)
    d = json.loads(raw) if raw else {}
    return {
        "vic_threshold": d.get("vic_threshold", DEFAULT_VIC_THRESHOLD),
        "sender_name": d.get("sender_name", ""),
        "email_templates": d.get("email_templates") or DEFAULT_TEMPLATES,
        # Latent-value benchmarks (merchant's own numbers; 0 = not set → fallback heuristic).
        "aov": d.get("aov", 0),
        "max_orders": d.get("max_orders", 0),
        "highest_lt": d.get("highest_lt", 0),
        # Desktop alerts for new high-grade orders.
        "notify_enabled": bool(d.get("notify_enabled", False)),
        "notify_grades": d.get("notify_grades") or ["A*", "A"],
        "notify_email": d.get("notify_email", ""),
    }


def _num(v, default=0.0):
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return default


def _clean_templates(raw) -> list[dict]:
    out = []
    for t in (raw or []):
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", "")).strip()
        body = str(t.get("body", "")).strip()
        if name and body:
            out.append({"name": name[:80], "subject": str(t.get("subject", ""))[:160],
                        "body": body[:4000]})
    return out


def register(app) -> None:

    @app.get("/v1/settings")
    def get_settings(shop: str = Depends(require_shop)) -> dict:
        s = settings_for(shop)
        store = shop_store()
        s["klaviyo_connected"] = bool(store.get_klaviyo(shop) or config.KLAVIYO_API_KEY)
        mc = store.get_mailchimp(shop)
        s["mailchimp_connected"] = bool(mc and mc.get("list_id"))
        s["mailchimp_list_name"] = (mc or {}).get("list_name")
        # Real-time order-alert plumbing: the per-shop webhook URL + the Web Push key.
        import secrets

        from halia import notify
        token = store.ensure_webhook_token(shop, secrets.token_urlsafe(24))
        base = (config.HALIA_APP_URL or "").rstrip("/")
        s["webhook_url"] = f"{base}/webhooks/orders/{token}"
        s["vapid_public"] = notify.vapid_public()
        return s

    @app.post("/v1/settings")
    def save_settings(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        payload = payload or {}
        try:
            threshold = float(payload.get("vic_threshold", DEFAULT_VIC_THRESHOLD))
        except (TypeError, ValueError):
            raise HTTPException(422, "VIC threshold must be a number.")
        data = {
            "vic_threshold": max(0.0, threshold),
            "sender_name": str(payload.get("sender_name", ""))[:120],
            "email_templates": _clean_templates(payload.get("email_templates")),
            "aov": _num(payload.get("aov")),
            "max_orders": int(_num(payload.get("max_orders"))),
            "highest_lt": _num(payload.get("highest_lt")),
            "notify_enabled": bool(payload.get("notify_enabled", False)),
            "notify_grades": [g for g in (payload.get("notify_grades") or ["A*", "A"])
                              if g in ("A*", "A", "B")] or ["A*"],
            "notify_email": str(payload.get("notify_email", ""))[:200],
        }
        shop_store().save_settings(shop, json.dumps(data))
        cache.evict(shop)  # a changed threshold must re-score on next load
        return {"ok": True}

    @app.post("/v1/klaviyo/disconnect")
    def klaviyo_disconnect(shop: str = Depends(require_shop)) -> dict:
        shop_store().delete_klaviyo(shop)
        return {"ok": True}
