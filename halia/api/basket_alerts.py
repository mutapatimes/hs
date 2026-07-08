"""High-value open-basket alerts: a Slack/email nudge when a graded VIC has an unpaid checkout
above a threshold, so the team can recover it while it's warm.

These are not real-time: an "abandoned" basket is defined by inactivity (Shopify abandoned
checkouts / BigCommerce incomplete orders), so the check runs during each sync, right after the
carts are attached to the dashboard payload.

De-dup is RAM-only, to honour zero retention: a per-shop set of already-alerted basket ids (the
checkout / order id, an external system reference, not customer PII). Each run we alert the ids that
are newly high-value and replace the set with the current high-value set, so a converted or
abandoned basket is forgotten and never re-alerts on repeat. Nothing is written to disk; on a
process restart the set is empty, so recent high-value baskets may alert once more — the accepted
trade-off for keeping nothing persisted. A recency gate bounds that to baskets started this week.
"""
from __future__ import annotations

import html as _html
from datetime import date, datetime

from halia import config, notify
from halia.api.shopify_auth import shop_store

# shop -> set of basket ids already alerted (RAM only; never persisted)
_seen: dict[str, set] = {}
_RECENT_DAYS = 7
_MAX_PER_RUN = 10


def _basket_id(client: dict) -> str:
    cart = client.get("cart") or {}
    return str(cart.get("id") or f'{client.get("cid")}:{cart.get("value")}')


def _is_recent(started: str, today: date | None = None) -> bool:
    if not started:
        return True                        # unknown age -> don't exclude
    try:
        d = datetime.strptime(str(started)[:10], "%Y-%m-%d").date()
    except ValueError:
        return True
    return ((today or date.today()) - d).days <= _RECENT_DAYS


def _age(started: str, today: date | None = None) -> str:
    try:
        d = datetime.strptime(str(started)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "recently"
    days = ((today or date.today()) - d).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def _slack_blocks(name, grade, value, count, started, base_url):
    items = f"{count} item{'s' if count != 1 else ''}"
    fallback = f"Open basket · {name} — £{value:,}"
    section = {"type": "section", "text": {"type": "mrkdwn",
               "text": f"*{name}*  ·  Halia grade *{grade or '—'}*\n"
                       f"£{value:,} in an unpaid checkout · {items} · started {_age(started)}"}}
    blocks = [{"type": "header",
               "text": {"type": "plain_text", "text": "High-value open basket", "emoji": True}},
              section]
    url = (base_url or "").rstrip("/") + "/app"
    if url.startswith("http"):
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open in Halia"},
             "url": url, "style": "primary"}]})
    return fallback, blocks


def _email_html(name, grade, value, count, started):
    items = f"{count} item{'s' if count != 1 else ''}"
    return (
        "<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;"
        "margin:0 auto;color:#1c1b18\">"
        f"<p style=\"font:600 12px sans-serif;letter-spacing:.12em;text-transform:uppercase;"
        f"color:#1f564a;margin:0 0 8px\">High-value open basket</p>"
        f"<h2 style=\"font:400 26px Georgia,serif;margin:0 0 6px\">{_html.escape(name)}</h2>"
        f"<p style=\"color:#6b675e;margin:0 0 18px\">Halia grade {_html.escape(grade or '—')} · "
        f"£{value:,} in an unpaid checkout · {items} · started {_html.escape(_age(started))}. "
        "A discreet, timely note often recovers it.</p>"
        "<a href=\"/app\" style=\"display:inline-block;background:#1f564a;color:#fff;"
        "text-decoration:none;font:600 14px sans-serif;padding:11px 20px;border-radius:8px\">"
        "Open in Halia</a>"
        "<p style=\"color:#9a958a;font-size:12px;margin:22px 0 0\">You are receiving this because "
        "basket alerts are on in Halia. Turn them off any time in Settings.</p></div>")


def _send(shop, client, slack, emails):
    cart = client["cart"]
    name = str(client.get("name") or "A client")
    grade = str(client.get("grade") or "")
    value = int(cart.get("value") or 0)
    count = int(cart.get("count") or 0)
    started = cart.get("started")
    if slack:
        text, blocks = _slack_blocks(name, grade, value, count, started, config.HALIA_APP_URL)
        notify.send_slack(slack["webhook_url"], text, blocks, shop=shop)
    if emails and notify.email_configured():
        subject = f"Open basket · {name} — £{value:,}"
        html = _email_html(name, grade, value, count, started)
        for email in emails:
            notify.send_email(email, subject, html, shop=shop)


def dispatch_basket_alerts(shop: str, clients: list | None, s: dict | None = None,
                           today: date | None = None) -> int:
    """Alert on newly-seen high-value open baskets. Best-effort; returns the number sent."""
    from halia.api.settings import settings_for
    s = s or settings_for(shop)
    if not s.get("basket_alerts", True):
        return 0
    grades = set(s.get("notify_grades") or ["A*", "A"])
    try:
        min_value = float(s.get("basket_alert_min") or config.BASKET_ALERT_MIN)
    except (TypeError, ValueError):
        min_value = config.BASKET_ALERT_MIN
    store = shop_store()
    slack = store.get_slack(shop)
    emails = s.get("notify_emails") or ([s["notify_email"]] if s.get("notify_email") else [])
    if not (slack or (emails and notify.email_configured())):
        return 0                                   # no channel connected -> nothing to do

    current_ids: set = set()
    fresh: list = []
    already = _seen.get(shop, set())
    for c in clients or []:
        cart = c.get("cart")
        if not cart or c.get("grade") not in grades:
            continue
        try:
            value = int(cart.get("value") or 0)
        except (TypeError, ValueError):
            value = 0
        if value < min_value or not _is_recent(cart.get("started"), today):
            continue
        bid = _basket_id(c)
        current_ids.add(bid)
        if bid not in already:
            fresh.append(c)

    sent = 0
    for c in fresh[:_MAX_PER_RUN]:
        _send(shop, c, slack, emails)
        sent += 1
    _seen[shop] = current_ids                       # forget converted baskets; suppress repeats
    return sent
