"""Store Concierge message templates and the two send channels: email and WhatsApp.

Templates are keyed to a moment in the order/customer lifecycle so the desk can suggest the
right words for where a customer is (just ordered, on its way, delivered, gone quiet, and so
on). The merchant picks a template and sends it from their own email client or WhatsApp; we
generate the link only. Nothing is sent through us and nothing is stored (zero-retention).
"""
from __future__ import annotations

import re
import urllib.parse as _url

# Each moment maps to a lifecycle stage. `stage` is the order/customer stage it suits;
# `suggest_for` marks the default template for a customer status or an order stage.
MOMENTS = [
    {"key": "thank_you", "label": "Thank you", "stage": "new order",
     "subject": "Thank you for your order",
     "body": "Hi {first_name},\n\nThank you so much for your order. We're getting it ready with real care. If there is anything at all you need, simply reply to this note.\n\nWarmly,\n{shop}"},
    {"key": "on_its_way", "label": "On its way", "stage": "shipped",
     "subject": "Your order is on its way",
     "body": "Hi {first_name},\n\nLovely news: your order has just left us and is on its way to you. We hope it brightens your day when it arrives.\n\n{shop}"},
    {"key": "delivered", "label": "How are you enjoying it?", "stage": "delivered",
     "subject": "How are you enjoying it?",
     "body": "Hi {first_name},\n\nWe hope your order arrived safely and that you love it. If anything is not quite right, we are always here to help.\n\n{shop}"},
    {"key": "vip_gift", "label": "A little thank you", "stage": "appreciation",
     "subject": "A little something for you",
     "body": "Hi {first_name},\n\nWe wanted to say thank you for being such a treasured customer. We have set a little something aside for you, with our compliments.\n\n{shop}"},
    {"key": "new_arrival", "label": "New arrival", "stage": "preview",
     "subject": "Something we thought you'd love",
     "body": "Hi {first_name},\n\nA new piece just arrived that made us think of you. Would you like a first look before it goes out to everyone?\n\n{shop}"},
    {"key": "winback", "label": "We've missed you", "stage": "gone quiet",
     "subject": "We've missed you",
     "body": "Hi {first_name},\n\nIt has been a little while and we have been thinking of you. We would love to welcome you back with something special, just for you.\n\n{shop}"},
    {"key": "appointment", "label": "A private appointment", "stage": "invitation",
     "subject": "A private appointment",
     "body": "Hi {first_name},\n\nWould you enjoy a private appointment with us? We would love to show you a few things we think you will love, at a time that suits you.\n\n{shop}"},
]

MOMENTS_BY_KEY = {m["key"]: m for m in MOMENTS}

# default template for a customer status (clients view) and for an order stage (orders view)
_SUGGEST_STATUS = {"active": "new_arrival", "lapsed": "winback"}
_SUGGEST_STAGE = {"preparing": "thank_you", "on its way": "on_its_way", "delivered": "delivered"}


def first_name(name: str) -> str:
    return (str(name or "").strip().split(" ") or [""])[0] or "there"


def fill(text: str, name: str, shop: str) -> str:
    return (str(text or "").replace("{first_name}", first_name(name))
            .replace("{shop}", shop or "us"))


def suggest_for_status(status: str) -> str:
    return _SUGGEST_STATUS.get((status or "").lower(), "thank_you")


def suggest_for_stage(stage: str) -> str:
    return _SUGGEST_STAGE.get((stage or "").lower(), "thank_you")


def email_link(email: str, subject: str, body: str) -> str:
    if not email:
        return ""
    q = _url.urlencode({"subject": subject or "", "body": body or ""}, quote_via=_url.quote)
    return f"mailto:{email}?{q}"


def wa_number(phone: str) -> str:
    """Best-effort E.164-ish digits for wa.me. Strips spaces and symbols and a leading 00
    international prefix. A bare local number (leading single 0) can't be mapped to a country
    reliably, so it is returned as-is for the merchant to correct."""
    d = re.sub(r"\D", "", str(phone or ""))
    if d.startswith("00"):
        d = d[2:]
    return d


def whatsapp_link(phone: str, body: str) -> str:
    num = wa_number(phone)
    if not num:
        return ""
    return f"https://wa.me/{num}?text={_url.quote(body or '')}"


def templates_public() -> list:
    """The template library in the shape the dashboard embeds for its client-side send."""
    return [{"key": m["key"], "label": m["label"], "stage": m["stage"],
             "subject": m["subject"], "body": m["body"]} for m in MOMENTS]
