"""The lifecycle email engine: enroll contacts, then send due steps on a schedule.

Halia runs its own journeys and uses Brevo only as the sender (via halia.notify). This keeps the
whole thing in code and testable, with no Brevo dashboard workflows to maintain.

  - demo   : a lead who asked for a demo. Instant intro, then a 3-email drip at +4 day gaps.
  - client : a new tenant. Welcome, how-to, then the good-call/bad-call habit.
  - weekly : a recurring nudge for active clients that rotates through check-your-VICs,
             the feedback habit, and refresh-your-templates, every 7 days.

The scheduler (`run_due`) is meant to be poked periodically by a cron (see /internal/cron/run).
Every send carries a signed one-click Unsubscribe; suppressed emails are skipped everywhere.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse as _up
from datetime import datetime, timedelta, timezone

from halia import emails
from halia.api.tenant_auth import _secret

# (template_key, days_after_previous_step)
_SEQUENCES: dict[str, list[tuple[str, int]]] = {
    "demo": [("demo_intro", 0), ("demo_hidden", 4), ("demo_how", 4), ("demo_ready", 4)],
    "client": [("client_welcome", 0), ("client_action", 3), ("client_feedback", 4)],
}
_WEEKLY = ["weekly_vics", "weekly_feedback", "weekly_refresh"]
_WEEKLY_EVERY_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ── unsubscribe token (HMAC over the shared app secret) ──────────────────────────
def _sig(email: str) -> str:
    return hmac.new(_secret(), f"unsub|{email.strip().lower()}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def unsub_url(email: str) -> str:
    q = _up.urlencode({"e": email.strip().lower(), "s": _sig(email)})
    return f"{emails.base_url()}/email/unsubscribe?{q}"


def unsub_valid(email: str, sig: str) -> bool:
    return hmac.compare_digest(sig or "", _sig(email))


# ── enrollment ───────────────────────────────────────────────────────────────────
def _store():
    from halia.api.shopify_auth import shop_store
    return shop_store()


def enroll(email: str, journey: str, data: dict | None = None,
           first_delay_days: int | None = None, store=None) -> bool:
    """Enroll ``email`` on ``journey``. No-op if already enrolled or suppressed. Returns started?"""
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    st = store or _store()
    if st.is_suppressed(email):
        return False
    if journey in _SEQUENCES:
        delay = _SEQUENCES[journey][0][1] if first_delay_days is None else first_delay_days
    else:  # weekly / recurring
        delay = _WEEKLY_EVERY_DAYS if first_delay_days is None else first_delay_days
    next_at = _iso(_now() + timedelta(days=delay))
    st.enroll_journey(email, journey, next_at, json.dumps(data or {}))
    return True


def enroll_demo(email: str, store=None) -> bool:
    return enroll(email, "demo", store=store)


def enroll_client(email: str, first: str = "", shop: str = "", store=None) -> None:
    """A new client: the welcome series now, plus the recurring weekly nudge starting in a week."""
    data = {"first": first, "shop": shop}
    enroll(email, "client", data, store=store)
    enroll(email, "weekly", data, store=store)  # first weekly fires in _WEEKLY_EVERY_DAYS


# ── scheduler ────────────────────────────────────────────────────────────────────
def _send_one(email: str, template_key: str, data: dict, send) -> bool:
    subject, html, text = emails.render(template_key, data, unsub_url(email))
    try:
        return bool(send(email, subject, html, text=text))
    except Exception:  # noqa: BLE001 - one bad send must not stall the batch
        return False


def _weekly_enrich(data: dict, store) -> dict:
    """Best-effort: fold last-fortnight hidden-VIC count into the weekly copy."""
    shop = data.get("shop")
    if not shop:
        return data
    try:
        from halia.store import recent_weeks
        by_shop = store.metric_by_shop(recent_weeks(2))
        hidden = (by_shop.get(shop, {}) or {}).get("hidden_vics", 0)
        if hidden:
            return {**data, "hidden": int(hidden)}
    except Exception:  # noqa: BLE001
        pass
    return data


def run_due(now: datetime | None = None, send=None, store=None) -> dict:
    """Send every due step, then advance/finish/reschedule. Returns {sent, processed}."""
    now = now or _now()
    st = store or _store()
    if send is None:
        import halia.notify as notify
        send = notify.send_email

    rows = st.due_journeys(_iso(now))
    sent = 0
    for r in rows:
        email, journey, step = r["email"], r["journey"], int(r["step"] or 0)
        data = json.loads(r.get("data") or "{}")

        if journey in _SEQUENCES:
            seq = _SEQUENCES[journey]
            if step >= len(seq):
                st.finish_journey(email, journey)
                continue
            if _send_one(email, seq[step][0], data, send):
                sent += 1
            nxt = step + 1
            if nxt < len(seq):
                st.advance_journey(email, journey, nxt, _iso(now + timedelta(days=seq[nxt][1])))
            else:
                st.finish_journey(email, journey)

        elif journey == "weekly":
            tkey = _WEEKLY[step % len(_WEEKLY)]
            if _send_one(email, tkey, _weekly_enrich(data, st), send):
                sent += 1
            st.advance_journey(email, journey, step + 1,
                               _iso(now + timedelta(days=_WEEKLY_EVERY_DAYS)))
        else:  # unknown journey — close it so it stops being due
            st.finish_journey(email, journey)

    return {"sent": sent, "processed": len(rows)}
