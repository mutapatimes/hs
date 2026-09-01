"""Appointments live in the client's own record and the associate's own calendar."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from halia.api import appointments, board, onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "maison.myshopify.com"


class FakeSink:
    def __init__(self): self.meta, self.tags = {}, []
    def get_metafield(self, cid, key, namespace="halia"): return self.meta.get((cid, key))
    def set_metafield(self, cid, key, value, *a, **k): self.meta[(cid, key)] = value
    def tag_customer(self, cid, tags): self.tags.append(("+", cid, tags))
    def untag_customer(self, cid, tags): self.tags.append(("-", cid, tags))
    def pipeline_cards(self):
        out = {}
        for (cid, key), raw in self.meta.items():
            if key == "pipeline":
                p = json.loads(raw)
                out[cid] = {"cid": cid, "stage": p.get("stage"), "name": "Grace Ladoja", "email": "g@x.com",
                            "assignee": p.get("assignee"), "activity": p.get("activity") or [],
                            "appointments": p.get("appointments") or []}
        return out


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "a.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Maison", hash_token(tok))
    sink = FakeSink()
    monkeypatch.setattr(board, "_sink", lambda shop: sink)
    from halia.api import reports
    reports._REPORT_CACHE.clear()
    yield TestClient(app, cookies={COOKIE: tok}), store, sink


def _soon(days=3, hour=15):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


def test_booking_writes_the_record_and_hands_back_calendar_links(env):
    client, store, sink = env
    when = _soon()
    r = client.post("/v1/board/appointment", json={"cid": "c1", "when": when.isoformat(), "place": "Mount Street",
                                                   "client_name": "Grace Ladoja", "actor": "Sarah"})
    assert r.status_code == 200, r.text
    d = r.json()
    appt, links = d["appointment"], d["links"]
    assert appt["place"] == "Mount Street" and appt["minutes"] == 45
    assert "calendar.google.com" in links["google"] and "outlook.office.com" in links["outlook"]
    assert "BEGIN:VEVENT" in links["ics"] and "SUMMARY:Appointment with Grace Ladoja and Sarah at Maison" in links["ics"]
    assert links["ics_data"].startswith("data:text/calendar")
    pipe = json.loads(sink.meta[("c1", "pipeline")])
    assert pipe["appointments"][0]["id"] == appt["id"] and pipe["stage"] == "To reach out"
    assert pipe["activity"][-1]["action"] == "appointment" and "Mount Street" in pipe["activity"][-1]["note"]
    assert any(t[0] == "+" for t in sink.tags)


def test_upcoming_lists_the_next_fortnight_and_cancel_removes(env):
    client, store, sink = env
    client.post("/v1/board/appointment", json={"cid": "c1", "when": _soon(3).isoformat(), "actor": "Sarah"})
    far = client.post("/v1/board/appointment", json={"cid": "c1", "when": _soon(40).isoformat(), "actor": "Sarah"}).json()
    rows = client.get("/v1/appointments?days=14").json()["appointments"]
    assert len(rows) == 1 and rows[0]["name"] == "Grace Ladoja" and rows[0]["in_days"] == 3 and rows[0]["links"]["google"]
    assert len(client.get("/v1/appointments?days=60").json()["appointments"]) == 2
    r = client.post("/v1/board/appointment/cancel", json={"cid": "c1", "id": far["appointment"]["id"]})
    assert r.json()["ok"] is True
    pipe = json.loads(sink.meta[("c1", "pipeline")])
    assert len(pipe["appointments"]) == 1 and pipe["activity"][-1]["action"] == "appointment_cancelled"
    assert client.post("/v1/board/appointment/cancel", json={"cid": "c1", "id": "nope"}).json()["ok"] is False


def test_rescheduling_moves_the_entry_the_client_already_has(env):
    client, store, sink = env
    d = client.post("/v1/board/appointment", json={"cid": "c1", "when": _soon(3, 15).isoformat(),
                                                   "place": "Mount Street", "client_name": "Grace",
                                                   "actor": "Sarah"}).json()
    appt_id = d["appointment"]["id"]
    r = client.post("/v1/board/appointment/reschedule",
                    json={"cid": "c1", "id": appt_id, "when": _soon(5, 11).isoformat(),
                          "place": "Bond Street", "client_name": "Grace", "actor": "Sarah"})
    assert r.status_code == 200
    moved = r.json()["appointment"]
    assert moved["id"] == appt_id and moved["place"] == "Bond Street"   # same entry, moved
    pipe = json.loads(sink.meta[("c1", "pipeline")])
    assert len(pipe["appointments"]) == 1 and pipe["appointments"][0]["id"] == appt_id
    assert pipe["activity"][-1]["action"] == "appointment_moved" and "moved to" in pipe["activity"][-1]["note"]
    # the invitation is rebuilt for the new time
    assert "11:00" in r.json()["links"]["message"] and "Bond Street" in r.json()["links"]["message"]
    assert client.post("/v1/board/appointment/reschedule",
                       json={"cid": "c1", "id": "nope", "when": _soon(6).isoformat()}).status_code == 404


def test_the_keyboard_and_app_can_move_and_cancel_a_booking(env):
    client, store, sink = env
    seat_tok = new_token()
    store.create_seat(SHOP, "Sarah Bloom", hash_token(seat_tok), "sarah@m.com")
    h = {"X-Halia-Ext-Token": seat_tok}
    booked = client.post("/v1/extension/action",
                         json={"action": "appointment", "cid": "c1", "when": _soon(2).isoformat(),
                               "client_name": "Grace"}, headers=h).json()["appointment"]
    r = client.post("/v1/extension/action",
                    json={"action": "appointment_move", "cid": "c1", "id": booked["id"],
                          "when": _soon(9, 16).isoformat(), "place": "Bond Street",
                          "client_name": "Grace"}, headers=h)
    assert r.status_code == 200 and r.json()["appointment"]["place"] == "Bond Street"
    rows = client.get("/v1/extension/appointments?days=30", headers=h).json()["appointments"]
    assert len(rows) == 1 and rows[0]["place"] == "Bond Street"
    assert client.post("/v1/extension/action",
                       json={"action": "appointment_cancel", "cid": "c1", "id": booked["id"]},
                       headers=h).json()["ok"] is True
    assert json.loads(sink.meta[("c1", "pipeline")])["appointments"] == []


def test_bad_when_is_rejected(env):
    client, store, sink = env
    assert client.post("/v1/board/appointment", json={"cid": "c1", "when": "next tuesday"}).status_code == 422
    assert client.post("/v1/board/appointment", json={"cid": "c1"}).status_code == 422


def test_extension_books_and_lists_with_the_seat_attributed(env):
    client, store, sink = env
    seat_tok = new_token()
    sid = store.create_seat(SHOP, "Sarah Bloom", hash_token(seat_tok), "sarah@m.com")
    h = {"X-Halia-Ext-Token": seat_tok}
    r = client.post("/v1/extension/action", json={"action": "appointment", "cid": "c1", "when": _soon(2).isoformat(),
                                                  "place": "Bond Street", "client_name": "Grace"}, headers=h)
    assert r.status_code == 200 and r.json()["links"]["ics"]
    pipe = json.loads(sink.meta[("c1", "pipeline")])
    assert pipe["appointments"][0]["seat_id"] == sid and pipe["appointments"][0]["seat_name"] == "Sarah Bloom"
    rows = client.get("/v1/extension/appointments", headers=h).json()["appointments"]
    assert rows[0]["mine"] is True and rows[0]["place"] == "Bond Street"
    assert store.seat_month_metrics(sid) == {"appointments": 1}
    # the team report counts it for the seat
    rep = client.get("/v1/reports/associates?days=30").json()
    mine = next(s for s in rep["seats"] if s["id"] == sid)
    assert mine["appointments"] == 1 and rep["totals"]["appointments"] == 1


def test_ics_escapes_commas_and_newlines():
    appt = {"id": "abc", "when": "2026-09-14T15:00:00+00:00", "minutes": 30, "place": "Mount St, Mayfair", "note": "Ring\nsizes"}
    ics = appointments.calendar_links(appt, "Grace", "Maison")["ics"]
    assert "LOCATION:Mount St\\, Mayfair" in ics and "DESCRIPTION:Ring\\nsizes" in ics and "DTEND:20260914T153000Z" in ics


# ── the client's invite ───────────────────────────────────────────────────────
def test_invite_link_is_signed_store_voiced_and_carries_no_client_detail(env):
    client, store, sink = env
    d = client.post("/v1/board/appointment", json={"cid": "c1", "when": _soon(4, 11).isoformat(), "place": "Mount Street",
                                                   "client_name": "Grace Ladoja",
                                                   "client_email": "grace@x.com", "actor": "Sarah"}).json()
    links = d["links"]
    assert links["invite"].startswith("http") and "/i/" in links["invite"]
    assert links["message"].startswith("Your appointment is set for ") and "Mount Street" in links["message"] and links["invite"] in links["message"]
    token = links["invite"].rsplit("/i/", 1)[1]
    assert "Grace" not in token and "Ladoja" not in appointments.parse_invite(token).__repr__()
    page = client.get(f"/i/{token}")
    assert page.status_code == 200 and "Maison" in page.text and "Mount Street" in page.text
    assert "Grace" not in page.text and "grace@x.com" not in page.text and "Sarah" not in page.text
    assert "Halia" not in page.text.replace("haliascore", "")   # the store's page, not ours
    ics = client.get(f"/i/{token}.ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Appointment at Maison" in ics.text and "LOCATION:Mount Street" in ics.text
    assert "ATTENDEE" not in ics.text and "mailto:" not in ics.text   # nobody is named to the client
    assert client.get(f"/i/{token[:-3]}xyz").status_code == 404
    assert client.get("/i/garbage").status_code == 404


def test_the_associates_own_entry_names_both_people_and_carries_both_addresses(env):
    client, store, sink = env
    seat_tok = new_token()
    store.create_seat(SHOP, "Sarah Bloom", hash_token(seat_tok), "sarah@maison.com")
    r = client.post("/v1/extension/action",
                    json={"action": "appointment", "cid": "c1", "when": _soon(3).isoformat(),
                          "place": "Mount Street", "client_name": "Grace Ladoja",
                          "client_email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": seat_tok})
    links = r.json()["links"]
    assert "SUMMARY:Appointment with Grace Ladoja and Sarah Bloom at Maison" in links["ics"]
    assert 'ORGANIZER;CN="Sarah Bloom":mailto:sarah@maison.com' in links["ics"]
    assert 'ATTENDEE;CN="Grace Ladoja";ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:grace@x.com' in links["ics"]
    assert "add=grace%40x.com%2Csarah%40maison.com" in links["google"]
    assert "to=grace%40x.com%2Csarah%40maison.com" in links["outlook"]
    # the client's own copy stays anonymous: the store, the time, the place, and nobody named
    ics = client.get("/i/" + links["invite"].rsplit("/i/", 1)[1] + ".ics").text
    assert "SUMMARY:Appointment at Maison" in ics
    assert "Grace" not in ics and "Sarah" not in ics and "mailto:" not in ics


def test_the_invite_page_is_headed_by_the_store_even_with_no_label(env, monkeypatch):
    from halia.api import appointments as ap
    client, store, sink = env
    monkeypatch.setattr(ap.shop_store(), "get_tenant", lambda shop: {"label": ""})
    assert ap._store_name("glen-norah-vmskd33v.myshopify.com") == "Glen Norah Vmskd33V"


def test_invite_and_capture_serve_on_the_store_domain_through_the_proxy(env, monkeypatch):
    import halia.config as hcfg
    from tests.test_catalog import _proxy_sig
    monkeypatch.setattr(hcfg, "SHOPIFY_API_SECRET", "sekret")
    monkeypatch.setattr("halia.api.catalog._primary_domain", lambda shop: "maison.com")
    from halia.api import client_host
    client_host._CACHE.clear()
    client, store, sink = env
    d = client.post("/v1/board/appointment", json={"cid": "c1", "when": _soon(2).isoformat(), "client_name": "Grace"}).json()
    assert d["links"]["invite"].startswith("https://maison.com/a/catalogue/i/")
    token = d["links"]["invite"].rsplit("/i/", 1)[1]
    params = {"shop": SHOP, "path_prefix": "/a/catalogue", "timestamp": "1"}
    q = "&".join(f"{k}={v}" for k, v in params.items()) + "&signature=" + _proxy_sig(params, "sekret")
    page = client.get(f"/proxy/catalogue/i/{token}?{q}")
    assert page.status_code == 200 and 'href="' + token + '.ics"' in page.text and 'href="/i/' not in page.text
    assert client.get(f"/proxy/catalogue/i/{token}.ics?{q}").headers["content-type"].startswith("text/calendar")
    assert client.get(f"/proxy/catalogue/i/{token}").status_code == 403
    client_host._CACHE.clear()


def test_invite_page_carries_the_store_name_once_and_never_a_placeholder_heading(env, monkeypatch):
    client, store, sink = env
    from halia.api import appointments as ap
    links = ap.calendar_links({"id": "x", "when": _soon(2, 14).isoformat(timespec="minutes"),
                               "minutes": 45, "place": "Mount Street", "note": ""}, "Grace", "Maison")
    page = client.get("/i/" + links["invite"].rsplit("/i/", 1)[1])
    assert page.status_code == 200
    assert page.text.count("Your appointment") == 0
    assert page.text.count("<h1>Maison</h1>") == 1
    # a store with no name shows no heading at all, rather than a placeholder
    links = ap.calendar_links({"id": "y", "when": _soon(2, 14).isoformat(timespec="minutes"),
                               "minutes": 45, "place": "", "note": ""}, "Grace", "")
    page = client.get("/i/" + links["invite"].rsplit("/i/", 1)[1])
    assert page.status_code == 200 and "<h1>" not in page.text and "Your appointment" not in page.text


def test_a_duration_survives_every_path(env):
    # No test asserted this before, which is how the Messages picker came to collect a duration and
    # drop it on the floor: HaliaAPI.bookAppointment had no minutes parameter at all.
    client, store, sink = env
    seat_tok = new_token()
    store.create_seat(SHOP, "Sarah", hash_token(seat_tok), "sarah@m.com")
    h = {"X-Halia-Ext-Token": seat_tok}
    d = client.post("/v1/board/appointment",
                    json={"cid": "c1", "when": _soon(3).isoformat(), "minutes": 90}).json()
    assert d["appointment"]["minutes"] == 90 and d["links"]["minutes"] == 90
    assert "DTEND:" in d["links"]["ics"]
    e = client.post("/v1/extension/action",
                    json={"action": "appointment", "cid": "c1", "when": _soon(4).isoformat(),
                          "minutes": 30}, headers=h).json()
    assert e["appointment"]["minutes"] == 30
    moved = client.post("/v1/extension/action",
                        json={"action": "appointment_move", "cid": "c1",
                              "id": e["appointment"]["id"], "when": _soon(5).isoformat(),
                              "minutes": 60}, headers=h).json()
    assert moved["appointment"]["minutes"] == 60


def test_a_moved_appointment_moves_the_entry_both_sides_already_hold(env):
    # The record keeps the id so the calendar entry updates rather than duplicating, but without a
    # SEQUENCE a calendar that honours it ignores the update, and the client's copy took its UID
    # from the token, which changes with the time, so they got a second entry instead.
    client, store, sink = env
    d = client.post("/v1/board/appointment",
                    json={"cid": "c1", "when": _soon(3, 15).isoformat(), "client_name": "Grace"}).json()
    appt_id = d["appointment"]["id"]
    assert "SEQUENCE:0" in d["links"]["ics"]
    first_token = d["links"]["invite"].rsplit("/i/", 1)[1]
    first_ics = client.get(f"/i/{first_token}.ics").text
    assert f"UID:{appt_id}@haliascore.com" in first_ics and "SEQUENCE:0" in first_ics

    r = client.post("/v1/board/appointment/reschedule",
                    json={"cid": "c1", "id": appt_id, "when": _soon(6, 11).isoformat(),
                          "client_name": "Grace"}).json()
    assert r["appointment"]["id"] == appt_id
    assert "SEQUENCE:1" in r["links"]["ics"]
    second_ics = client.get("/i/" + r["links"]["invite"].rsplit("/i/", 1)[1] + ".ics").text
    # Same UID, higher revision: their calendar updates the visit it already has.
    assert f"UID:{appt_id}@haliascore.com" in second_ics and "SEQUENCE:1" in second_ics
    assert "11:00" in r["links"]["message"]


def test_the_links_name_the_event_so_no_surface_has_to(env):
    # The Outlook pane opens a real meeting form and has to title it. Six surfaces already
    # re-derive parts of this; the server owns it.
    client, store, sink = env
    d = client.post("/v1/board/appointment",
                    json={"cid": "c1", "when": _soon(2, 14).isoformat(), "place": "Mount Street",
                          "client_name": "Grace Ladoja", "actor": "Sarah"}).json()
    links = d["links"]
    assert links["title"] == "Appointment with Grace Ladoja and Sarah at Maison"
    assert links["location"] == "Mount Street" and links["minutes"] == 45
    from datetime import datetime
    assert (datetime.fromisoformat(links["end"])
            - datetime.fromisoformat(links["start"])).total_seconds() == 45 * 60


def test_an_invite_made_before_ids_travelled_still_opens(env):
    # Tokens already in clients' inboxes carry no id and no revision.
    client, store, sink = env
    import base64 as _b64, hashlib as _h, hmac as _hm, json as _j
    from halia.api.tenant_auth import _secret
    raw = _j.dumps({"w": _soon(3).isoformat(timespec="minutes"), "m": 45, "p": "Mount Street",
                    "s": "Maison"}, separators=(",", ":")).encode()
    body = _b64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = _hm.new(_secret(), body.encode(), _h.sha256).hexdigest()[:24]
    old = f"{body}.{sig}"
    assert appointments.parse_invite(old)["id"] == ""
    page = client.get(f"/i/{old}")
    assert page.status_code == 200 and "Mount Street" in page.text
    ics = client.get(f"/i/{old}.ics")
    assert ics.status_code == 200 and "SEQUENCE:0" in ics.text


def test_a_clash_is_reported_and_never_refused(env):
    # book() appended unconditionally before this: one associate could be in three places at once
    # and the same client could be booked twice, with nothing said.
    client, store, sink = env
    seat_tok = new_token()
    sid = store.create_seat(SHOP, "Sarah", hash_token(seat_tok), "sarah@m.com")
    h = {"X-Halia-Ext-Token": seat_tok}
    first = client.post("/v1/extension/action",
                        json={"action": "appointment", "cid": "c1", "when": _soon(3, 15).isoformat(),
                              "minutes": 60, "client_name": "Grace"}, headers=h).json()
    assert first["clash"] == []                                    # nothing to run into yet

    # An overlapping visit for the same associate is booked, and reported.
    second = client.post("/v1/extension/action",
                         json={"action": "appointment", "cid": "c2",
                               "when": _soon(3, 15).replace(minute=30).isoformat(),
                               "client_name": "Ben"}, headers=h)
    assert second.status_code == 200
    clash = second.json()["clash"]
    assert len(clash) == 1 and clash[0]["id"] == first["appointment"]["id"]
    assert clash[0]["why"] == "you"
    assert len(json.loads(sink.meta[("c2", "pipeline")])["appointments"]) == 1   # not refused

    # Asked beforehand, the same answer, without booking anything.
    d = client.get("/v1/extension/check_time",
                   params={"when": _soon(3, 15).replace(minute=30).isoformat(), "minutes": 45},
                   headers=h).json()
    assert len(d["clash"]) == 2
    assert json.loads(sink.meta[("c1", "pipeline")])["appointments"][0]["seat_id"] == sid


def test_visits_that_only_touch_do_not_clash(env):
    # One ending at 15:00 and the next starting at 15:00 is a normal day, not a double booking.
    client, store, sink = env
    seat_tok = new_token()
    store.create_seat(SHOP, "Sarah", hash_token(seat_tok), "sarah@m.com")
    h = {"X-Halia-Ext-Token": seat_tok}
    client.post("/v1/extension/action",
                json={"action": "appointment", "cid": "c1", "when": _soon(4, 14).isoformat(),
                      "minutes": 60}, headers=h)
    d = client.get("/v1/extension/check_time",
                   params={"when": _soon(4, 15).isoformat(), "minutes": 30}, headers=h).json()
    assert d["clash"] == []


def test_a_time_outside_opening_hours_is_flagged_but_allowed(env):
    import json as _j
    client, store, sink = env
    # A store that has not set hours is never warned about.
    d = client.post("/v1/board/appointment",
                    json={"cid": "c1", "when": _soon(3, 3).isoformat()}).json()
    assert d["outside_hours"] == ""

    store.save_settings(SHOP, _j.dumps({"hours": {
        "mon": {"open": "10:00", "close": "18:00"}, "tue": {"open": "10:00", "close": "18:00"},
        "wed": {"open": "10:00", "close": "18:00"}, "thu": {"open": "10:00", "close": "18:00"},
        "fri": {"open": "10:00", "close": "18:00"}, "sat": {"open": "11:00", "close": "17:00"},
        "sun": {"closed": True}}}))
    # Find a weekday and a Sunday in the window so the assertion does not depend on today.
    def _on(weekday, hour):
        for d_ in range(1, 9):
            t = _soon(d_, hour)
            if t.weekday() == weekday:
                return t
        raise AssertionError("no such day in the window")

    early = client.post("/v1/board/appointment",
                        json={"cid": "c1", "when": _on(0, 8).isoformat()}).json()
    assert "before the shop opens on Monday (10:00)" in early["outside_hours"]
    late = client.post("/v1/board/appointment",
                       json={"cid": "c1", "when": _on(1, 17).isoformat(), "minutes": 120}).json()
    assert "past closing on Tuesday (18:00)" in late["outside_hours"]
    shut = client.post("/v1/board/appointment",
                       json={"cid": "c1", "when": _on(6, 12).isoformat()}).json()
    assert shut["outside_hours"] == "The shop is closed on Sunday."
    fine = client.post("/v1/board/appointment",
                       json={"cid": "c1", "when": _on(2, 11).isoformat()}).json()
    assert fine["outside_hours"] == ""
    # Flagged, never refused: every one of them is on the record.
    assert len(json.loads(sink.meta[("c1", "pipeline")])["appointments"]) == 5


def _past(hours=3):
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def test_a_visit_can_be_marked_attended_and_counts_for_the_associate(env):
    client, store, sink = env
    seat_tok = new_token()
    sid = store.create_seat(SHOP, "Sarah Bloom", hash_token(seat_tok), "sarah@m.com")
    h = {"X-Halia-Ext-Token": seat_tok}
    appt = client.post("/v1/extension/action",
                       json={"action": "appointment", "cid": "c1",
                             "when": _past(3).isoformat(), "client_name": "Grace"},
                       headers=h).json()["appointment"]
    r = client.post("/v1/extension/action",
                    json={"action": "appointment_outcome", "cid": "c1", "id": appt["id"],
                          "outcome": "attended"}, headers=h)
    assert r.status_code == 200 and r.json()["appointment"]["status"] == "attended"
    pipe = json.loads(sink.meta[("c1", "pipeline")])
    assert pipe["appointments"][0]["status"] == "attended"
    assert pipe["activity"][-1]["action"] == "appointment_attended"
    from halia.api import reports
    reports._REPORT_CACHE.clear()
    rep = client.get("/v1/reports/associates?days=30").json()
    mine = next(x for x in rep["seats"] if x["id"] == sid)
    assert mine["attended"] == 1 and mine["no_shows"] == 0
    assert rep["totals"]["attended"] == 1


def test_a_visit_that_has_not_happened_cannot_be_marked(env):
    # Otherwise an associate could mark next month's visits attended and quietly inflate the
    # numbers the team report is built on.
    client, store, sink = env
    appt = client.post("/v1/board/appointment",
                       json={"cid": "c1", "when": _soon(3).isoformat()}).json()["appointment"]
    r = client.post("/v1/board/appointment/outcome",
                    json={"cid": "c1", "id": appt["id"], "outcome": "attended"})
    assert r.status_code == 422 and "has not happened yet" in r.json()["detail"]
    bad = client.post("/v1/board/appointment/outcome",
                      json={"cid": "c1", "id": appt["id"], "outcome": "maybe"})
    assert bad.status_code == 422
    assert client.post("/v1/board/appointment/outcome",
                       json={"cid": "c1", "id": "nope", "outcome": "attended"}).status_code == 404


def test_tomorrows_visits_are_gathered_for_the_team_and_only_theirs(env, monkeypatch):
    client, store, sink = env
    from halia.api import appointments as ap
    client.post("/v1/board/appointment", json={"cid": "c1", "when":
        (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()})
    client.post("/v1/board/appointment", json={"cid": "c1", "when": _soon(10).isoformat()})
    rows = ap.due_reminders(SHOP)
    assert len(rows) == 1                       # the far one is not due yet
    # Within the "already told them" floor, nothing is due, so the hourly run does not repeat.
    assert ap.due_reminders(SHOP, already=12) == []

    sent = {}
    monkeypatch.setattr("halia.notify.email_configured", lambda: True)
    monkeypatch.setattr("halia.notify.send_email",
                        lambda to, subj, html, *a, **k: sent.update({"to": to, "subj": subj, "html": html}) or True)
    store.save_settings(SHOP, json.dumps({"notify_emails": ["team@maison.com"]}))
    from halia.api.capture_alerts import dispatch_visit_reminder
    assert dispatch_visit_reminder(SHOP, rows) == 1
    assert sent["to"] == "team@maison.com" and "1 visit coming up" in sent["subj"]
    assert "Grace Ladoja" in sent["html"]
    # It goes to the team, never to the client.
    assert "g@x.com" not in sent["to"]
