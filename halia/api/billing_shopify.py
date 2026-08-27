"""Shopify Billing: the embedded app's Plans screen subscribes via Shopify's recurring app charges.

A merchant picks a tier on the Plans screen; we create an ``appSubscription`` and hand back the
``confirmationUrl``, which the app opens at the TOP of the window (out of the admin iframe). Shopify
takes the merchant through approval, then redirects the top window back to ``/v1/plans/activate``,
where we confirm the subscription is live, mark the tenant active in the shared ``billing`` table
(so the existing paywall reads it too), and bounce back into the embedded app.

Only billing state is stored (status + the Shopify subscription id) — never anything about customers.
Test mode (config.SHOPIFY_BILLING_TEST) runs the real approval flow without charging, for pre-launch.

    GET  /v1/plans/status     — the catalogue + this shop's current plan (auth: session token)
    POST /v1/plans/subscribe  — create a subscription for {plan}, return its confirmationUrl
    GET  /v1/plans/activate   — Shopify's return target: confirm + persist, then re-enter the app
    POST /v1/plans/cancel     — cancel the active subscription (downgrade to Free)
"""
from __future__ import annotations

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from halia import config, plans
from halia.api.shopify_auth import get_valid_token, require_shop, shop_store

_CREATE = """
mutation CreateSub($name:String!,$returnUrl:URL!,$test:Boolean,$lineItems:[AppSubscriptionLineItemInput!]!){
  appSubscriptionCreate(name:$name, returnUrl:$returnUrl, test:$test, lineItems:$lineItems){
    userErrors{ field message }
    confirmationUrl
    appSubscription{ id status }
  }
}"""

_CANCEL = """
mutation CancelSub($id:ID!){
  appSubscriptionCancel(id:$id){ userErrors{ field message } appSubscription{ id status } }
}"""

_ACTIVE_SUBS = """{ currentAppInstallation { activeSubscriptions {
  id name status currentPeriodEnd
  lineItems { id plan { pricingDetails { __typename } } } } } }"""

_USAGE_CREATE = """
mutation Usage($lineItemId:ID!,$description:String!,$price:MoneyInput!){
  appUsageRecordCreate(subscriptionLineItemId:$lineItemId, description:$description, price:$price){
    userErrors{ field message }
    appUsageRecord{ id }
  }
}"""


def _token(shop: str) -> str | None:
    """The shop's offline Admin token — present only for a Shopify tenant (None for Woo etc.)."""
    return get_valid_token(shop)


def _transport(shop: str):
    from scoring.shopify_fetch import http_transport
    return http_transport(shop, _token(shop))


def _gql(shop: str, query: str, variables: dict) -> dict:
    from scoring.shopify_fetch import _run
    return _run(_transport(shop), query, variables, 2)


def _user_errors(data: dict, field: str) -> None:
    errs = ((data or {}).get(field) or {}).get("userErrors") or []
    if errs:
        raise HTTPException(502, "; ".join(e.get("message", "error") for e in errs)[:300])


def active_subscription(shop: str) -> dict | None:
    """The shop's live Shopify app subscription {id,name,status}, or None. Best-effort."""
    if not _token(shop):
        return None
    try:
        data = _gql(shop, _ACTIVE_SUBS, {})
    except Exception:  # noqa: BLE001 — the Plans screen must still render on a Shopify hiccup
        return None
    subs = (((data or {}).get("currentAppInstallation") or {}).get("activeSubscriptions") or [])
    for s in subs:
        if s.get("status") == "ACTIVE":
            return s
    return subs[0] if subs else None


def _current_plan_key(shop: str) -> str:
    """Map the live Shopify subscription back to a plan key; 'free' when there is none."""
    sub = active_subscription(shop)
    if not sub or sub.get("status") != "ACTIVE":
        return "free"
    name = (sub.get("name") or "").strip().lower()
    for p in plans.public_catalogue():
        if p["name"].strip().lower() == name or p["key"] == name:
            return p["key"]
    return "free"


