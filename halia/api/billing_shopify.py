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
from halia.api.shopify_auth import require_shop, shop_store

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

_ACTIVE_SUBS = "{ currentAppInstallation { activeSubscriptions { id name status } } }"


def _token(shop: str) -> str | None:
    """The shop's offline Admin token — present only for a Shopify tenant (None for Woo etc.)."""
    return shop_store().get_token(shop)


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


def _admin_app_url(shop: str) -> str:
    """Deep link back into the embedded app inside Shopify admin (top-level, re-embeds the app)."""
    handle = config.SHOPIFY_APP_HANDLE or config.SHOPIFY_API_KEY
    store = shop.replace(".myshopify.com", "")
    if handle:
        return f"https://admin.shopify.com/store/{store}/apps/{handle}"
    return (config.HALIA_APP_URL or "") + "/app"


def register(app) -> None:

    @app.get("/v1/plans/status")
    def plans_status(shop: str = Depends(require_shop)) -> dict:
        """The plan catalogue plus this shop's current plan and whether it can self-serve billing."""
        shopify = bool(_token(shop))
        return {
            "plans": plans.public_catalogue(),
            "current": _current_plan_key(shop) if shopify else "free",
            "shopify": shopify,          # Shopify Billing only applies to a Shopify tenant
            "test": bool(config.SHOPIFY_BILLING_TEST),
            "currency": plans.CURRENCY,
        }

    @app.post("/v1/plans/subscribe")
    def plans_subscribe(shop: str = Depends(require_shop), payload: dict = Body(default={})) -> dict:
        key = str((payload or {}).get("plan", "")).strip().lower()
        p = plans.plan(key)
        if not p:
            raise HTTPException(400, "Unknown plan.")
        if not plans.billable(key):
            raise HTTPException(400, "That plan can't be subscribed to here.")
        if not _token(shop):
            raise HTTPException(400, "Shopify billing is only available inside the Shopify app.")
        base = config.HALIA_APP_URL or ""
        return_url = f"{base}/v1/plans/activate?shop={shop}"
        variables = {
            "name": p["name"],
            "returnUrl": return_url,
            "test": bool(config.SHOPIFY_BILLING_TEST),
            "lineItems": [{"plan": {"appRecurringPricingDetails": {
                "price": {"amount": plans.amount(key), "currencyCode": plans.CURRENCY},
                "interval": plans.INTERVAL}}}],
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
