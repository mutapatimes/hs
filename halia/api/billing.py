"""Stripe billing: gate the hosted dashboard behind a subscription.

Free path: a merchant connects their store and sees a teaser (their hidden-VIC count and
the total latent value). To unlock the full dashboard they subscribe through Stripe Checkout.

Billing is OFF unless STRIPE_SECRET_KEY and STRIPE_PRICE_ID are both set, so existing and
local tenants stay fully open and no one is ever locked out by accident. Specific tenants can
be comped via HALIA_FREE_SHOPS.

    POST /v1/checkout      — create a Checkout Session, return its URL (auth: tenant cookie)
    POST /webhooks/stripe  — Stripe events: mark a tenant active / canceled

Stripe is called over its REST API with `requests` (no SDK dependency), mirroring the Brevo
email integration.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import Body, Depends, HTTPException, Request

from halia import config
from halia.api.roles import require_manager
from halia.api.shopify_auth import require_shop, shop_store

_ACTIVE = {"active", "trialing", "comped", "complete"}


def billing_enabled() -> bool:
    return bool(config.STRIPE_SECRET_KEY and (config.STRIPE_PRICE_ID or config.STRIPE_TIERS))


def _tier_cap(s: str):
    """A tier's customer cap: ''/'*'/'inf' -> unlimited; '15k'/'15000'/'15,000' -> int; else None."""
    s = s.strip().lower()
    if s in ("", "*", "inf"):
        return float("inf")
    s = s.replace(",", "").replace("k", "000")
    return int(s) if s.isdigit() else None


def _parse_tiers() -> list[tuple[float, str]]:
    """[(max_customers, price_id)] ascending from config.STRIPE_TIERS; [] when unset/empty."""
    tiers: list[tuple[float, str]] = []
    for part in (config.STRIPE_TIERS or "").split(","):
        if ":" not in part:
            continue
        cap_s, pid = part.split(":", 1)
        cap, pid = _tier_cap(cap_s), pid.strip()
        if cap is not None and pid:
            tiers.append((cap, pid))
    tiers.sort(key=lambda t: t[0])
    return tiers


def _scanned_count(shop: str) -> int:
    """Total customers scanned for this shop (its 'DB size'); 0 if not scored/available yet."""
    try:
        from halia.api import data
        entry = data.results_for(shop)
        return len(entry["results"]) if entry and entry.get("results") else 0
    except Exception:  # noqa: BLE001 — best-effort; never block checkout on the count
        return 0


def _is_storeconcierge(shop: str) -> bool:
    """True when this tenant is on the Store Concierge brand (flat £14 clienteling plan)."""
    try:
        from halia.storeconcierge.tenant import brand_of
        return brand_of(shop) == "storeconcierge"
    except Exception:  # noqa: BLE001 — never let a brand lookup break checkout
        return False


def price_for_shop(shop: str) -> str | None:
    """The Stripe price for this tenant: Store Concierge tenants get their own flat price; otherwise
    the size tier the customer count falls in, else the single STRIPE_PRICE_ID. A store scanned at 0
    (cache cold) defaults to the smallest tier."""
    if _is_storeconcierge(shop) and config.STRIPE_PRICE_STORECONCIERGE:
        return config.STRIPE_PRICE_STORECONCIERGE
    tiers = _parse_tiers()
    if not tiers:
        return config.STRIPE_PRICE_ID
    count = _scanned_count(shop)
    for cap, pid in tiers:                      # ascending — the first tier the store fits under
        if count <= cap:
            return pid
    return tiers[-1][1]                          # above every finite cap -> the top tier


# Human plan names by ascending tier rank (the size tiers carry no name of their own).
_TIER_NAMES = ["Discovery", "Signal", "Atelier", "Maison"]


def plan_for_shop(shop: str) -> dict | None:
    """The matched plan for the paywall: {name, count} from the shop's scanned book size.

    Turns the gate from a generic "subscribe" into "your book: 47,015 customers -> Signal". None
    when tiered pricing is not configured (single-price or billing off).
    """
    if _is_storeconcierge(shop):
        return {"name": "Store Concierge", "count": _scanned_count(shop)}
    tiers = _parse_tiers()
    if not tiers:
        return None
    count = _scanned_count(shop)
    idx = next((i for i, (cap, _) in enumerate(tiers) if count <= cap), len(tiers) - 1)
    name = _TIER_NAMES[idx] if idx < len(_TIER_NAMES) else f"Tier {idx + 1}"
    return {"name": name, "count": int(count)}