def _line_items(key: str) -> list[dict]:
    """The recurring plan, plus a capped usage line for extra seats on metered plans. The
    merchant approves both once; seats beyond the bundle are then posted as usage records."""
    items = [{"plan": {"appRecurringPricingDetails": {
        "price": {"amount": plans.amount(key), "currencyCode": plans.CURRENCY},
        "interval": plans.INTERVAL}}}]
    if plans.included_seats(key) is not None:
        items.append({"plan": {"appUsagePricingDetails": {
            "cappedAmount": {"amount": plans.SEAT_PRICE * plans.SEAT_CAP,
                             "currencyCode": plans.CURRENCY},
            "terms": plans.seat_terms(key)}}})
    return items


def _usage_line_id(sub: dict | None) -> str | None:
    for li in ((sub or {}).get("lineItems") or []):
        if ((li.get("plan") or {}).get("pricingDetails") or {}).get("__typename") == "AppUsagePricing":
            return li.get("id")
    return None


def _seat_state(shop: str) -> dict:
    import json
    raw = shop_store().get_settings_raw(shop)
    d = json.loads(raw) if raw else {}
    return dict(d.get("seat_billing") or {})


def _save_seat_state(shop: str, state: dict) -> None:
    import json
    raw = shop_store().get_settings_raw(shop)
    d = json.loads(raw) if raw else {}
    d["seat_billing"] = state
    shop_store().save_settings(shop, json.dumps(d))


def bill_seats(shop: str) -> dict:
    """Post a usage record for seats beyond the plan's bundle, once per billing period, plus a
    top-up when the team grows mid-period. Idempotent; safe to run hourly. Returns what happened."""
    if _stripe_billed(shop) or not _token(shop):
        return {"shop": shop, "skipped": "not shopify-billed"}
    sub = active_subscription(shop)
    if not sub or sub.get("status") != "ACTIVE":
        return {"shop": shop, "skipped": "no active subscription"}
    key = _current_plan_key(shop)
    if plans.included_seats(key) is None:
        return {"shop": shop, "skipped": "seats not metered"}
    line = _usage_line_id(sub)
    if not line:
        return {"shop": shop, "skipped": "subscription predates seat billing"}
    period = str(sub.get("currentPeriodEnd") or "")
    extra = min(plans.extra_seats(key, shop_store().active_seat_count(shop)), plans.SEAT_CAP)
    state = _seat_state(shop)
    charged = int(state.get("charged") or 0) if state.get("period") == period else 0
    delta = extra - charged
    if delta <= 0:
        return {"shop": shop, "period": period, "extra": extra, "charged": charged, "posted": 0}
    amount = delta * plans.SEAT_PRICE
    data = _gql(shop, _USAGE_CREATE, {
        "lineItemId": line,
        "description": f"{delta} additional associate seat{'s' if delta != 1 else ''} · Halia {plans.plan(key)['name']}",
        "price": {"amount": amount, "currencyCode": plans.CURRENCY}})
    _user_errors(data, "appUsageRecordCreate")
    _save_seat_state(shop, {"period": period, "charged": extra,
                            "last_record": ((data.get("appUsageRecordCreate") or {})
                                            .get("appUsageRecord") or {}).get("id")})
    return {"shop": shop, "period": period, "extra": extra, "charged": extra, "posted": delta,
            "amount": amount}


def run_seat_billing() -> dict:
    """Hourly sweep over Shopify-billed tenants. Best-effort per shop; never raises."""
    out = {"checked": 0, "posted": 0, "errors": 0}
    for t in shop_store().all_tenants():
        t = dict(t)
        if t.get("kind") not in (None, "", "shopify"):
            continue
        bill = shop_store().get_billing(t["shop"])
        if not bill or dict(bill).get("status") != "active":
            continue
        out["checked"] += 1
        try:
            r = bill_seats(t["shop"])
            out["posted"] += int(r.get("posted") or 0)
        except Exception:  # noqa: BLE001 — one shop's hiccup must not stop the sweep
            out["errors"] += 1
    return out


def _admin_app_url(shop: str) -> str:
    """Deep link back into the embedded app inside Shopify admin (top-level, re-embeds the app)."""
    handle = config.SHOPIFY_APP_HANDLE or config.SHOPIFY_API_KEY
    store = shop.replace(".myshopify.com", "")
    if handle:
        return f"https://admin.shopify.com/store/{store}/apps/{handle}"
    return (config.HALIA_APP_URL or "") + "/app"


