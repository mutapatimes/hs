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
    # A teammate given a seat: sign in, first moves, capture at the counter, the weekly habit.
    "associate": [("assoc_welcome", 0), ("assoc_first_moves", 2), ("assoc_capture", 3),
                  ("assoc_habits", 4)],
    # The free scan: the book is scored and counted, names are on a plan. Ends on subscription.
    "freescan": [("free_scored", 0), ("free_reveal", 3), ("free_moved", 7), ("free_last", 11)],
    # After a cancellation: a fresh count at 30 and 90 days. Ends if they come back.
    "winback": [("winback_30", 30), ("winback_90", 60)],
}
DORMANT, CANCEL_ENDING, SEASON, BIRTHDAYS = "dormant", "cancel_ending", "season", "birthdays"
_DORMANT_DAYS = 14
_SEASON_LEAD_DAYS = 14
_WEEKLY = ["weekly_vics", "weekly_feedback", "weekly_refresh", "weekly_team"]
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


def enroll_associate(email: str, first: str = "", shop: str = "", store_name: str = "",
                     connect: str = "", store=None) -> bool:
    """Start the associate onboarding for a newly issued seat. The join link rides the first
    email so signing in is one tap from the inbox."""
    return enroll(email, "associate", {"first": first, "shop": shop, "store_name": store_name,
                                       "connect": connect}, store=store)


def enroll_client(email: str, first: str = "", shop: str = "", store=None) -> None:
    """A new client: the welcome series now, plus the recurring weekly nudge starting in a week."""
    data = {"first": first, "shop": shop}
    enroll(email, "client", data, store=store)
    enroll(email, "weekly", data, store=store)  # first weekly fires in _WEEKLY_EVERY_DAYS


# ── the end-of-month recap, one per seat holder ──────────────────────────────────
MONTHLY = "monthly"
_MONTHLY_HOUR = 6   # UTC, on the 1st: the previous calendar month is complete


def _first_of_next_month(now: datetime) -> datetime:
    y, m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return now.replace(year=y, month=m, day=1, hour=_MONTHLY_HOUR, minute=0, second=0, microsecond=0)


def _previous_month(now: datetime) -> tuple[str, int, str]:
    """('YYYY-MM', days in it, 'August') for the month before ``now``."""
    import calendar
    y, m = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return f"{y:04d}-{m:02d}", calendar.monthrange(y, m)[1], calendar.month_name[m]


