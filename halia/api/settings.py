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
import re
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

# Order-action templates power the Orders view (status-aware). Keyed by order status.
# Placeholders: {first_name}, {sender}, plus {order_number} and {order_total} in the body.
ORDER_STATUSES = ("new", "fulfilled", "refunded", "cancelled")
DEFAULT_ORDER_TEMPLATES = {
    "new": [
        {"name": "Local expedite", "subject": "Good news about your order",
         "body": "Hi {first_name},\n\nWe noticed you are local, so we have expedited your order and "
                 "may be able to get it out to you today, making sure it reaches you as soon as "
                 "possible. Could you just confirm you are happy with the same delivery address? "
                 "Reply here and we will get it moving.\n\nWarmly,\n{sender}"},
        {"name": "Welcome + gift wrap", "subject": "Thank you for your order",
         "body": "Hi {first_name},\n\nThank you for your order, we really look forward to looking "
                 "after it. We aim to get it out as quickly as we can. Ahead of time, we also offer "
                 "complimentary gift wrapping and a handwritten note if this is a gift, just let me "
                 "know and I will arrange it before it ships.\n\nWarmly,\n{sender}"},
        {"name": "Priority handling", "subject": "Your order is in good hands",
         "body": "Hi {first_name},\n\nI wanted to let you know I have personally flagged your order "
                 "for priority handling, so it is prepared with extra care. I will be in touch the "
                 "moment it ships.\n\nWarmly,\n{sender}"},
        {"name": "Personal thank you", "subject": "A personal note",
         "body": "Hi {first_name},\n\nThank you so much for your order, it is a pleasure to have you "
                 "with us. If there is anything you would like alongside it, I am here personally to "
                 "help.\n\nWarmly,\n{sender}"},
        {"name": "Anything else?", "subject": "While we prepare your order",
         "body": "Hi {first_name},\n\nWhile we get your order ready, is there anything else you have "
                 "had your eye on? I would be glad to set it aside or send it together to save you a "
                 "second delivery.\n\nWarmly,\n{sender}"},
    ],
    "fulfilled": [
        {"name": "Shipped fast", "subject": "Your order is on its way",
         "body": "Hi {first_name},\n\nJust to let you know we got your order out as fast as we could. "
                 "We hope it reaches you soon and that you love it. If anything is not quite right, "
                 "reply here and I will sort it out straight away.\n\nWarmly,\n{sender}"},
        {"name": "Care check-in", "subject": "Looking after you",
         "body": "Hi {first_name},\n\nYour order is on its way. If anything is not perfect when it "
                 "arrives, tell me directly and I will make it right, no fuss.\n\nWarmly,\n{sender}"},
        {"name": "Styling help", "subject": "A little help with your order",
         "body": "Hi {first_name},\n\nYour order has shipped. If you would like any advice on caring "
                 "for it or styling it, I am always happy to help.\n\nWarmly,\n{sender}"},
        {"name": "VIP touch", "subject": "You are in good hands",
         "body": "Hi {first_name},\n\nYour order is on the way. As one of our most valued clients, "
                 "you have my direct line for anything you need.\n\nWarmly,\n{sender}"},
        {"name": "Early preview", "subject": "Something you might love",
         "body": "Hi {first_name},\n\nI hope you enjoy your order. We have some new pieces arriving "
                 "that I think would suit you. Would you like an early look before they go "
                 "live?\n\nWarmly,\n{sender}"},
    ],
    "refunded": [
        {"name": "Win back", "subject": "Let me help",
         "body": "Hi {first_name},\n\nI am sorry this one did not work out, and your refund is on its "
                 "way. I would love to help you find something that is a better fit, whenever you are "
                 "ready.\n\nWarmly,\n{sender}"},
        {"name": "Apology + offer", "subject": "Thank you for your patience",
         "body": "Hi {first_name},\n\nApologies for the trouble, your refund has been processed. As a "
                 "thank you for your patience, I would be glad to look after you personally on your "
                 "next order.\n\nWarmly,\n{sender}"},
        {"name": "Quick feedback", "subject": "So we can do better",
         "body": "Hi {first_name},\n\nYour refund is complete. If you have a moment, I would value "
                 "knowing what did not suit, so we can do better for you next time.\n\nWarmly,\n{sender}"},
        {"name": "Always welcome", "subject": "You are always welcome",
         "body": "Hi {first_name},\n\nSorry it was not right this time. You are always welcome back, "
                 "and I am here if you would like a hand finding the right piece.\n\nWarmly,\n{sender}"},
        {"name": "On the hunt", "subject": "Tell me what you were after",
         "body": "Hi {first_name},\n\nYour refund is sorted. If there was something specific you were "
                 "after, tell me and I will hunt it down for you.\n\nWarmly,\n{sender}"},
    ],
    "cancelled": [
        {"name": "Everything ok?", "subject": "About your order",
         "body": "Hi {first_name},\n\nI noticed your order was cancelled. If that was not intended, or "
                 "you would like a hand, I am here to sort it quickly.\n\nWarmly,\n{sender}"},
        {"name": "Help to reorder", "subject": "Happy to help",
         "body": "Hi {first_name},\n\nIf you changed your mind or hit a snag at checkout, just let me "
                 "know and I can place the order for you, or hold the piece while you "
                 "decide.\n\nWarmly,\n{sender}"},
        {"name": "Suggest alternatives", "subject": "Let me help you find the right one",
         "body": "Hi {first_name},\n\nSorry this one did not go ahead. If it was not quite right, I "
                 "would be glad to suggest a few alternatives you might prefer.\n\nWarmly,\n{sender}"},
        {"name": "No pressure", "subject": "Whenever you are ready",
         "body": "Hi {first_name},\n\nNo pressure at all. Whenever you are ready, I am here to help "
                 "you find something you will love.\n\nWarmly,\n{sender}"},
        {"name": "Stay in touch", "subject": "Keeping you in mind",
         "body": "Hi {first_name},\n\nI will keep you in mind for pieces I think you would like. If "
                 "you would prefer me not to, just say and I will leave you be.\n\nWarmly,\n{sender}"},
    ],
}


