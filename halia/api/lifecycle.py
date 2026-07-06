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
        return JSONResponse(journeys.run_due())
