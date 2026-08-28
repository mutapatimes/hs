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
    assert "BEGIN:VEVENT" in links["ics"] and "SUMMARY:Grace Ladoja at Maison" in links["ics"]
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
                                                   "client_name": "Grace Ladoja"}).json()
    links = d["links"]
    assert links["invite"].startswith("http") and "/i/" in links["invite"]
    assert links["message"].startswith("Your appointment is set for ") and "Mount Street" in links["message"] and links["invite"] in links["message"]
    token = links["invite"].rsplit("/i/", 1)[1]
    assert "Grace" not in token and "Ladoja" not in appointments.parse_invite(token).__repr__()
    page = client.get(f"/i/{token}")
    assert page.status_code == 200 and "Maison" in page.text and "Mount Street" in page.text
    assert "Grace" not in page.text and "Halia" not in page.text.replace("haliascore", "")
    ics = client.get(f"/i/{token}.ics")
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Appointment at Maison" in ics.text and "LOCATION:Mount Street" in ics.text
    assert client.get(f"/i/{token[:-3]}xyz").status_code == 404
    assert client.get("/i/garbage").status_code == 404
