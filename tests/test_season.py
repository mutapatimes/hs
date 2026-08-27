"""The season, as a luxury house runs it: templates, campaign presets, birthdays surfaced, and
the same-day follow-up from an in-store capture."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from halia.api import birthdays as bd
from halia.api import board, onboarding, shopify_auth
from halia.api.app import app
from halia.api.settings import DEFAULT_TEMPLATES, SEASON_TEMPLATES
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

SHOP = "season.myshopify.com"


def test_season_templates_ship_in_the_defaults():
    names = {t["name"] for t in DEFAULT_TEMPLATES}
    for t in SEASON_TEMPLATES:
        assert t["name"] in names and "{first_name}" in t["body"] and "{sender}" in t["body"]
        assert "—" not in t["body"] and "discount" not in t["body"].lower()
    assert "A birthday note" in names


def test_parse_birthday_forms():
    assert bd.parse_birthday("14 June") == (6, 14)
    assert bd.parse_birthday("June 14th") == (6, 14)
    assert bd.parse_birthday("14/06") == (6, 14)
    assert bd.parse_birthday("1990-06-14") == (6, 14)
    assert bd.parse_birthday("14.06.1990") == (6, 14)
    assert bd.parse_birthday("soon") is None and bd.parse_birthday("") is None


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Maison", hash_token(tok))
    seat_tok = new_token()
    seat = store.create_seat(SHOP, "Sarah Bloom", hash_token(seat_tok), "sarah@m.com")
    cache.clear(); bd.invalidate(SHOP)
    cache.set(SHOP, results=[], payload={"data": [{"cid": "c1", "grade": "A*"}, {"cid": "c2", "grade": "B"}],
                                         "orders": []}, orders=[])
    yield TestClient(app, cookies={COOKIE: tok}), store, seat_tok, seat, monkeypatch
    cache.clear(); bd.invalidate(SHOP)


def test_upcoming_birthdays_window_and_rollover(env):
    client, store, seat_tok, seat, mp = env
    today = date(2026, 12, 28)
    mp.setattr(bd, "fetch_birthdays", lambda shop: [
        {"cid": "c1", "name": "Grace", "month": 1, "day": 3, "source": "captured"},    # 6 days, next year
        {"cid": "c2", "name": "Omar", "month": 12, "day": 29, "source": "store"},     # tomorrow
        {"cid": "c3", "name": "Far", "month": 3, "day": 1, "source": "captured"},     # outside 14 days
    ])
    rows = bd.upcoming(SHOP, 14, today=today)
    assert [r["name"] for r in rows] == ["Omar", "Grace"]
    assert rows[0]["in_days"] == 1 and rows[1]["date"] == "2027-01-03" and rows[1]["grade"] == "A*"
    # the endpoints use the real clock: give them a birthday three days out
    from datetime import timedelta
    soon = date.today() + timedelta(days=3)
    bd.invalidate(SHOP)
    mp.setattr(bd, "fetch_birthdays", lambda shop: [
        {"cid": "c1", "name": "Grace", "month": soon.month, "day": soon.day, "source": "captured"}])
    d = client.get("/v1/birthdays?days=14").json()
    assert d["count"] == 1 and d["birthdays"][0]["in_days"] == 3 and d["birthdays"][0]["grade"] == "A*"
    d2 = client.get("/v1/extension/birthdays", headers={"X-Halia-Ext-Token": seat_tok}).json()
    assert d2["count"] == 1
    # and the reach-today queue carries it with the note attached
    from halia.api.extension import _todos
    todos = [t for t in _todos(SHOP) if t["kind"] == "birthday"]
    assert todos and todos[0]["template"] == "A birthday note" and "3 days" in todos[0]["why"]


def test_campaign_presets_are_a_luxury_calendar(env):
    client, *_ = env
    d = client.get("/v1/campaigns/presets").json()
    keys = [p["key"] for p in d["presets"]]
    assert keys == ["preview", "gifting", "bespoke", "courier", "between", "newseason"]
    for p in d["presets"]:
        assert p["starts"] <= p["ends"] and p["template"] and "Black Friday" not in p["name"]
    assert d["presets"][-1]["starts"] > d["presets"][0]["ends"]


def test_capture_followup_puts_the_client_on_the_pipeline(env):
    client, store, seat_tok, seat, mp = env
    class Sink:
        def __init__(self): self.meta, self.tags = {}, {}
        def get_metafield(self, cid, key): return self.meta.get((cid, key))
        def set_metafield(self, cid, key, value): self.meta[(cid, key)] = value
        def tag_customer(self, cid, tags): self.tags.setdefault(cid, set()).update(tags)
        def untag_customer(self, cid, tags): self.tags.setdefault(cid, set()).difference_update(tags)
    sink = Sink()
    mp.setattr(board, "_sink", lambda shop: sink)
    written = {}
    mp.setattr(board, "_write_soft", lambda s_, cid, pipe: written.update({cid: pipe}) or None)
    r = client.post("/v1/capture/followup", json={"customer_id": "gid://shopify/Customer/77",
                                                  "note": "Tried the camel coat, 38"},
                    headers={"X-Halia-Ext-Token": seat_tok})
    assert r.status_code == 200 and r.json()["stage"] == "To reach out"
    pipe = written["77"]
    assert pipe["stage"] == "To reach out"
    act = pipe["activity"][-1]
    assert act["actor_id"] == seat and act["actor_name"] == "Sarah Bloom" and "camel coat" in act["note"]
    assert any("reach" in t.lower() for t in sink.tags["77"])


def test_suggested_templates_follow_the_client(env):
    client, store, seat_tok, seat, mp = env
    from halia.api.extension import _suggest_templates, _templates
    tpls = _templates(SHOP, "Grace")
    names = _suggest_templates(SHOP, {"found": True, "cid": "c1", "play": "sleeping", "grade": "A*",
                                      "ordersCount": 4, "cart": {"count": 2}}, tpls)
    assert len(names) == 3
    assert any("aside" in n.lower() for n in names)            # the open basket
    assert any("win" in n.lower() or "missed" in n.lower() for n in names)   # gone quiet
    fresh = _suggest_templates(SHOP, {"found": False}, tpls)
    assert fresh and "welcome" in fresh[0].lower()
    # a birthday within the week outranks everything
    from datetime import timedelta
    soon = date.today() + timedelta(days=2)
    bd.invalidate(SHOP)
    mp.setattr(bd, "fetch_birthdays", lambda shop: [{"cid": "c1", "name": "Grace", "month": soon.month, "day": soon.day, "source": "captured"}])
    first = _suggest_templates(SHOP, {"found": True, "cid": "c1", "play": "fresh", "ordersCount": 1}, tpls)[0]
    assert "birthday" in first.lower()          # whichever birthday template the store keeps
    # and the context carries a default set for the no-client panel
    d = client.get("/v1/extension/context", headers={"X-Halia-Ext-Token": seat_tok}).json()
    assert d["suggested"] and len(d["suggested"]) <= 3