def enroll_monthly(email: str, seat_id: str, shop: str, store_name: str = "", first: str = "",
                   store=None) -> bool:
    """A seat holder gets their own numbers at the end of every calendar month."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    st = store or _store()
    if st.is_suppressed(email):
        return False
    st.enroll_journey(email, MONTHLY, _iso(_first_of_next_month(_now())),
                      json.dumps({"seat_id": seat_id, "shop": shop, "store_name": store_name,
                                  "first": first}))
    return True


def ensure_monthly_enrolments(store=None) -> int:
    """Every live seat with an email is on the monthly recap (idempotent; new seats join at
    creation, this catches the ones that predate it). Returns how many were added."""
    st = store or _store()
    added = 0
    for t in st.all_tenants():
        t = dict(t)
        for seat in st.list_seats(t["shop"]):
            email = (seat.get("email") or "").strip().lower()
            if "@" not in email or st.is_suppressed(email):
                continue
            before = st.journey_exists(email, MONTHLY) if hasattr(st, "journey_exists") else False
            if enroll_monthly(email, seat["id"], t["shop"], t.get("label") or t["shop"],
                              (seat.get("name") or "").split(" ")[0], store=st) and not before:
                added += 1
    return added


def _seat_month(shop: str, seat_id: str, now: datetime, store=None) -> dict | None:
    """One associate's numbers for the month just ended, plus where they stand on the team.
    None when the seat is gone, so the recap stops."""
    st = store or _store()
    month, days, month_name = _previous_month(now)
    seat = next((x for x in st.list_seats(shop) if x["id"] == seat_id), None)
    if not seat:
        return None
    try:
        from halia.api.reports import build_report
        rep = build_report(shop, days)
    except Exception:  # noqa: BLE001
        rep = {"available": False, "seats": [], "totals": {}}
    rows = rep.get("seats") or []
    mine = next((r for r in rows if r.get("id") == seat_id), None) or {}
    ranked = sorted(rows, key=lambda r: (-(r.get("revenue") or 0), -(r.get("contacts") or 0)))
    rank = next((i + 1 for i, r in enumerate(ranked) if r.get("id") == seat_id), None)
    tools = st.seat_month_metrics(seat_id, month)
    return {"month": month, "month_name": month_name, "days": days,
            "contacts": int(mine.get("contacts") or 0), "clients": int(mine.get("clients") or 0),
            "captures": int(mine.get("captures") or 0), "captured_top": int(mine.get("captured_top") or 0),
            "conversions": int(mine.get("conversions") or 0), "revenue": int(mine.get("revenue") or 0),
            "top_share": float(mine.get("topShare") or 0.0),
            "drafts": int(tools.get("drafts") or 0), "links": int(tools.get("links") or 0),
            "remembered": int(tools.get("remembered") or 0),
            "rank": rank, "team_size": len([r for r in rows if not r.get("former")]),
            "team": rep.get("totals") or {}}


# ── merchant journeys (the owner of a store) ─────────────────────────────────────
def _owner_email(shop: str) -> str:
    """The store's own contact: the account email, else the first alert address."""
    try:
        from halia.api.settings import settings_for
        st = settings_for(shop)
        for e in [st.get("account_email") or ""] + list(st.get("notify_emails") or []):
            if "@" in (e or ""):
                return e.strip().lower()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _owner_data(shop: str, store=None) -> dict:
    st = store or _store()
    tenant = dict(st.get_tenant(shop) or {})
    label = tenant.get("label") or shop
    return {"shop": shop, "store_name": label, "first": label}


def _paid(shop: str) -> bool:
    try:
        from halia.api import billing
        return bool(billing.is_paid(shop))
    except Exception:  # noqa: BLE001
        return True


def _book_numbers(shop: str) -> dict | None:
    """Live counts from the warm book, for a merchant email. None when the book is not in
    memory (the cron never triggers a fetch just to write an email)."""
    try:
        from halia.cache import cache
        entry = cache.get(shop)
    except Exception:  # noqa: BLE001
        entry = None
    if not entry:
        return None
    payload = entry.get("payload") or {}
    rows = payload.get("data") or []
    quiet = sum(1 for r in rows if r.get("band") == "lapsed" and r.get("known"))
    baskets = sum(1 for r in rows if r.get("cart"))
    basket_value = sum(int(((r.get("cart") or {}).get("value")) or 0) for r in rows if r.get("cart"))
    top = sum(1 for r in rows if r.get("grade") in ("A*", "A") and not r.get("known"))
    return {"count": payload.get("stat_count") or str(len(rows)), "latent": payload.get("stat_latent") or "",
            "top": top, "quiet": quiet, "baskets": baskets, "basket_value": basket_value,
            "scored": payload.get("stat_scored") or ""}


def enroll_freescan(shop: str, store=None) -> bool:
    """A store on the free scan: what is in their book, then what a plan reveals."""
    email = _owner_email(shop)
    if not email or _paid(shop):
        return False
    return enroll(email, "freescan", _owner_data(shop, store), store=store)


def enroll_winback(shop: str, store=None) -> bool:
    email = _owner_email(shop)
    if not email:
        return False
    st = store or _store()
    st.delete_journey(email, CANCEL_ENDING)
    st.delete_journey(email, "winback")           # a second cancellation restarts the clock
    return enroll(email, "winback", _owner_data(shop, store), store=store)