def plan_links() -> dict:
    """Map of plan key -> Stripe Payment Link, parsed from config.STRIPE_PLAN_LINKS."""
    out = {}
    for part in (config.STRIPE_PLAN_LINKS or "").split(","):
        if "=" in part:
            key, url = part.split("=", 1)
            key, url = key.strip().lower(), url.strip()
            if key and url.startswith("http"):
                out[key] = url
    return out


def link_with_ref(url: str, shop: str) -> str:
    """Attach the shop as Stripe's client_reference_id so a Payment Link checkout can be traced back
    to this tenant by the webhook (Payment Links are static and otherwise carry no shop identity)."""
    if not url:
        return url
    import urllib.parse
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}client_reference_id={urllib.parse.quote(shop, safe='')}"


def _norm_key(v: str) -> str:
    """A tenant key however it was typed: 'https://glennorah.co.uk/' and 'glennorah-co-uk' match."""
    import re as _re
    s = _re.sub(r"^https?://", "", str(v or "").strip().lower()).strip("/")
    s = _re.sub(r"^www[.-]", "", s)
    return _re.sub(r"[^a-z0-9.]+", "-", s).strip("-")


def _free_shops():
    """Comped tenant keys: the console's dashboard override, else env HALIA_FREE_SHOPS. Every
    entry is kept both as typed and normalised, so a store URL, a slug or a myshopify domain all
    comp the same tenant."""
    from halia.console_config import console_setting
    raw = console_setting("free_shops", config.HALIA_FREE_SHOPS) or []
    out = set()
    for v in raw:
        v = str(v or "").strip()
        if not v:
            continue
        out.add(v); out.add(v.lower()); out.add(_norm_key(v)); out.add(_norm_key(v).replace(".", "-"))
    return out


def is_paid(shop: str) -> bool:
    """True if this tenant may see the full dashboard. Open when billing is off or comped."""
    if not billing_enabled():
        return True
    free = _free_shops()
    if shop in free or shop.lower() in free or _norm_key(shop) in free or _norm_key(shop).replace(".", "-") in free:
        return True
    b = shop_store().get_billing(shop)
    return bool(b and b.get("status") in _ACTIVE)


def _stripe(method: str, path: str, data: dict | None = None) -> dict:
    import requests

    resp = requests.request(method, f"https://api.stripe.com/v1/{path}",
                            auth=(config.STRIPE_SECRET_KEY, ""), data=data, timeout=20)
    if not (200 <= resp.status_code < 300):
        raise HTTPException(502, f"Stripe error: {resp.text[:200]}")
    return resp.json()


def create_checkout(shop: str) -> str:
    """Create a subscription Checkout Session for this tenant and return its hosted URL."""
    base = config.HALIA_APP_URL or ""
    data = {
        "mode": "subscription",
        "line_items[0][price]": price_for_shop(shop),   # size-based tier, else the single price
        "line_items[0][quantity]": "1",
        "client_reference_id": shop,
        "metadata[shop]": shop,
        "subscription_data[metadata][shop]": shop,
        "success_url": f"{base}/app?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/app",
        "allow_promotion_codes": "true",
    }
    return _stripe("POST", "checkout/sessions", data)["url"]


def create_plan_checkout(shop: str, plan_key: str) -> str:
    """A Stripe Checkout Session for one specific plan, priced inline from the plan catalogue.

    This is the bridge-tenant path when no Payment Link is configured for the plan: with just
    STRIPE_SECRET_KEY set, choosing a plan still lands on real Stripe Checkout. A configured
    STRIPE_PLAN_LINKS link is preferred by the frontend and never reaches here."""
    from halia import plans as plancat
    if not config.STRIPE_SECRET_KEY:
        raise HTTPException(400, "Stripe is not configured yet.")
    if not plancat.billable(plan_key):
        raise HTTPException(400, "That plan can't be subscribed to here.")
    p = plancat.plan(plan_key)
    base = config.HALIA_APP_URL or ""
    data = {
        "mode": "subscription",
        "line_items[0][price_data][currency]": plancat.CURRENCY.lower(),
        "line_items[0][price_data][unit_amount]": str(int(round(plancat.amount(plan_key) * 100))),
        "line_items[0][price_data][recurring][interval]": "month",
        "line_items[0][price_data][product_data][name]": f"Halia {p['name']}",
        "line_items[0][quantity]": "1",
        "client_reference_id": shop,
        "metadata[shop]": shop,
        "subscription_data[metadata][shop]": shop,
        "success_url": f"{base}/app?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/app",
        "allow_promotion_codes": "true",
    }
    return _stripe("POST", "checkout/sessions", data)["url"]


