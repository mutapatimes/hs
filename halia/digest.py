"""The weekly digest: what is worth a merchant's attention this Monday morning.

Two halves, deliberately separated:

* ``facts(shop)`` counts. It reads the warm scored book and the shop's campaigns and returns
  plain numbers and a handful of names. No model is involved, so every figure in the digest is
  something the engine actually measured.

* ``write(facts)`` phrases. It hands those figures to Claude to turn into a few readable lines,
  and falls back to composing them itself when there is no key. The model is told, and can only
  be given, the numbers in ``facts`` — it never sees the book.

A note on honesty in the wording: Halia stores no history, so the digest cannot say what *changed*
this week without inventing a comparison it has no basis for. Everything here is either a current
state ("14 proven clients are quiet") or a genuine seven-day window derived from order dates
("6 top-grade clients ordered in the last seven days"). The prompt forbids the model from implying
otherwise.

Zero-retention is untouched: this reads the same RAM book every other surface reads and stores
nothing.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

_WEEK = 7 * 86400
_NAMES = 3          # how many names to carry per section: enough to act on, not a mailing list


def _play(row: dict) -> str:
    """The play a client falls into. Mirrors the dashboard's own playOf()."""
    tier, band = row.get("tier"), row.get("band")
    if row.get("known") or (tier in ("A1", "A") and (row.get("ordersCount") or 0) >= 2
                            and band == "lapsed"):
        return "sleeping"
    if not row.get("known") and band in ("active", "new"):
        return "fresh"
    return ""


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def facts(shop: str, now: Optional[float] = None) -> dict:
    """Everything the digest can honestly report, counted from the warm book. No model involved.

    Warm cache only: a digest is a convenience and must never trigger a sync."""
    from halia.api.shopify_auth import shop_store
    from halia.cache import cache

    now = now if now is not None else time.time()
    rows = ((cache.get(shop) or {}).get("payload") or {}).get("data") or []

    quiet, fresh_orders, baskets = [], [], []
    hidden = 0
    latent_total = 0.0
    for row in rows:
        if not row.get("known"):
            hidden += 1
        latent_total += _money(row.get("latent"))
        play = _play(row)
        if play == "sleeping":
            quiet.append(row)
        last = row.get("lastSort") or 0
        if last and (now - last) <= _WEEK and str(row.get("tier") or "").startswith("A"):
            fresh_orders.append(row)
        cart = row.get("cart") or {}
        if _money(cart.get("value")) > 0:
            baskets.append(row)

    def _top(items, key):
        best = sorted(items, key=key, reverse=True)[:_NAMES]
        return [{"name": r.get("name") or "A client", "grade": r.get("grade"),
                 "spend": _money(r.get("spend")),
                 "basket": _money((r.get("cart") or {}).get("value"))} for r in best]

    campaigns = []
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    try:
        for row in shop_store().list_campaigns(shop):
            starts, ends = row.get("starts") or "", row.get("ends") or ""
            if not (starts and ends and starts <= today <= ends):
                continue
            try:
                cfg = json.loads(row.get("config_json") or "{}")
            except (TypeError, ValueError):
                cfg = {}
            campaigns.append({"name": row["name"], "members": len(cfg.get("members") or []),
                              "ends": ends})
    except Exception:  # noqa: BLE001 — a digest must never fail on a campaign read
        campaigns = []

    return {
        "clients": len(rows),
        "hidden": hidden,
        "quiet": len(quiet),
        "quiet_top": _top(quiet, lambda r: _money(r.get("spend"))),
        "recent_orders": len(fresh_orders),
        "recent_top": _top(fresh_orders, lambda r: _money(r.get("spend"))),
        "baskets": len(baskets),
        "basket_value": round(sum(_money((r.get("cart") or {}).get("value")) for r in baskets)),
        "basket_top": _top(baskets, lambda r: _money((r.get("cart") or {}).get("value"))),
        "latent": round(latent_total),
        "campaigns": campaigns,
        "warm": bool(rows),
    }


# ── phrasing ─────────────────────────────────────────────────────────────────────────
_SYSTEM = (
    "You write a luxury retailer's Monday morning briefing from figures their client-intelligence "
    "engine has already counted.\n\n"
    "Three to five short lines, each one thing worth doing. Lead with whatever most deserves "
    "attention. Name the two or three clients you were given where naming them helps someone act; "
    "otherwise talk in numbers.\n\n"
    "Use only the figures given. Never invent a number, a name, a product or a campaign. Do not "
    "say anything changed, rose, fell or improved: you are seeing one snapshot and have no earlier "
    "one to compare it with. A seven-day figure may be described as such because it was measured "
    "that way.\n\n"
    "Plain text, one line per point, no markdown, no bullet characters, no greeting or sign-off. "
    "Do not use em dashes; use commas, colons or periods."
)


def _n(count: int, noun: str, verb: str = "") -> str:
    """"1 client is" / "3 clients are" — a briefing that mis-agrees reads as machine output."""
    word = noun if count == 1 else noun + "s"
    if not verb:
        return f"{count} {word}"
    forms = {"is": "are", "has": "have", "was": "were"}
    return f"{count} {word} {verb if count == 1 else forms.get(verb, verb)}"


def _plain(f: dict) -> list[str]:
    """The digest composed without a model: the same facts, stated flatly."""
    lines: list[str] = []
    if f.get("recent_orders"):
        who = ", ".join(c["name"] for c in f.get("recent_top") or [])
        lines.append(_n(f["recent_orders"], "top-grade client")
                     + " ordered in the last seven days"
                     + (f": {who}. Worth a personal note." if who else "."))
    if f.get("quiet"):
        who = ", ".join(c["name"] for c in f.get("quiet_top") or [])
        lines.append(_n(f["quiet"], "proven client", "is") + " quiet"
                     + (f". The highest spenders among them: {who}." if who else "."))
    if f.get("baskets"):
        top = (f.get("basket_top") or [{}])[0]
        lines.append(_n(f["baskets"], "basket", "is")
                     + f" open, worth £{f['basket_value']:,.0f} in total"
                     + (f", the largest {top.get('name')}'s at £{top.get('basket', 0):,.0f}."
                        if top.get("name") else "."))
    for camp in (f.get("campaigns") or [])[:2]:
        lines.append(f"{camp['name']} is running until {camp['ends']} with "
                     f"{_n(camp['members'], 'client')} in it.")
    if f.get("hidden"):
        lines.append(f"{_n(f['hidden'], 'client')} in your book "
                     f"{'is' if f['hidden'] == 1 else 'are'} quietly valuable and not tagged a "
                     f"VIP by the store.")
    return lines


def write(f: dict, shop: Optional[str] = None) -> tuple[str, str]:
    """Return (digest text, source). Source is "ai" when a model phrased it, "book" when not.

    Falls back to the plain composition on a missing key, a cap, or any failure, so the digest
    always says something true."""
    lines = _plain(f)
    if not lines:
        return ("Nothing needs your attention this week. No open baskets, no proven clients gone "
                "quiet, and no recent orders from top-grade clients.", "book")
    plain = "\n".join(lines)

    from halia import config, llm
    if not llm.available():
        return plain, "book"
    if shop and config.LLM_WEEKLY_CAP:
        from halia.api.shopify_auth import shop_store
        if shop_store().shop_metric(shop, "digest_ai") >= config.LLM_WEEKLY_CAP:
            return plain, "book"

    text = llm.complete(_SYSTEM, "This week's figures:\n" + json.dumps(f, indent=1)
                        + "\n\nWrite the briefing now.", max_tokens=500)
    return (text, "ai") if text else (plain, "book")