def _stripe_billed(shop: str) -> bool:
    """True for a tenant on a custom-distribution bridge app: Shopify forbids such apps the
    Billing API, so these shops subscribe through Stripe instead (payment links / checkout)."""
    return shop in config.SHOPIFY_CUSTOM_APPS


def register(app) -> None:

    @app.get("/v1/plans/status")
    def plans_status(shop: str = Depends(require_shop)) -> dict:
        """The plan catalogue plus this shop's current plan and whether it can self-serve billing."""
        if _stripe_billed(shop):
            from halia.api.billing import stripe_plans_payload
            return stripe_plans_payload(shop)
        shopify = bool(_token(shop))
        current = _current_plan_key(shop) if shopify else "free"
        in_use = shop_store().active_seat_count(shop) if shopify else 0
        return {
            "plans": plans.public_catalogue(),
            "current": current,
            "shopify": shopify,          # Shopify Billing only applies to a Shopify tenant
            "test": bool(config.SHOPIFY_BILLING_TEST),
            "currency": plans.CURRENCY,
            "seatPrice": plans.SEAT_PRICE,
            "seatsInUse": in_use,
            "seatsIncluded": plans.included_seats(current),
            "extraSeats": plans.extra_seats(current, in_use),
            "seatOverage": plans.seat_overage(current, in_use),
            "seatCap": plans.SEAT_CAP,
            "seatBilling": _seat_state(shop) if shopify else {},
        }

    @app.post("/v1/plans/subscribe")
    def plans_subscribe(shop: str = Depends(require_shop), payload: dict = Body(default={})) -> dict:
        key = str((payload or {}).get("plan", "")).strip().lower()
        p = plans.plan(key)
        if not p:
            raise HTTPException(400, "Unknown plan.")
        if not plans.billable(key):
            raise HTTPException(400, "That plan can't be subscribed to here.")
        if _stripe_billed(shop):
            raise HTTPException(400, "This store is billed through Stripe — choose a plan "
                                     "from the plan cards instead.")
        if not _token(shop):
            raise HTTPException(400, "Shopify billing is only available inside the Shopify app.")
        base = config.HALIA_APP_URL or ""
        return_url = f"{base}/v1/plans/activate?shop={shop}"
        variables = {
            "name": p["name"],
            "returnUrl": return_url,
            "test": bool(config.SHOPIFY_BILLING_TEST),
            "lineItems": _line_items(key),
        }
        data = _gql(shop, _CREATE, variables)
        _user_errors(data, "appSubscriptionCreate")
        url = (data.get("appSubscriptionCreate") or {}).get("confirmationUrl")
        if not url:
            raise HTTPException(502, "Shopify did not return a confirmation URL.")
        return {"confirmationUrl": url}

    @app.get("/v1/plans/activate")
    def plans_activate(request: Request):
        """Shopify's return target after approval (loads at the top of the window). Confirm the
        subscription is live, mark the tenant active, then re-enter the embedded app."""
        shop = (request.query_params.get("shop") or "").strip()
        if shop and _token(shop):
            sub = active_subscription(shop)
            if sub and sub.get("status") == "ACTIVE":
                shop_store().set_billing(shop, "active", None, sub.get("id"))
            else:
                shop_store().set_billing(shop, "canceled")
        dest = _admin_app_url(shop) if shop else ((config.HALIA_APP_URL or "") + "/app")
        return RedirectResponse(dest, status_code=302)

    @app.post("/v1/plans/cancel")
    def plans_cancel(shop: str = Depends(require_shop)) -> dict:
        """Cancel the active Shopify subscription (a downgrade to the Free plan)."""
        if _stripe_billed(shop):
            raise HTTPException(400, "This store is billed through Stripe — manage or cancel "
                                     "from the Billing panel in Settings.")
        if not _token(shop):
            raise HTTPException(400, "Shopify billing is only available inside the Shopify app.")
        sub = active_subscription(shop)
        if not sub:
            shop_store().set_billing(shop, "canceled")
            return {"ok": True, "current": "free"}
        data = _gql(shop, _CANCEL, {"id": sub["id"]})
        _user_errors(data, "appSubscriptionCancel")
        shop_store().set_billing(shop, "canceled")
        return {"ok": True, "current": "free"}