def create_portal(shop: str) -> str:
    """Create a Stripe Billing Portal session so the tenant can manage their subscription
    (update card, view invoices, cancel). Requires an existing Stripe customer."""
    b = shop_store().get_billing(shop) or {}
    customer = b.get("customer_id")
    if not customer:
        raise HTTPException(400, "No billing account yet — subscribe first.")
    base = config.HALIA_APP_URL or ""
    return _stripe("POST", "billing_portal/sessions",
                   {"customer": customer, "return_url": f"{base}/app"})["url"]


def _subscription(shop: str) -> dict | None:
    """Fetch this tenant's Stripe subscription (best-effort; None on any problem)."""
    b = shop_store().get_billing(shop) or {}
    sub_id = b.get("subscription_id")
    if not (billing_enabled() and sub_id):
        return None
    try:
        return _stripe("GET", f"subscriptions/{sub_id}")
    except Exception:  # noqa: BLE001
        return None


def set_cancel(shop: str, cancel: bool) -> dict:
    """Schedule (or undo) cancellation at the end of the current period. The tenant keeps
    access until then — no mid-cycle lockout. Returns the new cancel flag + period end."""
    b = shop_store().get_billing(shop) or {}
    sub_id = b.get("subscription_id")
    if not sub_id:
        raise HTTPException(400, "No active subscription to change.")
    sub = _stripe("POST", f"subscriptions/{sub_id}",
                  {"cancel_at_period_end": "true" if cancel else "false"})
    try:
        from halia import journeys
        if sub.get("cancel_at_period_end"):
            journeys.enroll_cancel_ending(shop, sub.get("current_period_end"))
        else:
            journeys.cancel_cancel_ending(shop)
    except Exception:  # noqa: BLE001
        pass
    return {"cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
            "current_period_end": sub.get("current_period_end")}


def on_billing_change(shop: str, status: str) -> None:
    """Journeys follow the plan: active starts the client series and stops the free-scan and
    win-back mail; canceled starts the win-back. Best-effort."""
    try:
        from halia import journeys
        if status == "active":
            journeys.on_subscribed(shop)
        elif status == "canceled":
            journeys.enroll_winback(shop)
    except Exception:  # noqa: BLE001
        pass


def cancel_now(shop: str) -> None:
    """Immediately cancel the tenant's Stripe subscription. Used when a tenant deletes
    their account so they are not billed for a period they can no longer reach. Best-effort:
    account deletion must still proceed even if Stripe is unset or unreachable."""
    if not billing_enabled():
        return
    b = shop_store().get_billing(shop) or {}
    sub_id = b.get("subscription_id")
    if not sub_id:
        return
    try:
        _stripe("DELETE", f"subscriptions/{sub_id}")
    except Exception:  # noqa: BLE001 — never block erasure on a billing hiccup
        pass


RETENTION_PERCENT = 50


def apply_retention(shop: str) -> dict:
    """Retention offer: apply a 50%-off discount to this tenant's subscription."""
    b = shop_store().get_billing(shop) or {}
    sub_id = b.get("subscription_id")
    if not sub_id:
        raise HTTPException(400, "No active subscription to discount.")
    coupon = config.STRIPE_RETENTION_COUPON
    if not coupon:
        coupon = _stripe("POST", "coupons", {
            "percent_off": str(RETENTION_PERCENT), "duration": "forever",
            "name": f"Halia retention {RETENTION_PERCENT}% off"})["id"]
    _stripe("POST", f"subscriptions/{sub_id}", {"coupon": coupon})
    return {"ok": True, "percent_off": RETENTION_PERCENT}


