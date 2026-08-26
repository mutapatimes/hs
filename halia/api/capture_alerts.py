"""Team alert when a high-grade client is captured unattended.

The handover path already shows the associate the grade in person; this covers the moments
nobody is watching: the QR card by the till, a self-capture at an event. A qualifying new
capture pings the same channels the VIP order alerts use — web push, email, Slack — so
someone can say hello while the client is still nearby. Best-effort by design: a notify
failure never breaks the capture. Sibling of basket_alerts.py.
"""
from __future__ import annotations

import html as _html

from halia import config, notify
from halia.api.shopify_auth import shop_store

_CHANNEL_LINE = {
    "qr": "left their details at the boutique",
    "vcard": "was added from a shared contact",
}


def _who(body: dict) -> str:
    name = " ".join(p for p in (str(body.get("first_name") or "").strip(),
                                str(body.get("last_name") or "").strip()) if p)
    return name or "A new client"


def _slack_blocks(name, grade, line, signals, base_url):
    fallback = f"New {grade} client · {name}"
    detail = " · ".join(signals[:3]) if signals else "Signals are in the dashboard"
    blocks = [{"type": "header",
               "text": {"type": "plain_text", "text": f"New {grade} client", "emoji": True}},
              {"type": "section", "text": {"type": "mrkdwn",
               "text": f"*{name}* {line}.\n{detail}"}}]
    url = (base_url or "").rstrip("/") + "/app"
    if url.startswith("http"):
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open in Halia"},
             "url": url, "style": "primary"}]})
    return fallback, blocks


def _email_html(name, grade, line, signals):
    detail = " · ".join(_html.escape(x) for x in signals[:3]) if signals else \
        "The signals are in the dashboard."
    return (
        "<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;"
        "margin:0 auto;color:#1c1b18\">"
        f"<p style=\"font:600 12px sans-serif;letter-spacing:.12em;text-transform:uppercase;"
        f"color:#1f564a;margin:0 0 8px\">New {_html.escape(grade)} client</p>"
        f"<h2 style=\"font:400 26px Georgia,serif;margin:0 0 6px\">{_html.escape(name)}</h2>"
        f"<p style=\"color:#6b675e;margin:0 0 18px\">{_html.escape(name)} {_html.escape(line)}. "
        f"{detail}. A welcome within the hour lands differently.</p>"
        "<a href=\"/app\" style=\"display:inline-block;background:#1f564a;color:#fff;"
        "text-decoration:none;font:600 14px sans-serif;padding:11px 20px;border-radius:8px\">"
        "Open in Halia</a>"
        "<p style=\"color:#9a958a;font-size:12px;margin:22px 0 0\">You are receiving this because "
        "capture alerts are on in Halia. Turn them off any time in Settings.</p></div>")


def dispatch_capture_alert(shop: str, result: dict, body: dict, channel: str,
                           s: dict | None = None) -> bool:
    """Alert on a NEW, qualifying, unattended capture. Returns whether anything was sent."""
    try:
        if not result.get("created"):
            return False                      # a repeat submit, already in the book
        grade = str(result.get("grade") or "")
        from halia.api.settings import settings_for
        s = s or settings_for(shop)
        if not s.get("capture_alerts", True):
            return False
        if grade not in set(s.get("notify_grades") or ["A*", "A"]):
            return False

        store = shop_store()
        slack = store.get_slack(shop)
        emails = s.get("notify_emails") or ([s["notify_email"]] if s.get("notify_email") else [])
        subs = store.push_subs(shop)
        if not (slack or subs or (emails and notify.email_configured())):
            return False

        name = _who(body)
        line = _CHANNEL_LINE.get(channel, "just joined")
        signals = [str(x) for x in (result.get("signals") or [])]

        if subs:
            notify.send_web_push(subs, {
                "title": f"New {grade} client · {name}",
                "body": f"{name.split(' ')[0]} {line}. " + (" · ".join(signals[:2]) or ""),
                "tag": f"halia-capture-{result.get('customer_id') or name}",
                "url": "/app"}, shop=shop)
        if slack:
            text, blocks = _slack_blocks(name, grade, line, signals, config.HALIA_APP_URL)
            notify.send_slack(slack["webhook_url"], text, blocks, shop=shop)
        if emails and notify.email_configured():
            subject = f"New {grade} client · {name}"
            html_body = _email_html(name, grade, line, signals)
            for email in emails:
                notify.send_email(email, subject, html_body, shop=shop)
        return True
    except Exception:  # noqa: BLE001 — alerts must never break a capture
        return False
