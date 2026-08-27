"""WooCommerce parity: capture, pipeline, board, reports and birthdays all work for a Woo tenant
through customer meta in the merchant's store plus an opaque-id index on Halia's side."""
import json

import pytest
from fastapi.testclient import TestClient

from halia.adapters.woo_sink import WooSink
from halia.api import birthdays as bd
from halia.api import board, onboarding, reports, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

SHOP = "maison-woo"


class FakeWC:
    """Enough of WC REST to exercise the sink: customers with meta_data, search by email."""

    def __init__(self):
        self.customers: dict[str, dict] = {}
        self.next_id = 100
        self.calls = []

    def req(self, method, path, params=None, body=None):
        self.calls.append((method, path, params, body))
        if method == "GET" and path == "customers":
            em = (params or {}).get("email")
            return [c for c in self.customers.values() if em and c["email"] == em]
        if method == "GET" and path.startswith("customers/"):
            return self.customers[path.split("/")[1]]
        if method == "POST" and path == "customers":
            cid = str(self.next_id); self.next_id += 1
            c = {"id": int(cid), "email": body.get("email", ""), "first_name": body.get("first_name", ""),
                 "last_name": body.get("last_name", ""), "billing": body.get("billing", {}),
                 "meta_data": body.get("meta_data", [])}
            self.customers[cid] = c
            return c
        if method == "PUT" and path.startswith("customers/"):
            c = self.customers[path.split("/")[1]]
            for k in ("first_name", "last_name", "email"):
                if body.get(k): c[k] = body[k]
            if body.get("billing"): c["billing"] = {**c.get("billing", {}), **body["billing"]}
            for m in body.get("meta_data") or []:
                c["meta_data"] = [x for x in c["meta_data"] if x["key"] != m["key"]] + [m]
            return c
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "w.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "woocommerce", "Maison Woo", hash_token(tok))
    store.save_woocommerce(SHOP, "https://maison.example", "ck", "cs")
    seat_tok = new_token()
    seat = store.create_seat(SHOP, "Sarah Bloom", hash_token(seat_tok), "sarah@m.com")
    wc = FakeWC()
    sink = WooSink(wc, index_add=lambda k, c: store.woo_index_add(SHOP, k, c),
                   index_remove=lambda k, c: store.woo_index_remove(SHOP, k, c),
                   index_list=lambda k: store.woo_index_list(SHOP, k))
    monkeypatch.setattr(board, "woo_sink", lambda shop: sink)
    monkeypatch.setattr(board, "current_staff_id", lambda request: None)
    cache.clear(); reports._REPORT_CACHE.clear(); bd.invalidate(SHOP)
    cache.set(SHOP, results=[], payload={"data": [], "orders": []}, orders=[])
    yield TestClient(app, cookies={COOKIE: tok}), store, wc, seat_tok, seat
    cache.clear(); reports._REPORT_CACHE.clear(); bd.invalidate(SHOP)


def test_capture_writes_a_woo_customer_with_meta(env):
    client, store, wc, seat_tok, seat = env
    r = client.post("/v1/capture", headers={"X-Halia-Ext-Token": seat_tok}, json={
        "first_name": "Grace", "last_name": "Ladoja", "email": "grace@x.com", "postcode": "sw1a1aa",
        "country": "UK", "birthday": "14 June", "sizes": "IT 38", "channel": "handover",
        "consent": {"email_marketing": True}})
    assert r.status_code == 200 and r.json()["created"] is True
    wid = r.json()["customer_id"]
    c = wc.customers[wid]
    assert c["email"] == "grace@x.com" and c["billing"]["postcode"] == "SW1A 1AA"
    meta = {m["key"]: m["value"] for m in c["meta_data"]}
    assert json.loads(meta["halia_capture"])["seat_id"] == seat
    assert "halia-captured" in json.loads(meta["halia_tags"])
    assert json.loads(meta["halia_preferences"])["birthday"] == "14 June"
    assert store.woo_index_list(SHOP, "captured") == [wid]
    # a second capture of the same email updates, never duplicates
    r2 = client.post("/v1/capture", headers={"X-Halia-Ext-Token": seat_tok},
                     json={"email": "grace@x.com", "phone": "+44 7700 900123"})
    assert r2.json()["created"] is False and r2.json()["customer_id"] == wid and len(wc.customers) == 1


def test_pipeline_board_and_report_on_woo(env):
    client, store, wc, seat_tok, seat = env
    # a guest cid (email) is registered on first pipeline action, then carded
    r = client.post("/v1/board/note", json={"cid": "omar@x.com", "note": "Loved the camel coat", "seat_id": seat})
    assert r.status_code == 200
    r = client.post("/v1/board/move", json={"cid": "omar@x.com", "stage": "Contacted", "seat_id": seat})
    assert r.status_code == 200, r.text
    wid = next(iter(wc.customers))
    board_ = client.get("/v1/board").json()
    assert board_["available"] and len(board_["cards"]) == 1 and board_["cards"][0]["stage"] == "Contacted"
    r = client.post("/v1/board/assign", json={"cid": wid, "assignee_seat": seat, "seat_id": seat})
    assert r.json()["pipeline"]["assignee"]["name"] == "Sarah Bloom"
    # the extension's contact log lands in the same meta, attributed to the seat
    r = client.post("/v1/extension/action", headers={"X-Halia-Ext-Token": seat_tok},
                    json={"action": "contacted", "cid": wid, "reason": "WhatsApp"})
    assert r.status_code == 200, r.text
    reports._REPORT_CACHE.clear()
    rep = client.get("/v1/reports/associates?days=30").json()
    me = next(x for x in rep["seats"] if x["id"] == seat)
    assert rep["available"] and me["contacts"] == 1 and me["owned"] == 1 and me["moves"] == 1


def test_birthdays_from_woo_captures(env):
    client, store, wc, seat_tok, seat = env
    from datetime import date, timedelta
    soon = date.today() + timedelta(days=4)
    client.post("/v1/capture", headers={"X-Halia-Ext-Token": seat_tok},
                json={"first_name": "Grace", "email": "grace@x.com", "birthday": soon.strftime("%d %B")})
    bd.invalidate(SHOP)
    d = client.get("/v1/birthdays?days=14").json()
    assert d["count"] == 1 and d["birthdays"][0]["name"] == "Grace" and d["birthdays"][0]["in_days"] == 4