def _record_cancel_reason(shop: str, reason: str = "", detail: str = "") -> None:
    """Best-effort: keep the merchant's stated cancellation reason (survey) for our team."""
    if not (reason or detail):
        return
    try:
        raw = shop_store().get_settings_raw(shop)
        s = json.loads(raw) if raw else {}
        s["cancel_reason"] = (reason or "")[:200]
        s["cancel_detail"] = (detail or "")[:1000]
        shop_store().save_settings(shop, json.dumps(s))
    except Exception:  # noqa: BLE001
        pass


def billing_state(shop: str) -> dict:
    """A small, UI-friendly summary of this tenant's billing state."""
    b = shop_store().get_billing(shop) or {}
    comped = shop in _free_shops()
    status = "comped" if comped else (b.get("status") or "free")
    manageable = bool(billing_enabled() and b.get("customer_id") and not comped)
    state = {
        "enabled": billing_enabled(),
        "paid": is_paid(shop),
        "comped": comped,
        "status": status,
        "manageable": manageable,
        "cancellable": bool(manageable and b.get("subscription_id") and is_paid(shop)),
        "cancel_at_period_end": False,
        "current_period_end": None,
    }
    sub = _subscription(shop) if state["cancellable"] else None
    if sub:
        state["cancel_at_period_end"] = bool(sub.get("cancel_at_period_end"))
        state["current_period_end"] = sub.get("current_period_end")
    # Matched plan for the paywall (only useful before they subscribe, and only with tiered pricing).
    if state["enabled"] and not state["paid"] and not comped:
        state["plan"] = plan_for_shop(shop)
    return state


def confirm_session(shop: str, session_id: str) -> bool:
    """Verify a returning Checkout session and, if paid, mark the tenant active."""
    if not billing_enabled() or not session_id:
        return is_paid(shop)
    try:
        sess = _stripe("GET", f"checkout/sessions/{session_id}")
    except Exception:  # noqa: BLE001 — fall back to stored status
        return is_paid(shop)
    if sess.get("client_reference_id") and sess["client_reference_id"] != shop:
        return is_paid(shop)
    if sess.get("payment_status") == "paid" or sess.get("status") == "complete":
        shop_store().set_billing(shop, "active", sess.get("customer"), sess.get("subscription"))
        on_billing_change(shop, "active")
        return True
    return is_paid(shop)


def stripe_plans_payload(shop: str) -> dict:
    """The plan catalogue with each tier's Stripe Payment Link, plus the tenant's billing state.
    Served to hosted (non-Shopify) tenants at /v1/billing/plans, and to Shopify tenants on a
    custom-distribution bridge app (which cannot use Shopify's Billing API) via /v1/plans/status.
    ``stripe: True`` tells the dashboard to render Stripe link CTAs instead of Shopify buttons."""
    from halia import plans as plancat
    links = plan_links()
    state = billing_state(shop)
    common = {"stripe": True, "checkout": bool(config.STRIPE_SECRET_KEY),
              "enabled": state["enabled"], "paid": state["paid"],
              "comped": state["comped"], "status": state["status"],
              "manageable": state["manageable"]}
    # Store Concierge is its own brand and one flat plan — never the Halia wealth-engine tiers.
    if _is_storeconcierge(shop):
        card = plancat.storeconcierge_card()
        card["link"] = link_with_ref(links.get("storeconcierge", ""), shop)
        return {"plans": [card], "recommended": "Store Concierge", **common}
    cards = []
    for p in plancat.public_catalogue():
        p = dict(p)
        p["link"] = link_with_ref(links.get(p["key"], ""), shop)
        cards.append(p)
    return {"plans": cards, "recommended": (plan_for_shop(shop) or {}).get("name"), **common}