def clean_emails(raw) -> list[str]:
    """Normalise a list (or comma/space-separated string) of emails to a de-duped valid list."""
    if isinstance(raw, str):
        raw = re.split(r"[,;\s]+", raw)
    out: list[str] = []
    for e in (raw or []):
        e = str(e).strip()
        if e and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e) and e.lower() not in (x.lower() for x in out):
            out.append(e[:200])
    return out[:25]


def settings_for(shop: str) -> dict:
    """The shop's settings, with defaults filled in."""
    raw = shop_store().get_settings_raw(shop)
    d = json.loads(raw) if raw else {}
    # Alert recipients: prefer the list; fall back to the legacy single notify_email.
    emails = d.get("notify_emails")
    if emails is None:
        emails = [d["notify_email"]] if d.get("notify_email") else []
    return {
        "vic_threshold": d.get("vic_threshold", DEFAULT_VIC_THRESHOLD),
        "sender_name": d.get("sender_name", ""),
        "email_templates": d.get("email_templates") or DEFAULT_TEMPLATES,
        "order_templates": d.get("order_templates") or DEFAULT_ORDER_TEMPLATES,
        # Latent-value benchmarks (merchant's own numbers; 0 = not set → fallback heuristic).
        "aov": d.get("aov", 0),
        "max_orders": d.get("max_orders", 0),
        "highest_lt": d.get("highest_lt", 0),
        # The merchant's own account email (captured at onboarding).
        "account_email": d.get("account_email", ""),
        # Desktop + email alerts for new high-grade orders.
        "notify_enabled": bool(d.get("notify_enabled", False)),
        "notify_grades": d.get("notify_grades") or ["A*", "A"],
        "notify_emails": emails,
        "notify_email": emails[0] if emails else "",  # back-compat (first recipient)
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


def _clean_order_templates(raw) -> dict:
    """Keep only the four known order statuses; clean each list; fall back to defaults
    for any status the merchant left empty, so the Orders view always has actions."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for status in ORDER_STATUSES:
        out[status] = _clean_templates(raw.get(status)) or DEFAULT_ORDER_TEMPLATES[status]
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
        # Shopify tag write-back is only offered to Shopify tenants (they hold an admin token).
        s["shopify_connected"] = bool(store.get_token(shop))
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
            "order_templates": _clean_order_templates(payload.get("order_templates")),
            "aov": _num(payload.get("aov")),
            "max_orders": int(_num(payload.get("max_orders"))),
            "highest_lt": _num(payload.get("highest_lt")),
            "notify_enabled": bool(payload.get("notify_enabled", False)),
            "notify_grades": [g for g in (payload.get("notify_grades") or ["A*", "A"])
                              if g in ("A*", "A", "B")] or ["A*"],
            "account_email": str(payload.get("account_email", ""))[:200],
        }
        emails = clean_emails(payload.get("notify_emails")
                              if payload.get("notify_emails") is not None
                              else payload.get("notify_email"))
        data["notify_emails"] = emails
        data["notify_email"] = emails[0] if emails else ""  # back-compat
        shop_store().save_settings(shop, json.dumps(data))
        cache.evict(shop)  # a changed threshold must re-score on next load
        return {"ok": True}

    @app.post("/v1/klaviyo/disconnect")
    def klaviyo_disconnect(shop: str = Depends(require_shop)) -> dict:
        shop_store().delete_klaviyo(shop)
        return {"ok": True}
