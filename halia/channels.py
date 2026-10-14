"""Store or online: where a client actually shops with the house.

Whether a client is a store client or an online client is a house decision, not a fact: one
client spent £100 in store and £6,000 online but walked in first. So Halia keeps the facts per
client (which channel came first and last, spend and orders in each, the store they use, the
associate on their store sales) and the label is a rule the merchant chooses in Settings:

  first   the channel of their first order
  spend   the channel with the larger share of their spend
  recent  the channel of their latest order

and "both" when each channel carries at least a set share of spend (0 turns "both" off).

Which channel an order is: Shopify's sourceName. Point of sale ("pos") and orders an associate
creates for a client ("shopify_draft_order") are store; everything else (the online store, the
Shop app, other sales channels) is online. Other platforms carry no source, so no channel.
RAM-only like the rest of the payload.
"""
from __future__ import annotations

from collections import Counter

STORE_SOURCES = {"pos", "shopify_draft_order"}
RULES = ("first", "spend", "recent")
DEFAULT_RULE = "first"
DEFAULT_BOTH = 25          # % of spend each channel needs before a client counts as both


def channel_of(order: dict, store_sources=()) -> str | None:
    """'store', 'online', or None when the order says nothing about where it was placed.
    ``store_sources`` are the house's own extra store channels (a third-party till such as
    Lightspeed reports its own source name), set in Settings."""
    src = str(order.get("source_name") or "").strip().lower()
    if not src:
        return None
    extra = {str(x).strip().lower() for x in (store_sources or ()) if str(x).strip()}
    return "store" if (src in STORE_SOURCES or src in extra) else "online"


def clean_sources(v) -> list[str]:
    """A comma- or line-separated list of sales channel names, lower-cased, at most 20."""
    import re
    items = v if isinstance(v, (list, tuple)) else re.split(r"[,\n]+", str(v or ""))
    out = []
    for x in items:
        x = str(x).strip().lower()[:60]
        if x and x not in out:
            out.append(x)
    return out[:20]


def summary(rows: list[dict] | None) -> dict | None:
    """The facts for one client from their order-history rows (newest first, each with 'ch' and
    'amount'). None when no order carries a channel."""
    rows = [r for r in (rows or []) if r.get("ch") in ("store", "online")]
    if not rows:
        return None
    spend = {"store": 0.0, "online": 0.0}
    orders = {"store": 0, "online": 0}
    for r in rows:
        spend[r["ch"]] += float(r.get("amount") or 0)
        orders[r["ch"]] += 1
    by_date = sorted(rows, key=lambda r: str(r.get("date") or ""))
    locs = Counter(r["loc"] for r in rows if r.get("ch") == "store" and r.get("loc"))
    staff = Counter(r["staff"] for r in rows if r.get("staff"))
    total = spend["store"] + spend["online"]
    out = {
        "first": by_date[0]["ch"],
        "firstDate": str(by_date[0].get("date") or ""),
        "last": by_date[-1]["ch"],
        "lastDate": str(by_date[-1].get("date") or ""),
        "storeSpend": round(spend["store"]),
        "onlineSpend": round(spend["online"]),
        "storeOrders": orders["store"],
        "onlineOrders": orders["online"],
        "storeShare": round(100 * spend["store"] / total) if total else (100 if orders["store"] and not orders["online"] else 0),
    }
    if locs:
        out["store"] = locs.most_common(1)[0][0]
    if staff:
        out["associate"] = staff.most_common(1)[0][0]
    return out


def label(s: dict | None, rule: str = DEFAULT_RULE, both: float = DEFAULT_BOTH) -> str | None:
    """'store', 'online' or 'both' for a client's facts under the house rule; None without facts."""
    if not s:
        return None
    share = float(s.get("storeShare") or 0)
    if both and s.get("storeOrders") and s.get("onlineOrders") and min(share, 100 - share) >= float(both):
        return "both"
    if rule == "recent":
        return s["last"]
    if rule == "spend":
        if share == 50:
            return s["first"]
        return "store" if share > 50 else "online"
    return s["first"]


def clean_rule(v) -> str:
    v = str(v or "").strip().lower()
    return v if v in RULES else DEFAULT_RULE


def clean_both(v) -> int:
    try:
        return max(0, min(50, int(float(v))))
    except (TypeError, ValueError):
        return DEFAULT_BOTH