def stripe_plan_key(shop: str) -> str:
    """The plan a Stripe-billed tenant is on, as a catalogue key. Read from the subscription's
    tier price when tiers are configured; else the size-recommended tier; 'free' when unpaid."""
    from halia import plans as plancat

    if not billing_enabled() or shop in _free_shops():
        return "maison"       # billing off or comped = everything open, seats not metered
    b = shop_store().get_billing(shop)
    if not (b and b.get("status") in _ACTIVE):
        return "free"
    by_key = {p["name"].strip().lower(): p["key"] for p in plancat.public_catalogue()}
    tier_names = {pid: _TIER_NAMES[i] for i, (_, pid) in enumerate(_parse_tiers()) if i < len(_TIER_NAMES)}
    sub = _subscription(shop) or {}
    for item in ((sub.get("items") or {}).get("data") or []):
        name = tier_names.get(((item.get("price") or {}).get("id")) or "")
        if name and name.lower() in by_key:
            return by_key[name.lower()]
    rec = (plan_for_shop(shop) or {}).get("name") or ""
    return by_key.get(rec.lower(), "signal")


def sync_seat_quantity(shop: str) -> dict:
    """Keep the seat add-on line on this tenant's Stripe subscription at quantity = seats beyond
    the bundle. Stripe prorates the change itself. Idempotent; safe to run hourly."""
    from halia import plans as plancat

    if not (billing_enabled() and config.STRIPE_SEAT_PRICE_ID):
        return {"shop": shop, "skipped": "seat price not configured"}
    if shop in _free_shops():
        return {"shop": shop, "skipped": "comped"}
    key = stripe_plan_key(shop)
    if plancat.included_seats(key) is None:
        return {"shop": shop, "skipped": "seats not metered"}
    sub = _subscription(shop)
    if not sub or sub.get("status") not in ("active", "trialing", "past_due"):
        return {"shop": shop, "skipped": "no active subscription"}
    extra = min(plancat.extra_seats(key, shop_store().active_seat_count(shop)), plancat.SEAT_CAP)
    item = next((i for i in ((sub.get("items") or {}).get("data") or [])
                 if ((i.get("price") or {}).get("id")) == config.STRIPE_SEAT_PRICE_ID), None)
    have = int(item.get("quantity") or 0) if item else 0
    if have == extra:
        return {"shop": shop, "plan": key, "extra": extra, "posted": 0}
    if item and extra == 0:
        _stripe("DELETE", f"subscription_items/{item['id']}", {"proration_behavior": "create_prorations"})
    elif item:
        _stripe("POST", f"subscription_items/{item['id']}",
                {"quantity": extra, "proration_behavior": "create_prorations"})
    else:
        _stripe("POST", "subscription_items", {"subscription": sub["id"], "price": config.STRIPE_SEAT_PRICE_ID,
                                                "quantity": extra, "proration_behavior": "create_prorations"})
    if extra > have:
        from halia.api.billing_shopify import overage_email
        overage_email(shop, key, extra - have, extra)
    return {"shop": shop, "plan": key, "extra": extra, "posted": extra - have}


def run_stripe_seat_billing() -> dict:
    """Hourly sweep over Stripe-billed tenants (hosted stores and bridge-app Shopify stores)."""
    from halia.api.billing_shopify import _stripe_billed

    out = {"checked": 0, "posted": 0, "errors": 0}
    if not (billing_enabled() and config.STRIPE_SEAT_PRICE_ID):
        return out
    for t in shop_store().all_tenants():
        t = dict(t)
        if t.get("kind") in (None, "", "shopify") and not _stripe_billed(t["shop"]):
            continue                              # the Shopify usage-record sweep owns these
        bill = shop_store().get_billing(t["shop"])
        if not bill or dict(bill).get("status") not in _ACTIVE:
            continue
        out["checked"] += 1
        try:
            r = sync_seat_quantity(t["shop"])
            out["posted"] += max(0, int(r.get("posted") or 0))
        except Exception:  # noqa: BLE001 — one shop's hiccup must not stop the sweep
            out["errors"] += 1
    return out


def _verify_sig(body: bytes, sig_header: str, secret: str, tolerance: int = 300) -> bool:
    """Verify a Stripe webhook signature (HMAC-SHA256 over `t.payload`), rejecting stale events.

    ``tolerance`` (seconds) bounds how old the signed timestamp may be, so a captured valid event
    cannot be replayed indefinitely.
    """
    try:
        import time as _t
        pairs = [p.split("=", 1) for p in sig_header.split(",")]
        t = next(v for k, v in pairs if k == "t")
        if tolerance and abs(_t.time() - int(t)) > tolerance:
            return False
        sigs = [v for k, v in pairs if k == "v1"]
        expected = hmac.new(secret.encode(), t.encode() + b"." + body, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, s) for s in sigs)
    except Exception:  # noqa: BLE001
        return False