def enroll_cancel_ending(shop: str, period_end_ts: int | float | None, store=None) -> bool:
    """Five days before a cancelled plan ends: what goes back behind the mask."""
    email = _owner_email(shop)
    if not email or not period_end_ts:
        return False
    st = store or _store()
    st.delete_journey(email, CANCEL_ENDING)
    if st.is_suppressed(email):
        return False
    end = datetime.fromtimestamp(float(period_end_ts), tz=timezone.utc)
    due = max(end - timedelta(days=5), _now())
    st.enroll_journey(email, CANCEL_ENDING, _iso(due),
                      json.dumps({**_owner_data(shop, store), "ends": end.date().isoformat()}))
    return True


def cancel_cancel_ending(shop: str, store=None) -> None:
    email = _owner_email(shop)
    if email:
        (store or _store()).delete_journey(email, CANCEL_ENDING)


def on_subscribed(shop: str, store=None) -> None:
    """A plan is live: the free-scan and win-back sequences stop, the client series starts."""
    email = _owner_email(shop)
    if not email:
        return
    st = store or _store()
    for j in ("freescan", "winback", CANCEL_ENDING):
        st.delete_journey(email, j)
    d = _owner_data(shop, st)
    enroll(email, "client", d, store=st)
    enroll(email, "weekly", d, store=st)


def enroll_dormant(shop: str, store=None) -> bool:
    email = _owner_email(shop)
    if not email:
        return False
    st = store or _store()
    if st.journey_exists(email, DORMANT) or st.is_suppressed(email):
        return False
    st.enroll_journey(email, DORMANT, _iso(_now()), json.dumps(_owner_data(shop, st)))
    return True


def _opened_recently(shop: str, now: datetime, store) -> bool:
    last = store.tenant_last_open(shop)
    if not last:
        return False
    try:
        return datetime.fromisoformat(last.replace("Z", "+00:00")) >= now - timedelta(days=_DORMANT_DAYS)
    except ValueError:
        return False


# ── seat journeys beyond the monthly recap: the season calendar and birthdays ────
def _next_season_due(now: datetime):
    """(due datetime, preset) for the next season moment whose lead window is ahead of now."""
    from halia.api.campaigns import presets_for
    from datetime import date as _date
    best = None
    for yr_shift in (0, 1):
        probe = _date(now.year + yr_shift, now.month, min(now.day, 28))
        for pr in presets_for(probe)["presets"]:
            starts = datetime.fromisoformat(pr["starts"]).replace(tzinfo=timezone.utc, hour=_MONTHLY_HOUR)
            due = starts - timedelta(days=_SEASON_LEAD_DAYS)
            if due > now and (best is None or due < best[0]):
                best = (due, pr)
    return best


def enroll_season(email: str, seat_id: str, shop: str, store_name: str = "", first: str = "",
                  store=None) -> bool:
    email = (email or "").strip().lower()
    st = store or _store()
    if "@" not in email or st.is_suppressed(email):
        return False
    nxt = _next_season_due(_now())
    if not nxt:
        return False
    st.enroll_journey(email, SEASON, _iso(nxt[0]),
                      json.dumps({"seat_id": seat_id, "shop": shop, "store_name": store_name, "first": first}))
    return True


def enroll_birthdays(email: str, seat_id: str, shop: str, store_name: str = "", first: str = "",
                     store=None) -> bool:
    email = (email or "").strip().lower()
    st = store or _store()
    if "@" not in email or st.is_suppressed(email):
        return False
    now = _now()
    monday = (now + timedelta(days=(7 - now.weekday()) % 7 or 7)).replace(hour=_MONTHLY_HOUR, minute=0, second=0, microsecond=0)
    st.enroll_journey(email, BIRTHDAYS, _iso(monday),
                      json.dumps({"seat_id": seat_id, "shop": shop, "store_name": store_name, "first": first}))
    return True


