"""The Halia plan catalogue: the single source of truth for tiers, prices, and what each includes.

Mirrors the marketing pricing page (web/site/pricing.html): a free scan, then Discovery, Signal,
Atelier and the custom Maison tier. Prices are flat monthly figures banded by book size, GBP; there
is no per-customer metering. Each paid tier bundles a number of associate seats (keyboard / Chrome
extension logins); seats beyond the bundle are a flat SEAT_PRICE add-on. Both the in-app Plans screen
and the Shopify Billing integration read from here so the app, the site, and what a merchant is
charged all agree.
"""
from __future__ import annotations

CURRENCY = "GBP"
INTERVAL = "EVERY_30_DAYS"            # Shopify appRecurringPricingDetails interval

# Per-seat pricing. Each paid tier includes a bundle of associate seats (a seat = one employee signed
# in to the keyboard or the Chrome extension). Beyond the bundle, each extra seat is a flat monthly
# add-on. Seats are bundled generously and priced low on purpose: the tools only earn their keep when
# associates actually use them, so a seat must never be the reason a manager holds one back. The base
# tier is the engine; seats are how an account grows without capping its own adoption.
SEAT_PRICE = 15                      # GBP / month per seat above the plan's bundle

# The feature ladder, in the order shown on a plan card. Each plan lists the same ladder with the
# ones it includes ticked and the rest struck through, so the jump between tiers reads at a glance.
FEATURES: list[tuple[str, str]] = [
    ("count", "Hidden-VIC count &amp; latent value"),
    ("search", "Real-time order search"),
    ("alerts", "Live notifications (Slack, e-mail)"),
    ("unmask", "Unmask who they are, and why"),
    ("signals", "Standard wealth &amp; intent signals"),
    ("premium", "Premium signal packs"),
    ("crm", "Push to CRM / email"),
    ("roi", "ROI reporting"),
    ("onboarding", "White-glove onboarding"),
    ("fulfilment", "Multi-surface delivery (fulfilment)"),
    ("priority", "Priority support"),
    ("custom", "Custom signals &amp; multi-brand"),
]

_FREE = {"count", "search", "alerts"}
_DISCOVERY = _FREE | {"unmask", "signals"}
_SIGNAL = _DISCOVERY | {"premium", "crm", "roi", "onboarding"}
_ATELIER = _SIGNAL | {"fulfilment", "priority"}
_MAISON = {k for k, _ in FEATURES}          # everything

# order matters: ascending, this is the order the cards render in.
# `seats` is the bundle of associate seats included at no extra cost; extra seats are SEAT_PRICE each.
# None means seats are not metered on this plan (free has none to give; Maison is all-in / custom).
_PLANS: list[dict] = [
    {"key": "free", "name": "Free scan", "price": 0, "cap": None, "seats": None,
     "who": "See what's hiding, free forever", "includes": _FREE},
    {"key": "discovery", "name": "Discovery", "price": 150, "cap": 15000, "seats": 3,
     "who": "Smaller premium brands · up to 15k customers", "includes": _DISCOVERY},
    {"key": "signal", "name": "Signal", "price": 500, "cap": 75000, "highlighted": True, "seats": 5,
     "who": "Established brands · 15k–75k customers", "includes": _SIGNAL},
    {"key": "atelier", "name": "Atelier", "price": 1200, "cap": None, "seats": 10,
     "who": "Large houses / high volume · 75k+ customers", "includes": _ATELIER},
    {"key": "maison", "name": "Maison", "price": None, "cap": None, "custom": True, "seats": None,
     "who": "Groups &amp; largest houses · multi-brand", "includes": _MAISON},
]

_BY_KEY = {p["key"]: p for p in _PLANS}


def plan(key: str) -> dict | None:
    return _BY_KEY.get((key or "").strip().lower())


def billable(key: str) -> bool:
    """True for a self-serve paid tier a merchant can subscribe to from the app (not free/custom)."""
    p = plan(key)
    return bool(p and p.get("price") and not p.get("custom"))


def amount(key: str) -> float | None:
    p = plan(key)
    return float(p["price"]) if p and p.get("price") else None


def included_seats(key: str) -> int | None:
    """Seats a plan bundles at no extra cost. None = not metered (free / custom)."""
    p = plan(key)
    return None if not p else p.get("seats")


def extra_seats(key: str, active: int) -> int:
    """How many seats are billable beyond the bundle for `active` seats in use. 0 when not metered."""
    inc = included_seats(key)
    if inc is None:
        return 0
    return max(0, int(active or 0) - int(inc))


def seat_overage(key: str, active: int) -> float:
    """The monthly add-on for seats beyond the bundle, in GBP."""
    return float(extra_seats(key, active) * SEAT_PRICE)


def _seat_label(p: dict) -> str:
    """How the seat allowance reads on a plan card."""
    seats = p.get("seats")
    if p.get("custom"):
        return "Seats to suit your teams"
    if not seats:
        return ""                                     # free scan has no associate seats
    unit = "seat" if seats == 1 else "seats"
    return f"Includes {seats} {unit}, then £{SEAT_PRICE} / seat"


def _price_label(p: dict) -> str:
    if p.get("custom"):
        return "Custom"
    return "Free" if not p.get("price") else f"£{p['price']:,}"


def _card(p: dict) -> dict:
    """A plan serialised for the Plans screen: name, price, seats, and the feature ladder ticked/struck."""
    inc = p["includes"]
    return {
        "key": p["key"], "name": p["name"], "who": p.get("who", ""),
        "price": p.get("price"), "priceLabel": _price_label(p),
        "seats": p.get("seats"), "seatPrice": SEAT_PRICE, "seatLabel": _seat_label(p),
        "custom": bool(p.get("custom")), "highlighted": bool(p.get("highlighted")),
        "billable": billable(p["key"]),
        "features": [{"label": label, "included": key in inc} for key, label in FEATURES],
    }


def public_catalogue() -> list[dict]:
    return [_card(p) for p in _PLANS]


# Store Concierge is a separate brand with a single flat plan (never the wealth engine). Its own
# card, so a storeconcierge tenant is offered the £14 clienteling plan, not the Halia tiers.
_SC_FEATURES = [
    "Private catalogues (PDF &amp; enquiry form)",
    "Win-back list for quiet clients",
    "Per-client notes",
    "Appointment &amp; message templates",
    "One-tap email &amp; WhatsApp",
    "Orders by lifecycle stage",
]


def storeconcierge_card() -> dict:
    return {
        "key": "storeconcierge", "name": "Store Concierge",
        "who": "Look after your best customers like a boutique",
        "price": 14, "priceLabel": "£14", "custom": False, "highlighted": True, "billable": True,
        "seats": 2, "seatPrice": SEAT_PRICE, "seatLabel": f"Includes 2 seats, then £{SEAT_PRICE} / seat",
        "features": [{"label": f, "included": True} for f in _SC_FEATURES],
    }


def recommended_key(customer_count: int) -> str:
    """The smallest paid tier a book of this size fits under (Discovery/Signal/Atelier)."""
    if customer_count <= 15000:
        return "discovery"
    if customer_count <= 75000:
        return "signal"
    return "atelier"