def register(app) -> None:

    @app.post("/v1/checkout")
    def checkout(shop: str = Depends(require_manager)) -> dict:
        if not billing_enabled():
            return {"url": "/app"}  # nothing to pay for; the dashboard is already open
        return {"url": create_checkout(shop)}

    @app.get("/v1/billing/status")
    def billing_status(shop: str = Depends(require_shop)) -> dict:
        return billing_state(shop)

    @app.get("/v1/billing/plans")
    def billing_plans(shop: str = Depends(require_shop)) -> dict:
        """The plan catalogue for the in-app Plans cards, each with its Stripe Payment Link, plus
        the tenant's billing state and the tier recommended for their book size."""
        return stripe_plans_payload(shop)

    @app.post("/v1/billing/checkout-plan")
    def billing_checkout_plan(shop: str = Depends(require_manager),
                              payload: dict = Body(default={})) -> dict:
        """Stripe Checkout for one named plan (bridge tenants without Payment Links)."""
        key = str((payload or {}).get("plan", "")).strip().lower()
        return {"url": create_plan_checkout(shop, key)}

    @app.post("/v1/billing/portal")
    def billing_portal(shop: str = Depends(require_manager)) -> dict:
        if not billing_enabled():
            raise HTTPException(400, "Billing isn't enabled.")
        return {"url": create_portal(shop)}

    @app.post("/v1/billing/cancel")
    def billing_cancel(shop: str = Depends(require_manager),
                       payload: dict = Body(default={})) -> dict:
        """Self-service cancel at the end of the current period (keeps access until then).
        Optionally records the merchant's stated reason from the cancellation survey."""
        if not billing_enabled():
            raise HTTPException(400, "Billing isn't enabled.")
        p = payload or {}
        _record_cancel_reason(shop, str(p.get("reason", "")), str(p.get("detail", "")))
        return set_cancel(shop, True)

    @app.post("/v1/billing/resume")
    def billing_resume(shop: str = Depends(require_manager)) -> dict:
        """Undo a scheduled cancellation — keep the subscription running."""
        if not billing_enabled():
            raise HTTPException(400, "Billing isn't enabled.")
        return set_cancel(shop, False)

    @app.post("/v1/billing/retention")
    def billing_retention(shop: str = Depends(require_shop)) -> dict:
        """Accept the 50%-off retention offer instead of cancelling."""
        if not billing_enabled():
            raise HTTPException(400, "Billing isn't enabled.")
        return apply_retention(shop)

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request) -> dict:
        body = await request.body()
        # SECURITY: fail CLOSED. When billing is live, an unverified event must never be trusted —
        # otherwise a forged checkout.session.completed marks any tenant paid for free. If the
        # webhook secret is not configured yet, reject every event rather than skipping the check.
        if billing_enabled() and not config.STRIPE_WEBHOOK_SECRET:
            raise HTTPException(503, "Billing webhook not configured")
        if config.STRIPE_WEBHOOK_SECRET:
            if not _verify_sig(body, request.headers.get("stripe-signature", ""),
                               config.STRIPE_WEBHOOK_SECRET):
                raise HTTPException(400, "Bad signature")
        try:
            event = json.loads(body.decode() or "{}")
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Bad payload")
        obj = (event.get("data") or {}).get("object") or {}
        typ = event.get("type", "")
        store = shop_store()
        shop = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("shop")
        if not shop:
            # Payment Link subscriptions carry no shop on later events — map back by stored ids.
            sub_id = obj.get("id") if typ.startswith("customer.subscription.") else obj.get("subscription")
            shop = store.billing_shop_for(subscription_id=sub_id, customer_id=obj.get("customer"))
        if not shop:
            return {"received": True}
        if typ == "checkout.session.completed":
            store.set_billing(shop, "active", obj.get("customer"), obj.get("subscription"))
            on_billing_change(shop, "active")
        elif typ == "customer.subscription.deleted":
            store.set_billing(shop, "canceled")
            on_billing_change(shop, "canceled")
        elif typ == "customer.subscription.updated":
            store.set_billing(shop, obj.get("status") or "active")
            on_billing_change(shop, obj.get("status") or "active")
        return {"received": True}
