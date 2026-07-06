"""Console-editable settings — one JSON blob you control from the /console dashboard.

Everything you should be able to change without a developer lives here: new-client defaults,
the self-serve signup code, comped clients, revenue display/overrides, client-email templates, and
journey milestones. It is persisted as a single JSON document under the sentinel shop key
``_console`` via the existing ``settings`` table (``save_settings``/``get_settings_raw``) — zero schema
change, same convention as the ``_system`` metrics bucket, and naturally excluded from tenant
iteration.

Kept deliberately light (only ``json`` + a lazy ``shop_store``) so ``settings.py`` / ``billing.py``
/ ``onboarding.py`` can read console overrides via ``console_setting()`` without an import cycle.
Secrets are NEVER stored here — only non-sensitive config you curate.
"""
from __future__ import annotations

import json

_CONSOLE_KEY = "_console"

# Seed client-outreach templates. Placeholders {client_name} / {store} / {sender} are filled when a
# message is composed. Brand voice: warm, plain, positive (no em dashes, no "not-a-X" phrasing).
DEFAULT_CLIENT_TEMPLATES = [
    {"id": "checkin", "name": "Check-in", "category": "check-in",
     "subject": "Checking in on {store}",
     "body": ("Hi {client_name},\n\nJust checking in to see how Halia is working for {store}. "
              "Are the hidden-VIC picks landing well with your team, and is there anything you would "
              "love it to do next?\n\nAlways happy to jump on a quick call.\n\nWarmly,\n{sender}")},
    {"id": "upgrade", "name": "Free upgrade", "category": "free-upgrade",
     "subject": "A little upgrade for {store}",
     "body": ("Hi {client_name},\n\nYou have been one of our earliest supporters, so I would like to "
              "turn on a complimentary upgrade for {store}: earlier access to new signals and "
              "priority support, on us.\n\nReply and I will switch it on today.\n\nWarmly,\n{sender}")},
    {"id": "support", "name": "Offer support", "category": "support",
     "subject": "Anything I can help with, {client_name}?",
     "body": ("Hi {client_name},\n\nI wanted to make sure {store} is getting the most from Halia. If "
              "anything feels unclear or you would like a second pair of eyes on your top clients, I "
              "am here.\n\nWhat would make this more useful for you?\n\nWarmly,\n{sender}")},
    {"id": "milestone", "name": "Milestone note", "category": "milestone",
     "subject": "Congratulations, {store}",
     "body": ("Hi {client_name},\n\nA quick note to celebrate a milestone with {store}. Thank you for "
              "growing with Halia. Here is to the next one.\n\nWarmly,\n{sender}")},
]

DEFAULTS = {
    "sender_name": "",                       # sign-off used for the {sender} placeholder
    "default_vic_threshold": 5000,          # applied to newly onboarded clients (per-shop overrides)
    "default_notify_grades": ["A*", "A"],
    "signup_code": None,                    # None -> fall back to env HALIA_SIGNUP_CODE
    "free_shops": None,                     # None -> fall back to env HALIA_FREE_SHOPS
    "plan_price": None,                     # display price (minor units? no: whole units); None -> Stripe
    "plan_currency": "GBP",
    "revenue_overrides": {},                # {shop: {amount, currency, renewal_date, plan, status}}
    "client_templates": DEFAULT_CLIENT_TEMPLATES,
    "milestones": [],                       # [{date, title, note}]
}


def _store():
    from halia.api.shopify_auth import shop_store
    return shop_store()


def _raw() -> dict:
    """The stored console blob exactly as saved (no defaults overlaid). {} when nothing saved."""
    raw = _store().get_settings_raw(_CONSOLE_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def console_settings() -> dict:
    """Full settings for display: DEFAULTS overlaid with whatever the console has saved."""
    merged = dict(DEFAULTS)
    merged.update(_raw())
    return merged


def save_console_settings(patch: dict) -> dict:
    """Merge ``patch`` into the stored blob and persist. Returns the new full settings."""
    data = _raw()
    data.update(patch)
    _store().save_settings(_CONSOLE_KEY, json.dumps(data))
    return console_settings()


def console_setting(key: str, env_fallback=None):
    """A single console override, or ``env_fallback`` when the console has not set that key.

    Presence-based: only overrides when the key was explicitly saved (so an intentionally empty
    list means "none", while an unsaved key defers to the environment default).
    """
    raw = _raw()
    return raw[key] if key in raw and raw[key] is not None else env_fallback


def is_console_shop(shop: str) -> bool:
    """True for the sentinel keys that are not real tenants (excluded from client lists)."""
    return shop in (_CONSOLE_KEY, "_system")
