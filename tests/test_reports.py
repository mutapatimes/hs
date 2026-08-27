"""Team report: folded from pipeline activity + orders + seats, at view time, nothing stored."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from halia.api import board, onboarding, reports, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

SHOP = "report.myshopify.com"


def _iso(days_ago, hour=10):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(hour=hour, minute=0).isoformat()


def _day(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "r.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Maison", hash_token(tok))
    sarah = store.create_seat(SHOP, "Sarah Bloom", hash_token(new_token()), "sarah@m.com")
    omar = store.create_seat(SHOP, "Omar Haddad", hash_token(new_token()), "omar@m.com")
    store.update_seat_profile(sarah, title="Client Advisor")
    class Sink:
        def _transport(self): return None
    monkeypatch.setattr(board, "_sink", lambda shop: Sink())
    cards = {
        "c1": {"cid": "c1", "stage": "Contacted", "assignee": {"id": sarah, "name": "Sarah Bloom"},
               "activity": [{"action": "contacted", "actor_id": sarah, "at": _iso(10)},
                            {"action": "moved:Contacted", "actor_id": sarah, "at": _iso(10)}]},
        "c2": {"cid": "c2", "stage": "To reach out", "assignee": None,
               "activity": [{"action": "contacted", "actor_id": omar, "at": _iso(5)},
                            {"action": "contacted", "actor_id": sarah, "at": _iso(3)}]},
        "c3": {"cid": "c3", "stage": "Parked", "assignee": None,
               "activity": [{"action": "contacted", "actor_id": None, "at": _iso(2)},
                            {"action": "contacted", "actor_id": sarah, "at": _iso(60)}]},   # outside 30d
    }
    reports._REPORT_CACHE.clear()          # the RAM cache is module-level: isolate every test
    monkeypatch.setattr(reports, "fetch_pipeline_cards", lambda transport: cards)
    monkeypatch.setattr(reports, "fetch_captures", lambda transport: [
        {"cid": "c1", "channel": "handover", "seat_id": sarah, "at": _iso(6)},
        {"cid": "c9", "channel": "qr", "seat_id": "", "at": _iso(4)},          # unattended QR
        {"cid": "c3", "channel": "handover", "seat_id": omar, "at": _iso(50)},  # outside 30d
    ])
    cache.clear()
    cache.set(SHOP, results=[], payload={
        "data": [{"cid": "c1", "grade": "A*"}, {"cid": "c2", "grade": "B"}, {"cid": "c3", "grade": "A"}],
        "orders": [
            {"orderId": "#1", "cid": "c1", "date": _day(8), "amount": 900},    # 2 days after Sarah's contact
            {"orderId": "#2", "cid": "c2", "date": _day(1), "amount": 400},    # after Omar (5d) AND Sarah (3d): latest = Sarah
            {"orderId": "#3", "cid": "c1", "date": _day(40), "amount": 100},   # outside window
        ]}, orders=[])
    yield TestClient(app, cookies={COOKIE: tok}), store, sarah, omar
    cache.clear(); reports._REPORT_CACHE.clear()


def test_report_folds_activity_orders_and_seats(env):
    client, store, sarah, omar = env
    d = client.get("/v1/reports/associates?days=30").json()
    assert d["available"] and d["days"] == 30
    by = {r["id"]: r for r in d["seats"]}
    s, o = by[sarah], by[omar]
    assert s["name"] == "Sarah Bloom" and s["title"] == "Client Advisor"
    assert s["contacts"] == 2 and s["clients"] == 2 and s["moves"] == 1 and s["owned"] == 1
    assert s["conversions"] == 2 and s["revenue"] == 1300 and s["rate"] == 1.0
    assert s["topShare"] == 0.5                       # c1 is A*, c2 is B
    assert o["contacts"] == 1 and o["conversions"] == 0   # Sarah's later contact took the credit
    assert d["unattributed"]["contacts"] == 1         # the shared sign-in contact on c3
    assert d["totals"]["contacts"] == 4 and d["totals"]["revenue"] == 1300
    assert d["seats"][0]["id"] == sarah                # sorted by contacts
    assert s["captures"] == 1 and s["captured_top"] == 1   # c1 is A*
    assert o["captures"] == 0 and d["unattributed"]["captures"] == 1
    assert d["totals"]["captures"] == 2


def test_window_and_non_shopify(env, monkeypatch):
    client, store, sarah, omar = env
    d = client.get("/v1/reports/associates?days=4").json()
    by = {r["id"]: r for r in d["seats"]}
    assert by[sarah]["contacts"] == 1 and by[omar]["contacts"] == 0
    from fastapi import HTTPException
    monkeypatch.setattr(board, "_sink", lambda shop: (_ for _ in ()).throw(HTTPException(400, "no")))
    reports.invalidate(SHOP)
    assert client.get("/v1/reports/associates").json()["available"] is False


def test_seat_week_for_the_iphone_desk(env):
    client, store, sarah, omar = env
    from halia.api.tenant_auth import hash_token as _h, new_token as _n
    tok = _n(); store.rotate_seat_token(sarah, _h(tok))
    d = client.get("/v1/extension/week?days=30", headers={"X-Halia-Ext-Token": tok}).json()
    assert d["available"] and d["me"]["name"] == "Sarah Bloom" and d["me"]["contacts"] == 2
    assert d["me"]["captures"] == 1 and d["team"]["contacts"] == 4
    shared = _n(); store.set_extension_token(SHOP, _h(shared))
    assert client.get("/v1/extension/week", headers={"X-Halia-Ext-Token": shared}).json()["me"] is None


def test_report_is_cached_and_invalidated(env, monkeypatch):
    client, store, sarah, omar = env
    calls = []
    monkeypatch.setattr(reports, "fetch_captures", lambda transport: calls.append(1) or [])
    reports.invalidate(SHOP)
    client.get("/v1/reports/associates?days=30"); client.get("/v1/reports/associates?days=30")
    assert len(calls) == 1                       # second read served from RAM
    reports.invalidate(SHOP)
    client.get("/v1/reports/associates?days=30")
    assert len(calls) == 2


def test_former_teammates_keep_their_history(env):
    client, store, sarah, omar = env
    reports.invalidate(SHOP)
    store.revoke_seat(SHOP, omar)
    d = client.get("/v1/reports/associates?days=30").json()
    names = [r["name"] for r in d["seats"]]
    assert "Omar Haddad (former)" in names and names[-1].endswith("(former)")
    assert d["unattributed"]["contacts"] == 1     # Omar's contact did not fall into shared sign-in


def test_weekly_team_digest_renders_and_falls_back(env, monkeypatch):
    client, store, sarah, omar = env
    from halia import emails, journeys
    reports.invalidate(SHOP)
    team = journeys._team_summary(SHOP)
    # a 7-day digest: the contacts at 10 days out fall away, three remain
    assert team and team["totals"]["contacts"] == 3 and team["top"][0]["name"] == "Sarah Bloom"
    subject, html, text = emails.render("weekly_team", {"first": "Val", "team": team}, "https://x/u")
    assert "logged 3 contacts" in text and "Sarah Bloom" in html
    assert journeys._team_summary("nobody.myshopify.com") is None

