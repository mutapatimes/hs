"""Appointments, kept where the store already lives.

A booking is written to the client's own record in the merchant's store (the halia.pipeline
field, beside the contact log), and handed to the associate's existing calendar through a
Google Calendar link, an Outlook link, or an .ics file (Apple and everything else). Halia
stores nothing and introduces no booking tool of its own.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote, urlencode

from fastapi import Body, Depends, HTTPException, Query, Request

from fastapi.responses import HTMLResponse, Response

from halia import config
from halia.api.shopify_auth import require_shop, shop_store
from halia.api.tenant_auth import _secret

DEFAULT_MINUTES = 45
KEEP_DAYS = 90            # past appointments older than this fall off the record


def _parse_when(raw: Any) -> datetime:
    s = str(raw or "").strip()
    if not s:
        raise HTTPException(422, "when is required (YYYY-MM-DDTHH:MM)")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "when must be a date and time, YYYY-MM-DDTHH:MM")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _label(when: datetime, minutes: int) -> str:
    return when.strftime("%a %d %b, %H:%M") + f" ({minutes} min)"


def invite_token(appt: dict, store_name: str) -> str:
    """A signed, self-contained invite for the client: when, how long, where, the store. No name
    and no address travel in it, so a forwarded link tells a stranger nothing about the client;
    the two people are named only on the associate's own copy of the entry. Nothing is stored and
    the signature stops tampering."""
    # The appointment's own id and revision travel too. Neither says anything about the client,
    # and without them a reschedule hands the client a SECOND entry instead of moving the one they
    # hold: the UID was derived from the token, and the token changes whenever the time does.
    raw = json.dumps({"w": appt["when"], "m": int(appt.get("minutes") or DEFAULT_MINUTES),
                      "p": appt.get("place") or "", "s": store_name or "",
                      "i": appt.get("id") or "", "q": int(appt.get("seq") or 0)},
                     separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{body}.{sig}"


def parse_invite(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:24]):
            return None
        d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        datetime.fromisoformat(d["w"])
        return {"when": d["w"], "minutes": int(d.get("m") or DEFAULT_MINUTES), "place": d.get("p") or "",
                "store": d.get("s") or "", "id": d.get("i") or "", "seq": int(d.get("q") or 0)}
    except Exception:  # noqa: BLE001 — any malformed token is simply not an invite
        return None


def event_title(client_name: str, seat_name: str, store_name: str) -> str:
    """What the entry is called in both calendars: who is meeting whom, and where."""
    who = " and ".join([n for n in (str(client_name or "").strip(), str(seat_name or "").strip()) if n])
    head = f"Appointment with {who}" if who else "Appointment"
    return f"{head} at {store_name}" if store_name else head


def seat_email(seat_id: Optional[str]) -> str:
    """The associate's own address, so they are on the invite beside the client."""
    if not seat_id:
        return ""
    try:
        return str((shop_store().seat_profile(seat_id) or {}).get("email") or "")
    except Exception:  # noqa: BLE001
        return ""


def _people_ics(client_name: str, client_email: str, seat_name: str, seat_email_: str) -> list[str]:
    """ORGANIZER and ATTENDEE lines. The associate hosts; both of them are on it."""
    def cn(name: str) -> str:
        clean = str(name or "").replace('"', "").replace(";", " ").replace(":", " ").strip()
        return f';CN="{clean}"' if clean else ""
    lines = []
    if seat_email_:
        lines.append(f"ORGANIZER{cn(seat_name)}:mailto:{seat_email_}")
    if client_email:
        lines.append(f"ATTENDEE{cn(client_name)};ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{client_email}")
    if seat_email_:
        lines.append(f"ATTENDEE{cn(seat_name)};ROLE=REQ-PARTICIPANT:mailto:{seat_email_}")
    return lines


def client_message(appt: dict, store_name: str, invite_url: str) -> str:
    """The line an associate sends the client, ready to paste."""
    start = datetime.fromisoformat(appt["when"])
    when = start.strftime("%A %d %B at %H:%M")
    where = f" at {appt['place']}" if appt.get("place") else (f" at {store_name}" if store_name else "")
    return f"Your appointment is set for {when}{where}. Add it to your calendar here: {invite_url}"


