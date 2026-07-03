"""Per-shop Slack alerts via an Incoming Webhook.

The merchant creates a Slack Incoming Webhook for one channel and pastes the URL. When a hidden
VIC places an order, Halia posts a rich alert to that channel (the same real-time event that
already drives web push + email). Nothing about the customer is stored — it is scored in the
moment, the alert is posted, and it is forgotten. The webhook URL (which contains a secret token)
is stored encrypted per tenant.

Routes (auth via require_shop, which also accepts a hosted tenant's session cookie):
  GET  /v1/slack/status                 — connected? masked webhook
  POST /v1/slack/connect {webhook_url}  — validate, post a hello, store
  POST /v1/slack/test                   — post a sample VIC alert
  POST /v1/slack/disconnect
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, HTTPException

from halia import config, notify
from halia.api.shopify_auth import require_shop, shop_store

_HOOK_PREFIX = "https://hooks.slack.com/"


def _masked(url: str) -> str:
    """Show enough to recognise the hook, never the secret token."""
    tail = (url or "").rstrip("/").split("/")[-1]
    return "hooks.slack.com/…/" + (tail[-6:] if len(tail) > 6 else "•••")


def build_alert_blocks(alert: dict, base_url: str | None) -> tuple[str, list]:
    """A Halia order alert -> (fallback text, Slack Block Kit blocks). Shared by the live
    dispatch (realtime._dispatch) and the /test route so they always look identical."""
    grade = str(alert.get("grade") or "").strip()
    name = str(alert.get("name") or "A client").strip()
    signals = " · ".join(alert.get("signals") or []) or "high-value signals"
    fallback = f"Hidden VIC just ordered · {name}" + (f" ({grade})" if grade else "")

    fields = []
    if alert.get("spend") is not None:
        try:
            fields.append({"type": "mrkdwn", "text": f"*Spend*\n£{int(alert['spend']):,}"})
        except (TypeError, ValueError):
            pass
    if alert.get("order_id"):
        fields.append({"type": "mrkdwn", "text": f"*Order*\n{alert['order_id']}"})

    section = {"type": "section",
               "text": {"type": "mrkdwn", "text": f"*{name}*  ·  Halia grade *{grade or '—'}*\n{signals}"}}
    if fields:
        section["fields"] = fields

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": "Hidden VIC just ordered", "emoji": True}},
        section,
    ]
    url = (base_url or "").rstrip("/") + "/app"
    if url.startswith("http"):
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open in Halia"},
             "url": url, "style": "primary"}]})
    return fallback, blocks


_SAMPLE = {"grade": "A*", "name": "Eleanor Ashworth", "order_id": "#1042", "spend": 180,
           "signals": ["Prime postcode (W1)", "Family-office email", "Premium card"]}


def register(app) -> None:

    @app.get("/v1/slack/status")
    def slack_status(shop: str = Depends(require_shop)) -> dict:
        conn = shop_store().get_slack(shop)
        return {"connected": bool(conn), "webhook": _masked(conn["webhook_url"]) if conn else ""}

    @app.post("/v1/slack/connect")
    def slack_connect(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        url = str((payload or {}).get("webhook_url", "")).strip()
        if not url.startswith(_HOOK_PREFIX):
            raise HTTPException(400, "That doesn't look like a Slack Incoming Webhook URL — it should "
                                     "start with https://hooks.slack.com/.")
        _, blocks = build_alert_blocks(
            {"grade": "A*", "name": "Halia is connected",
             "signals": ["You'll get an alert like this the moment a hidden VIC orders"]},
            config.HALIA_APP_URL)
        if not notify.send_slack(url, "Halia is connected to Slack ✓", blocks):
            raise HTTPException(400, "We couldn't post to that Slack webhook. Check the URL and try again.")
        shop_store().save_slack(shop, url)
        return {"ok": True, "webhook": _masked(url)}

    @app.post("/v1/slack/test")
    def slack_test(shop: str = Depends(require_shop)) -> dict:
        conn = shop_store().get_slack(shop)
        if not conn:
            raise HTTPException(400, "Connect Slack first.")
        text, blocks = build_alert_blocks(_SAMPLE, config.HALIA_APP_URL)
        return {"ok": notify.send_slack(conn["webhook_url"], text, blocks)}

    @app.post("/v1/slack/disconnect")
    def slack_disconnect(shop: str = Depends(require_shop)) -> dict:
        shop_store().delete_slack(shop)
        return {"ok": True}
