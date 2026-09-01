"""Routes for the lifecycle-email engine: one-click unsubscribe + the scheduler tick.

  GET  /email/unsubscribe?e=&s=  — public; a signed link in every lifecycle email. Suppresses
                                   the address so no further journey mail is sent.
  POST /internal/cron/run        — protected by the X-Cron-Key header (config.CRON_KEY). A Render
                                   Cron Job pokes it periodically; it sends any due journey steps.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from halia import config, journeys
from halia.api.shopify_auth import shop_store

_UNSUB_PAGE = (
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>{title} · Halia</title>"
    "<div style=\"font:16px/1.6 Helvetica,Arial,sans-serif;color:#1a1712;background:#f5f2ea;"
    "min-height:100vh;margin:0;display:flex;align-items:center;justify-content:center;padding:24px\">"
    "<div style=\"background:#fff;border:1px solid #e4dfd3;border-radius:16px;padding:34px 34px;"
    "max-width:460px;text-align:center\">"
    "<div style=\"font:300 24px Georgia,serif;margin-bottom:14px\">"
    "<span style=color:#1f564a>&#8258;</span>&nbsp;Halia</div>"
    "<h1 style=\"font:600 20px Helvetica,Arial,sans-serif;margin:0 0 8px\">{title}</h1>"
    "<p style=\"color:#6b675e;margin:0\">{body}</p></div></div>")


# Tomorrow's visits, once an hour. Reading appointments means reading the merchant's own store,
# which is not free, so only shops that have actually booked recently are looked at — the metric
# Halia already keeps for its own dashboard, so this costs one local count per tenant.
_REMINDER_METRIC = "extension_appointment"
_REMINDER_WEEKS = 4


def run_visit_reminders(store=None) -> dict:
    from halia.api import appointments as appts
    from halia.api.capture_alerts import dispatch_visit_reminder
    from halia.api.shopify_auth import shop_store
    from halia.store import _iso_week

    st = store or shop_store()
    weeks = _recent_weeks(_REMINDER_WEEKS)
    looked, told = 0, 0
    for tenant in st.all_tenants():
        shop = tenant["shop"] if not isinstance(tenant, str) else tenant
        try:
            booked = sum(st.shop_metric(shop, _REMINDER_METRIC, week=w) for w in weeks)
        except Exception:  # noqa: BLE001
            booked = 0
        if not booked:
            continue
        looked += 1
        try:
            told += dispatch_visit_reminder(shop, appts.due_reminders(shop))
        except Exception:  # noqa: BLE001 — one bad store never stops the rest
            continue
    return {"shops": looked, "visits": told}


def _recent_weeks(n: int) -> list[str]:
    from datetime import date, timedelta
    today = date.today()
    return sorted({(today - timedelta(weeks=i)).strftime("%G-W%V") for i in range(n)})


def register(app) -> None:

    @app.get("/email/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
    def email_unsubscribe(e: str = "", s: str = ""):
        email = (e or "").strip().lower()
        if email and journeys.unsub_valid(email, s):
            shop_store().suppress_email(email, "unsubscribe")
            return HTMLResponse(_UNSUB_PAGE.format(
                title="You're unsubscribed",
                body="You will not receive further Halia emails. You can reply to any earlier "
                     "message if you change your mind."))
        return HTMLResponse(_UNSUB_PAGE.format(
            title="Link not recognised",
            body="This unsubscribe link is invalid or has expired."), status_code=400)

    @app.post("/internal/cron/run", include_in_schema=False)
    def cron_run(request: Request, x_cron_key: str = Header(default="")):
        if not config.CRON_KEY or not hmac.compare_digest(x_cron_key, config.CRON_KEY):
            raise HTTPException(403, "Not authorised.")
        out_ensure = {}
        try:
            out_ensure = journeys.ensure_journeys()
        except Exception:  # noqa: BLE001 — the recap must never block the run
            pass
        out = journeys.run_due()
        out["enrolled"] = out_ensure
        try:
            out["visit_reminders"] = run_visit_reminders()
        except Exception:  # noqa: BLE001 — a reminder must never break the run
            out["visit_reminders"] = {"error": True}
        try:
            from halia.api import billing_shopify
            out["seat_billing"] = billing_shopify.run_seat_billing()
        except Exception:  # noqa: BLE001 — billing must never break the journeys run
            out["seat_billing"] = {"error": True}
        try:
            from halia.api import billing
            out["seat_billing_stripe"] = billing.run_stripe_seat_billing()
        except Exception:  # noqa: BLE001
            out["seat_billing_stripe"] = {"error": True}
        return JSONResponse(out)
