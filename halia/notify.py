"""Outbound alert delivery: email (SMTP) and Web Push. Both best-effort and optional.

When a high-grade order arrives, Halia scores the one customer in memory and dispatches an
alert, then forgets it. Nothing about the customer is stored to send these. If SMTP or VAPID
is not configured, that channel is simply a no-op, so the webhook never fails because of it.

Env:
  Email (Brevo):  HALIA_BREVO_API_KEY, HALIA_EMAIL_FROM (a verified sender), HALIA_EMAIL_FROM_NAME
  Email (SMTP):   HALIA_SMTP_HOST, HALIA_SMTP_PORT (587), HALIA_SMTP_USER, HALIA_SMTP_PASS, HALIA_SMTP_FROM
  Push:   HALIA_VAPID_PRIVATE (PEM), HALIA_VAPID_PUBLIC (base64url applicationServerKey).
          If unset, a keypair is generated once and cached in output/vapid.json.

Email uses Brevo's transactional API when HALIA_BREVO_API_KEY is set, else SMTP.
"""
from __future__ import annotations

import base64
import json
import os
import smtplib
import ssl
import traceback
from email.message import EmailMessage
from pathlib import Path

from config import OUTPUT_DIR

VAPID_SUBJECT = os.environ.get("HALIA_VAPID_SUBJECT", "mailto:alerts@haliascore.com")


def _env(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def _record(shop: str | None, metric: str, n: int = 1) -> None:
    """Best-effort console-dashboard counter for a successful send. Lazy-imported so this
    low-level module stays decoupled, and never raised so a metrics hiccup can't break a send."""
    try:
        from halia.api.data import record_activity
        record_activity(shop or "_system", metric, n)
    except Exception:  # pragma: no cover - counters are non-critical
        pass


# ── email ────────────────────────────────────────────────────────────────────────
def email_configured() -> bool:
    return bool(_env("HALIA_BREVO_API_KEY") or _env("HALIA_SMTP_HOST"))


def _send_brevo(to: str, subject: str, html: str, reply_to: str | None = None) -> bool:
    import requests

    sender = _env("HALIA_EMAIL_FROM", "HALIA_SMTP_FROM") or "alerts@haliascore.com"
    body = {"sender": {"email": sender, "name": _env("HALIA_EMAIL_FROM_NAME") or "Halia"},
            "to": [{"email": to}], "subject": subject, "htmlContent": html}
    if reply_to:
        body["replyTo"] = {"email": reply_to}
    try:
        resp = requests.post("https://api.brevo.com/v3/smtp/email", json=body,
                             headers={"api-key": _env("HALIA_BREVO_API_KEY"),
                                      "accept": "application/json", "content-type": "application/json"},
                             timeout=15)
        return 200 <= resp.status_code < 300
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return False


def send_email(to: str, subject: str, html: str, text: str | None = None,
               shop: str | None = None, reply_to: str | None = None) -> bool:
    """Send one email (Brevo API, else SMTP). On success, count it for the console dashboard,
    bucketed under ``shop`` (or '_system' for console/lifecycle mail with no shop context).
    ``reply_to`` sets the Reply-To header (used so a catalogue enquiry replies to the shopper)."""
    if not to:
        return False
    ok = _send_email_raw(to, subject, html, text, reply_to)
    if ok:
        _record(shop, "email")
    return ok


def _send_email_raw(to: str, subject: str, html: str, text: str | None,
                    reply_to: str | None = None) -> bool:
    if _env("HALIA_BREVO_API_KEY"):
        return _send_brevo(to, subject, html, reply_to)
    host = _env("HALIA_SMTP_HOST")
    if not host:
        return False
    port = int(_env("HALIA_SMTP_PORT") or 587)
    user, pw = _env("HALIA_SMTP_USER"), _env("HALIA_SMTP_PASS")
    sender = _env("HALIA_SMTP_FROM") or user or "alerts@haliascore.com"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text or "Open Halia to see the details.")
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls(context=ssl.create_default_context())
            if user and pw:
                s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 — never let a mail failure break the webhook
        traceback.print_exc()
        return False


# ── Slack (per-shop Incoming Webhook) ────────────────────────────────────────────────
def send_slack(webhook_url: str, text: str, blocks: list | None = None,
               shop: str | None = None) -> bool:
    """Post a message to a Slack Incoming Webhook. Best-effort; never raises.

    `text` is the notification/fallback string; `blocks` is optional Block Kit for the rich
    in-channel card. Returns True on a 2xx from Slack."""
    if not webhook_url:
        return False
    import requests

    body: dict = {"text": text}
    if blocks:
        body["blocks"] = blocks
    try:
        resp = requests.post(webhook_url, json=body, timeout=10)
        ok = 200 <= resp.status_code < 300
    except Exception:  # noqa: BLE001 — a Slack failure must never break the webhook
        traceback.print_exc()
        return False
    if ok:
        _record(shop, "notify_slack")
    return ok


# ── web push ───────────────────────────────────────────────────────────────────────
_VAPID: dict | bool | None = None


def vapid_keys() -> dict | None:
    """Return {'private': PEM, 'public': base64url}, generating + caching once if needed."""
    global _VAPID
    if _VAPID is not None:
        return _VAPID or None
    priv, pub = _env("HALIA_VAPID_PRIVATE"), _env("HALIA_VAPID_PUBLIC")
    if priv and pub:
        _VAPID = {"private": priv.replace("\\n", "\n"), "public": pub}
        return _VAPID
    cache = OUTPUT_DIR / "vapid.json"
    try:
        if cache.exists():
            _VAPID = json.loads(cache.read_text())
            return _VAPID
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        pk = ec.generate_private_key(ec.SECP256R1())
        priv_pem = pk.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
        raw_pub = pk.public_key().public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
        app_key = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
        _VAPID = {"private": priv_pem, "public": app_key}
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(_VAPID))
        return _VAPID
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        _VAPID = False
        return None


def vapid_public() -> str | None:
    v = vapid_keys()
    return v["public"] if v else None


def send_web_push(subscriptions: list[dict], payload: dict, shop: str | None = None) -> int:
    """Push a payload to each subscription. Returns how many succeeded. Best-effort."""
    v = vapid_keys()
    if not v or not subscriptions:
        return 0
    try:
        from pywebpush import webpush
    except Exception:  # noqa: BLE001 — library not installed
        return 0
    sent = 0
    for sub in subscriptions:
        try:
            webpush(subscription_info=sub, data=json.dumps(payload),
                    vapid_private_key=v["private"], vapid_claims={"sub": VAPID_SUBJECT})
            sent += 1
        except Exception:  # noqa: BLE001 — dead/expired subscription; ignore
            pass
    if sent:
        _record(shop, "notify_push", sent)
    return sent