def calendar_links(appt: dict, client_name: str, store_name: str, shop: str = "",
                   client_email: str = "") -> dict:
    """Links into the associate's own calendar. Google and Outlook open prefilled; the .ics text
    is for Apple Calendar and anything else (served as a download by the callers). Both people are
    on the entry: the associate hosts it, the client is invited."""
    start = datetime.fromisoformat(appt["when"])
    end = start + timedelta(minutes=int(appt.get("minutes") or DEFAULT_MINUTES))
    fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    seat_name = str(appt.get("seat_name") or "")
    seat_addr = seat_email(appt.get("seat_id"))
    title = event_title(client_name, seat_name, store_name)
    details = appt.get("note") or ""
    place = appt.get("place") or store_name or ""
    guests = [e for e in (client_email, seat_addr) if e]
    q = {"action": "TEMPLATE", "text": title, "dates": f"{fmt(start)}/{fmt(end)}",
         "details": details, "location": place}
    if guests:
        q["add"] = ",".join(guests)
    google = "https://calendar.google.com/calendar/render?" + urlencode(q)
    oq = {"subject": title, "startdt": start.astimezone(timezone.utc).isoformat(),
          "enddt": end.astimezone(timezone.utc).isoformat(), "body": details, "location": place,
          "path": "/calendar/action/compose"}
    if guests:
        oq["to"] = ",".join(guests)
    outlook = "https://outlook.office.com/calendar/0/deeplink/compose?" + urlencode(oq)
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Halia//Appointments//EN", "BEGIN:VEVENT",
        f"UID:{appt['id']}@haliascore.com", f"DTSTAMP:{fmt(datetime.now(timezone.utc))}",
        f"SEQUENCE:{int(appt.get('seq') or 0)}",
        f"DTSTART:{fmt(start)}", f"DTEND:{fmt(end)}", f"SUMMARY:{_ics_escape(title)}",
        f"LOCATION:{_ics_escape(place)}", f"DESCRIPTION:{_ics_escape(details)}",
        *_people_ics(client_name, client_email, seat_name, seat_addr),
        "END:VEVENT", "END:VCALENDAR", ""])
    token = invite_token(appt, store_name)
    if shop:
        from halia.api.client_host import client_url
        invite = client_url(shop, f"i/{token}")
    else:
        invite = (config.HALIA_APP_URL or "https://haliascore.com").rstrip("/") + f"/i/{token}"
    # title/start/end/minutes come back too: six surfaces were each re-deriving some of this, and
    # a client that has to build the event itself (the Outlook pane opens a real meeting form) must
    # not invent a second way of naming the same appointment.
    return {"google": google, "outlook": outlook, "ics": ics,
            "ics_data": "data:text/calendar;charset=utf-8," + quote(ics),
            "invite": invite, "message": client_message(appt, store_name, invite),
            "title": title, "location": place,
            "start": start.isoformat(), "end": end.isoformat(),
            "minutes": int(appt.get("minutes") or DEFAULT_MINUTES)}