def _season_payload(shop: str, now: datetime) -> dict | None:
    """The preset whose lead window we are in, with how many clients in the book fit it."""
    from halia.api.campaigns import presets_for
    from datetime import date as _date
    today = now.date()
    cands = []
    for yr_shift in (0, 1):
        probe = _date(now.year + yr_shift, now.month, min(now.day, 28))
        cands += presets_for(probe)["presets"]
    # The moment about two weeks out, not one starting today (a fortnight before 3 November
    # is the preview; on 3 November itself the next one, gifting, is the moment to prepare).
    window = [(abs((_date.fromisoformat(pr["starts"]) - today).days - _SEASON_LEAD_DAYS), pr) for pr in cands
              if 0 <= (_date.fromisoformat(pr["starts"]) - today).days <= _SEASON_LEAD_DAYS + 1]
    if not window:
        return None
    pick = min(window, key=lambda x: x[0])[1]
    n = 0
    try:
        from halia.cache import cache
        entry = cache.get(shop) or {}
        n = sum(1 for r in ((entry.get("payload") or {}).get("data") or []) if r.get("grade") in pick["grades"])
    except Exception:  # noqa: BLE001
        n = 0
    return {**pick, "fit": n}


def _birthdays_payload(shop: str) -> dict | None:
    try:
        from halia.api.birthdays import upcoming
        rows = upcoming(shop, 14)
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    return {"count": len(rows), "rows": [{"name": r.get("name") or "A client", "date": r.get("date"),
                                          "in_days": r.get("in_days"), "grade": r.get("grade") or ""}
                                         for r in rows[:6]]}


def ensure_journeys(store=None) -> dict:
    """Hourly: every live seat with an email is on the monthly recap, the season calendar and the
    birthdays note; unpaid stores with an owner email are on the free-scan series; paid stores
    that have not opened Halia in two weeks are on the gone-quiet nudge. All idempotent."""
    st = store or _store()
    out = {"monthly": 0, "season": 0, "birthdays": 0, "freescan": 0, "dormant": 0}
    now = _now()
    for t in st.all_tenants():
        t = dict(t)
        shop, label = t["shop"], t.get("label") or t["shop"]
        for seat in st.list_seats(shop):
            email = (seat.get("email") or "").strip().lower()
            if "@" not in email or st.is_suppressed(email):
                continue
            first = (seat.get("name") or "").split(" ")[0]
            for key, fn in ((MONTHLY, enroll_monthly), (SEASON, enroll_season), (BIRTHDAYS, enroll_birthdays)):
                if not st.journey_exists(email, key) and fn(email, seat["id"], shop, label, first, store=st):
                    out[key] += 1
        email = _owner_email(shop)
        if not email:
            continue
        if not _paid(shop):
            if not st.journey_exists(email, "freescan") and enroll_freescan(shop, store=st):
                out["freescan"] += 1
        else:
            last = st.tenant_last_open(shop)
            if last and not _opened_recently(shop, now, st) and enroll_dormant(shop, store=st):
                out["dormant"] += 1
    return out


# ── scheduler ────────────────────────────────────────────────────────────────────
def _send_one(email: str, template_key: str, data: dict, send) -> bool:
    subject, html, text = emails.render(template_key, data, unsub_url(email))
    try:
        return bool(send(email, subject, html, text=text))
    except Exception:  # noqa: BLE001 - one bad send must not stall the batch
        return False


