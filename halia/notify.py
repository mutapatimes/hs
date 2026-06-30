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

VAPID_SUBJECT = os.environ.get("HALIA_VAPID_SUBJECT", "mailto:alerts@halia.app")


def _env(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


# ── email ────────────────────────────────────────────────────────────────────────
def email_configured() -> bool:
    return bool(_env("HALIA_BREVO_API_KEY") or _env("HALIA_SMTP_HOST"))


def _send_brevo(to: str, subject: str, html: str) -> bool:
    import requests

    sender = _env("HALIA_EMAIL_FROM", "HALIA_SMTP_FROM") or "alerts@halia.app"
    body = {"sender": {"email": sender, "name": _env("HALIA_EMAIL_FROM_NAME") or "Halia"},
            "to": [{"email": to}], "subject": subject, "htmlContent": html}
    try:
        resp = requests.post("https://api.brevo.com/v3/smtp/email", json=body,
                             headers={"api-key": _env("HALIA_BREVO_API_KEY"),
                                      "accept": "application/json", "content-type": "application/json"},
                             timeout=15)
        return 200 <= resp.status_code < 300
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return False


def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    if not to:
        return False
    if _env("HALIA_BREVO_API_KEY"):
        return _send_brevo(to, subject, html)
    host = _env("HALIA_SMTP_HOST")
    if not host:
        return False
    port = int(_env("HALIA_SMTP_PORT") or 587)
    user, pw = _env("HALIA_SMTP_USER"), _env("HALIA_SMTP_PASS")
    sender = _env("HALIA_SMTP_FROM") or user or "alerts@halia.app"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
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


def send_web_push(subscriptions: list[dict], payload: dict) -> int:
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
    return sent