_INVITE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>{store}</title><style>
  *{{box-sizing:border-box}} body{{margin:0;background:#f8f7f5;color:#1a1a1d;font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
  .wrap{{max-width:430px;margin:0 auto;padding:40px 22px 60px}}
  h1{{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:27px;margin:0 0 6px}}
  .sub{{color:#6b6b70;font-size:14px;margin:0 0 28px}}
  .when{{font-family:Georgia,serif;font-size:24px;margin:0 0 4px}} .where{{color:#3d3d40;margin:0 0 30px}}
  a.b{{display:block;text-align:center;margin-top:10px;padding:14px;border:1px solid #1a1a1d;border-radius:12px;color:#1a1a1d;text-decoration:none;font-weight:600}}
  a.b.p{{background:#1a1a1d;color:#fff}}
</style></head><body><div class="wrap">
 {head}<p class="when">{when}</p><p class="where">{where}</p>
 <a class="b p" id="ics" href="{ics}">Add to my calendar</a>
 <a class="b" href="{google}" rel="noopener">Google Calendar</a>
 <a class="b" href="{outlook}" rel="noopener">Outlook</a>
</div><script>(function(){{var q=new URLSearchParams(location.search).get('halia-page');
if(q)document.getElementById('ics').href=location.pathname+'?halia-page='+q+'.ics';}})();</script></body></html>"""


def _ics_escape(s: str) -> str:
    return str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def book(shop: str, cid: str, when: Any, minutes: Any, place: str, note: str,
         actor_id: Optional[str], actor_name: Optional[str]) -> dict:
    """Write the appointment to the client's record and log it. Returns the appointment."""
    from halia.api.board import _sink, _write_soft, append_activity, load_pipe
    from scoring.shopify_pipeline import STAGES, stage_tag

    start = _parse_when(when)
    mins = max(15, min(int(minutes or DEFAULT_MINUTES), 480))
    appt = {"id": secrets.token_hex(6), "seq": 0,
            "when": start.isoformat(timespec="minutes"), "minutes": mins,
            "place": str(place or "").strip()[:120], "note": str(note or "").strip()[:500],
            "seat_id": actor_id, "seat_name": actor_name or "", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    sink = _sink(shop)
    pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    kept = [a for a in (pipe.get("appointments") or [])
            if a.get("when") and datetime.fromisoformat(a["when"]) >= cutoff]
    pipe["appointments"] = kept + [appt]
    if not pipe.get("stage"):                       # a booking puts them on the board
        stage = STAGES[0]
        pipe["stage"] = stage
        sink.untag_customer(cid, [stage_tag(s) for s in STAGES if s != stage])
        sink.tag_customer(cid, [stage_tag(stage)])
    append_activity(pipe, "appointment", actor_id, actor_name,
                    note=_label(start, mins) + (f" at {appt['place']}" if appt["place"] else ""))
    if _write_soft(sink, cid, pipe):
        raise HTTPException(502, "Could not save to the store just now. Please try again.")
    _invalidate(shop)
    return appt


def reschedule(shop: str, cid: str, appt_id: str, when: Any, minutes: Any, place: Any,
               actor_id: Optional[str], actor_name: Optional[str]) -> Optional[dict]:
    """Move an appointment that is already in the client's record. The entry keeps its id, so the
    client's calendar updates the event they already hold rather than gaining a second one. Returns
    the changed appointment, or None when there is nothing by that id."""
    from halia.api.board import _sink, _write_soft, append_activity, load_pipe

    start = _parse_when(when)
    sink = _sink(shop)
    pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
    rows = pipe.get("appointments") or []
    appt = next((a for a in rows if a.get("id") == appt_id), None)
    if not appt:
        return None
    was = _label(datetime.fromisoformat(appt["when"]), int(appt.get("minutes") or DEFAULT_MINUTES))
    appt["seq"] = int(appt.get("seq") or 0) + 1      # a new revision of the same entry
    appt["when"] = start.isoformat(timespec="minutes")
    appt["minutes"] = max(15, min(int(minutes or appt.get("minutes") or DEFAULT_MINUTES), 480))
    if place is not None:
        appt["place"] = str(place or "").strip()[:120]
    pipe["appointments"] = rows
    append_activity(pipe, "appointment_moved", actor_id, actor_name,
                    note=f"{was} moved to " + _label(start, int(appt["minutes"]))
                         + (f" at {appt['place']}" if appt.get("place") else ""))
    if _write_soft(sink, cid, pipe):
        raise HTTPException(502, "Could not save to the store just now. Please try again.")
    _invalidate(shop)
    return appt


def cancel(shop: str, cid: str, appt_id: str, actor_id: Optional[str], actor_name: Optional[str]) -> bool:
    from halia.api.board import _sink, _write_soft, append_activity, load_pipe
    sink = _sink(shop)
    pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
    before = pipe.get("appointments") or []
    gone = next((a for a in before if a.get("id") == appt_id), None)
    if not gone:
        return False
    pipe["appointments"] = [a for a in before if a.get("id") != appt_id]
    append_activity(pipe, "appointment_cancelled", actor_id, actor_name,
                    note=_label(datetime.fromisoformat(gone["when"]), int(gone.get("minutes") or DEFAULT_MINUTES)))
    if _write_soft(sink, cid, pipe):
        raise HTTPException(502, "Could not save to the store just now. Please try again.")
    _invalidate(shop)
    return True


OUTCOMES = ("attended", "no_show")


def record_outcome(shop: str, cid: str, appt_id: str, outcome: str,
                   actor_id: Optional[str], actor_name: Optional[str]) -> Optional[dict]:
    """Mark a visit as attended or a no-show. Only after it has started: nobody can say how a
    future appointment went, and letting them would quietly corrupt the associate's numbers."""
    from halia.api.board import _sink, _write_soft, append_activity, load_pipe

    if outcome not in OUTCOMES:
        raise HTTPException(422, "Outcome must be attended or no_show.")
    sink = _sink(shop)
    pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
    appt = next((a for a in (pipe.get("appointments") or []) if a.get("id") == appt_id), None)
    if not appt:
        return None
    try:
        when = datetime.fromisoformat(appt["when"])
    except (KeyError, ValueError):
        raise HTTPException(422, "That appointment has no usable time.")
    if when > datetime.now(timezone.utc):
        raise HTTPException(422, "That visit has not happened yet.")
    appt["status"] = outcome
    append_activity(pipe, f"appointment_{outcome}", actor_id, actor_name,
                    note=_label(when, int(appt.get("minutes") or DEFAULT_MINUTES)))
    if _write_soft(sink, cid, pipe):
        raise HTTPException(502, "Could not save to the store just now. Please try again.")
    _invalidate(shop)
    return appt


def due_reminders(shop: str, within_hours: int = 24, already: int = 2) -> list[dict]:
    """Visits starting inside the window that have not been reminded about. ``already`` is the
    lower bound in hours, so the hourly cron does not send the same nudge twice."""
    now = datetime.now(timezone.utc)
    soon = now + timedelta(hours=max(1, within_hours))
    floor = now + timedelta(hours=max(0, already))
    out = []
    for row in upcoming(shop, days=2):
        try:
            when = datetime.fromisoformat(row["when"])
        except (KeyError, ValueError):
            continue
        if floor <= when <= soon:
            out.append(row)
    return out


def upcoming(shop: str, days: int = 14, seat_id: Optional[str] = None,
             past_days: int = 0) -> list[dict]:
    """Every appointment in the next ``days`` across the board, soonest first. ``past_days``
    reaches back as well (the calendar view shows the month as it was, not just what is ahead);
    the record keeps KEEP_DAYS behind it, so that is the natural bound."""
    from halia.api.board import _sink, pipeline_cards
    try:
        cards = pipeline_cards(_sink(shop))
    except HTTPException:
        return []
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=max(1, min(int(days or 14), 90)))
    floor = now - (timedelta(days=min(int(past_days), KEEP_DAYS)) if past_days
                   else timedelta(hours=2))
    out = []
    for card in cards.values():
        for a in card.get("appointments") or []:
            try:
                when = datetime.fromisoformat(a["when"])
            except (KeyError, ValueError):
                continue
            if floor <= when <= horizon:
                out.append({**a, "cid": card["cid"], "name": card.get("name") or "", "email": card.get("email") or "",
                            "in_days": (when.date() - now.date()).days,
                            "mine": bool(seat_id and a.get("seat_id") == seat_id)})
    out.sort(key=lambda x: x["when"])
    return out


def clashes(shop: str, when: Any, minutes: Any = None, seat_id: Optional[str] = None,
            cid: str = "", ignore_id: str = "") -> list[dict]:
    """Anything the proposed time runs into: the same associate booked elsewhere, or the same
    client booked twice. Overlap is strict, so a visit ending at 15:00 and one starting at 15:00
    do not clash.

    A warning, never a block. An associate double-booking themselves on purpose is a normal thing
    to do, and refusing it would send them somewhere else to work."""
    try:
        start = _parse_when(when)
    except HTTPException:
        return []
    mins = max(15, min(int(minutes or DEFAULT_MINUTES), 480))
    end = start + timedelta(minutes=mins)
    out = []
    # 90 is the horizon upcoming() allows, and it only looks forward, which is all we need: a time
    # in the past cannot be double-booked in any way worth warning about.
    for row in upcoming(shop, days=90):
        if row.get("id") == ignore_id:
            continue
        mine = seat_id and row.get("seat_id") == seat_id
        theirs = cid and str(row.get("cid")) == str(cid)
        if not (mine or theirs):
            continue
        try:
            r_start = datetime.fromisoformat(row["when"])
        except (KeyError, ValueError):
            continue
        r_end = r_start + timedelta(minutes=int(row.get("minutes") or DEFAULT_MINUTES))
        if r_start < end and start < r_end:
            out.append({"id": row.get("id"), "cid": row.get("cid"), "name": row.get("name") or "",
                        "when": row["when"], "minutes": int(row.get("minutes") or DEFAULT_MINUTES),
                        "seat_name": row.get("seat_name") or "",
                        "why": "you" if mine else "them"})
    return out


def outside_hours(shop: str, when: Any, minutes: Any = None) -> str:
    """A plain sentence when the time falls outside the shop's own opening hours, else "".
    A store that has not set hours is never warned about."""
    try:
        from halia.api.settings import DAYS, settings_for
        hours = (settings_for(shop) or {}).get("hours") or {}
    except Exception:  # noqa: BLE001 — a settings hiccup must never block a booking
        return ""
    if not hours:
        return ""
    try:
        start = _parse_when(when)
    except HTTPException:
        return ""
    end = start + timedelta(minutes=max(15, min(int(minutes or DEFAULT_MINUTES), 480)))
    row = hours.get(DAYS[start.weekday()]) or {}
    day = start.strftime("%A")
    if row.get("closed"):
        return f"The shop is closed on {day}."
    def _mins(hhmm: str) -> int:
        h, _, m = str(hhmm or "").partition(":")
        return int(h or 0) * 60 + int(m or 0)
    opens, shuts = _mins(row.get("open")), _mins(row.get("close"))
    s_min = start.hour * 60 + start.minute
    e_min = s_min + int((end - start).total_seconds() // 60)
    if s_min < opens:
        return f"That is before the shop opens on {day} ({row['open']})."
    if e_min > shuts:
        return f"That runs past closing on {day} ({row['close']})."
    return ""


def _warnings(shop: str, appt: dict, seat_id: Optional[str], cid: str) -> dict:
    """What a surface should say before the associate walks away. Informational: every one of
    these is a booking a person may legitimately want."""
    return {"clash": clashes(shop, appt["when"], appt.get("minutes"), seat_id=seat_id, cid=cid,
                             ignore_id=appt.get("id") or ""),
            "outside_hours": outside_hours(shop, appt["when"], appt.get("minutes"))}


def _invalidate(shop: str) -> None:
    try:
        from halia.api import reports
        reports.invalidate(shop)
    except Exception:  # noqa: BLE001
        pass


def _store_name(shop: str) -> str:
    # dict() first: the store hands back a sqlite3.Row, which has no .get. Falls back to the
    # domain, so the client's page is always headed by the shop and never by "Appointment".
    t = dict(shop_store().get_tenant(shop) or {})
    name = str(t.get("label") or "").strip()
    if name:
        return name
    host = str(shop or "").replace(".myshopify.com", "").strip("/")
    host = host.split("//")[-1].split("/")[0]
    return host.replace("-", " ").title() if host else ""


def render_invite(token: str):
    """The client's side of an appointment: a store-voiced page with the time, the place and
    one tap into their own calendar. Everything it shows is in the signed link; nothing is read
    or stored. Halia is not named on it. Served on the store's own domain wherever possible."""
    import html as _html
    ics_wanted = token.endswith(".ics")
    inv = parse_invite(token[:-4] if ics_wanted else token)
    if not inv:
        raise HTTPException(404, "Not found")
    appt = {"id": inv["id"] or hashlib.sha1(token.encode()).hexdigest()[:12], "when": inv["when"],
            "minutes": inv["minutes"], "place": inv["place"], "note": ""}
    start = datetime.fromisoformat(inv["when"])
    end = start + timedelta(minutes=inv["minutes"])
    fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # The client's copy names nobody: the store, the time and the place, and no addresses. Their
    # associate's own copy is the one that carries both people.
    title = f"Appointment at {inv['store']}" if inv["store"] else "Appointment"
    place = inv["place"] or inv["store"]
    if ics_wanted:
        ics = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Halia//Appointments//EN", "BEGIN:VEVENT",
                            f"UID:{appt['id']}@haliascore.com", f"DTSTAMP:{fmt(datetime.now(timezone.utc))}",
                            f"SEQUENCE:{inv['seq']}",
                            f"DTSTART:{fmt(start)}", f"DTEND:{fmt(end)}", f"SUMMARY:{_ics_escape(title)}",
                            f"LOCATION:{_ics_escape(place)}", "END:VEVENT", "END:VCALENDAR", ""])
        return Response(ics, media_type="text/calendar; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="appointment.ics"'})
    google = "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE", "text": title, "dates": f"{fmt(start)}/{fmt(end)}", "location": place})
    outlook = "https://outlook.office.com/calendar/0/deeplink/compose?" + urlencode({
        "subject": title, "startdt": start.astimezone(timezone.utc).isoformat(),
        "enddt": end.astimezone(timezone.utc).isoformat(), "location": place, "path": "/calendar/action/compose"})
    store = _html.escape(inv["store"] or "")
    html = _INVITE_PAGE.format(store=store or "Appointment",          # the tab's title only
                               head=(f"<h1>{store}</h1>" if store else ""),
                               when=_html.escape(start.strftime("%A %d %B, %H:%M")),
                               where=_html.escape(place), ics=f"{token}.ics",
                               google=_html.escape(google), outlook=_html.escape(outlook))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def register(app) -> None:
    from halia.api.board import _actor

    @app.post("/v1/board/appointment")
    def board_appointment(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        cid = str(p.get("cid") or "").strip()
        if not cid:
            raise HTTPException(422, "cid is required.")
        actor_id, actor_name = _actor(request, p)
        appt = book(shop, cid, p.get("when"), p.get("minutes"), p.get("place"), p.get("note"), actor_id, actor_name)
        return {"ok": True, "appointment": appt,
                "links": calendar_links(appt, str(p.get("client_name") or ""), _store_name(shop), shop,
                                        client_email=str(p.get("client_email") or "")),
                **_warnings(shop, appt, actor_id, cid)}

    @app.post("/v1/board/appointment/reschedule")
    def board_appointment_reschedule(request: Request, shop: str = Depends(require_shop),
                                     payload: Any = Body(...)) -> dict:
        p = payload or {}
        cid = str(p.get("cid") or "").strip()
        actor_id, actor_name = _actor(request, p)
        appt = reschedule(shop, cid, str(p.get("id") or "").strip(),
                          p.get("when"), p.get("minutes"), p.get("place"), actor_id, actor_name)
        if not appt:
            raise HTTPException(404, "That appointment is no longer in the client's record.")
        return {"ok": True, "appointment": appt,
                "links": calendar_links(appt, str(p.get("client_name") or ""), _store_name(shop), shop,
                                        client_email=str(p.get("client_email") or "")),
                **_warnings(shop, appt, actor_id, cid)}

    @app.post("/v1/board/appointment/outcome")
    def board_appointment_outcome(request: Request, shop: str = Depends(require_shop),
                                  payload: Any = Body(...)) -> dict:
        p = payload or {}
        actor_id, actor_name = _actor(request, p)
        appt = record_outcome(shop, str(p.get("cid") or "").strip(), str(p.get("id") or "").strip(),
                              str(p.get("outcome") or "").strip(), actor_id, actor_name)
        if not appt:
            raise HTTPException(404, "That appointment is no longer in the client's record.")
        return {"ok": True, "appointment": appt}

    @app.post("/v1/board/appointment/cancel")
    def board_appointment_cancel(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        actor_id, actor_name = _actor(request, p)
        ok = cancel(shop, str(p.get("cid") or "").strip(), str(p.get("id") or "").strip(), actor_id, actor_name)
        return {"ok": ok}

    @app.get("/i/{token}", include_in_schema=False)
    def invite_page(token: str):
        return render_invite(token)

    @app.get("/v1/appointments/check")
    def check_time(shop: str = Depends(require_shop), when: str = Query(...),
                   minutes: int = Query(0), cid: Optional[str] = Query(None),
                   seat_id: Optional[str] = Query(None)) -> dict:
        """The dashboard's twin of /v1/extension/check_time."""
        return {"clash": clashes(shop, when, minutes, seat_id=seat_id, cid=str(cid or "")),
                "outside_hours": outside_hours(shop, when, minutes)}

    @app.get("/v1/appointments")
    def list_appointments(shop: str = Depends(require_shop), days: int = Query(14),
                          past: int = Query(0)) -> dict:
        rows = upcoming(shop, days, past_days=max(0, min(int(past or 0), KEEP_DAYS)))
        store = _store_name(shop)
        return {"appointments": [{**a, "links": calendar_links(a, a.get("name") or "", store, shop,
                                                               client_email=a.get("email") or "")}
                                 for a in rows]}