def _team_summary(shop: str) -> dict | None:
    """Last week's team numbers for the digest, or None when there is nothing to say."""
    try:
        from halia.api.reports import build_report
        rep = build_report(shop, 7)
    except Exception:  # noqa: BLE001
        return None
    if not rep.get("available") or not rep.get("seats"):
        return None
    if not (rep["totals"].get("contacts") or rep["totals"].get("captures")):
        return None
    top = sorted(rep["seats"], key=lambda r: (-r.get("revenue", 0), -r.get("contacts", 0)))[:3]
    return {"totals": rep["totals"], "top": top}


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
            payload = data
            if journey in ("freescan", "winback"):
                shop = str(data.get("shop") or "")
                if shop and _paid(shop):              # they subscribed: this series is over
                    st.finish_journey(email, journey)
                    continue
                numbers = _book_numbers(shop) if shop else None
                payload = {**data, "book": numbers or {}}
            if _send_one(email, seq[step][0], payload, send):
                sent += 1
            nxt = step + 1
            if nxt < len(seq):
                st.advance_journey(email, journey, nxt, _iso(now + timedelta(days=seq[nxt][1])))
            else:
                st.finish_journey(email, journey)

        elif journey == "weekly":
            tkey = _WEEKLY[step % len(_WEEKLY)]
            payload = _weekly_enrich(data, st)
            if tkey == "weekly_team":
                team = _team_summary(str(data.get("shop") or "")) if data.get("shop") else None
                if team:
                    payload = {**payload, "team": team}
                else:
                    tkey = "weekly_vics"          # nothing to report yet: the usual nudge instead
            if _send_one(email, tkey, payload, send):
                sent += 1
            st.advance_journey(email, journey, step + 1,
                               _iso(now + timedelta(days=_WEEKLY_EVERY_DAYS)))
        elif journey == DORMANT:
            shop = str(data.get("shop") or "")
            if not shop or not _paid(shop) or _opened_recently(shop, now, st):
                st.delete_journey(email, journey)     # back in the app, or gone: re-enrol later if needed
                continue
            numbers = _book_numbers(shop)
            if numbers and _send_one(email, "merchant_quiet", {**data, "book": numbers}, send):
                sent += 1
            st.advance_journey(email, journey, step + 1, _iso(now + timedelta(days=_DORMANT_DAYS)))

        elif journey == CANCEL_ENDING:
            shop = str(data.get("shop") or "")
            still = False
            try:
                from halia.api import billing
                still = bool(billing.billing_state(shop).get("cancel_at_period_end")) if shop else False
            except Exception:  # noqa: BLE001
                still = True
            if still and _send_one(email, "cancel_ending", {**data, "book": _book_numbers(shop) or {}}, send):
                sent += 1
            st.finish_journey(email, journey)

        elif journey == SEASON:
            shop, seat_id = str(data.get("shop") or ""), str(data.get("seat_id") or "")
            alive = seat_id and any(x["id"] == seat_id for x in st.list_seats(shop))
            if not alive or not _paid(shop):
                st.finish_journey(email, journey)
                continue
            moment = _season_payload(shop, now)
            if moment and _send_one(email, "season_moment", {**data, "moment": moment}, send):
                sent += 1
            nxt = _next_season_due(now + timedelta(days=1))
            if nxt:
                st.advance_journey(email, journey, step + 1, _iso(nxt[0]))
            else:
                st.finish_journey(email, journey)

        elif journey == BIRTHDAYS:
            shop, seat_id = str(data.get("shop") or ""), str(data.get("seat_id") or "")
            alive = seat_id and any(x["id"] == seat_id for x in st.list_seats(shop))
            if not alive or not _paid(shop):
                st.finish_journey(email, journey)
                continue
            bd = _birthdays_payload(shop)
            if bd and _send_one(email, "birthdays_week", {**data, "birthdays": bd}, send):
                sent += 1
            st.advance_journey(email, journey, step + 1, _iso(now + timedelta(days=7)))

        elif journey == MONTHLY:
            shop, seat_id = str(data.get("shop") or ""), str(data.get("seat_id") or "")
            month = _seat_month(shop, seat_id, now, store=st) if (shop and seat_id) else None
            if month is None:                     # seat revoked: the recap ends with it
                st.finish_journey(email, journey)
                continue
            if _send_one(email, "monthly_seat", {**data, "recap": month}, send):
                sent += 1
            st.advance_journey(email, journey, step + 1, _iso(_first_of_next_month(now)))

        else:  # unknown journey — close it so it stops being due
            st.finish_journey(email, journey)

    return {"sent": sent, "processed": len(rows)}
