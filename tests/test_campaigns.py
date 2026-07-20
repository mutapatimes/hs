"""Campaign monitoring: member selection, window metrics, store persistence, and the API."""
import json

import pytest
from fastapi.testclient import TestClient

from halia.api import shopify_auth
from halia.api.app import app
from halia.api.shopify_auth import require_shop
from halia.campaigns import campaign_metrics, select_members
from halia.store import ShopStore


def _clients():
    return [
        {"cid": "1", "name": "Ava", "tier": "A1", "aov": 0,
         "signals": [{"seg": "work-email", "d": "Work email: Jane Street"}],
         "orders": [{"date": "2025-03-05", "amount": 100}, {"date": "2025-06-10", "amount": 999}]},  # 999 out of window
        {"cid": "2", "name": "Ben", "tier": "B",
         "signals": [{"seg": "companies-house", "d": "Companies House: X"}],
         "orders": [{"date": "2025-03-12", "amount": 50}]},
        {"cid": "3", "name": "Cara", "tier": "C",
         "signals": [{"seg": "landline", "d": "Landline: yes"}],
         "orders": [{"date": "2025-03-12", "amount": 9999}]},  # not targeted -> excluded
    ]


CAMPAIGN = {"name": "Spring", "starts": "2025-03-01", "ends": "2025-05-31",
            "config": {"tiers": ["A1"], "signals": ["companies-house"]}}


def test_member_selection_union_of_tier_signal_and_explicit_ids():
    m = {c["cid"] for c in select_members(CAMPAIGN, _clients())}
    assert m == {"1", "2"}                       # A1 tier + companies-house signal; Cara excluded
    # an explicit hand-picked id pulls someone in regardless of rule
    camp2 = {**CAMPAIGN, "config": {"tiers": [], "signals": [], "members": ["3"]}}
    assert {c["cid"] for c in select_members(camp2, _clients())} == {"3"}


def test_metrics_respect_the_window_and_break_down_by_signal_and_grade():
    r = campaign_metrics(CAMPAIGN, _clients())
    k = r["kpis"]
    assert k["members"] == 2
    assert k["revenue"] == 150.0          # Ava's 100 (in window) + Ben's 50; Ava's 999 is out of window
    assert k["orders"] == 2 and k["buyers"] == 2 and k["conversion"] == 1.0
    assert k["aov"] == 75.0
    assert sum(p["value"] for p in r["series"]) == 150.0
    by_seg = {b["seg"]: b["value"] for b in r["by_signal"]}
    assert by_seg["work-email"] == 100.0 and by_seg["companies-house"] == 50.0
    by_tier = {b["tier"]: b["value"] for b in r["by_tier"]}
    assert by_tier["A1"] == 100.0 and by_tier["B"] == 50.0
    assert r["top"][0]["name"] == "Ava" and r["top"][0]["revenue"] == 100.0


def test_reactivation_counts_gone_quiet_clients_who_bought_in_window():
    clients = [
        # gone quiet (last order 2024-10, >90d before 2025-03-01) then bought in window -> reactivated
        {"cid": "1", "name": "Quiet Returner", "tier": "A1", "signals": [{"seg": "work-email", "d": "Work email: X"}],
         "orders": [{"date": "2024-10-01", "amount": 500}, {"date": "2025-03-20", "amount": 800}]},
        # active already (last order 2025-02-20, <90d before start) then bought in window -> NOT reactivation
        {"cid": "2", "name": "Loyal", "tier": "A1", "signals": [{"seg": "work-email", "d": "Work email: Y"}],
         "orders": [{"date": "2025-02-20", "amount": 300}, {"date": "2025-03-25", "amount": 300}]},
        # brand new (no prior order) -> NOT a reactivation
        {"cid": "3", "name": "New", "tier": "A1", "signals": [{"seg": "work-email", "d": "Work email: Z"}],
         "orders": [{"date": "2025-04-01", "amount": 900}]},
    ]
    camp = {"name": "W", "starts": "2025-03-01", "ends": "2025-05-31", "config": {"tiers": ["A1"]}}
    k = campaign_metrics(camp, clients)["kpis"]
    assert k["reactivated"] == 1
    assert k["reactivated_revenue"] == 800.0
    assert k["buyers"] == 3


def test_store_crud(tmp_path):
    s = ShopStore(db_path=tmp_path / "t.db")
    cfg = json.dumps({"tiers": ["A1"], "signals": ["work-email"], "members": []})
    s.save_campaign("camp1", "shopx", "Spring", "2025-03-01", "2025-05-31", cfg)
    got = s.get_campaign("camp1", "shopx")
    assert got and got["name"] == "Spring" and got["starts"] == "2025-03-01"
    assert json.loads(got["config_json"])["tiers"] == ["A1"]
    assert [c["id"] for c in s.list_campaigns("shopx")] == ["camp1"]
    # tenant isolation: another shop can't read it
    assert s.get_campaign("camp1", "other") is None
    s.delete_campaign("camp1", "shopx")
    assert s.list_campaigns("shopx") == []


@pytest.fixture()
def api(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "c.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    app.dependency_overrides[require_shop] = lambda: "shopx"
    yield TestClient(app), store
    app.dependency_overrides.pop(require_shop, None)


def test_api_create_list_monitor_delete(api):
    from halia.cache import cache
    c, _ = api
    r = c.post("/v1/campaigns", json={"name": "Spring", "starts": "2025-03-01", "ends": "2025-05-31",
                                      "config": {"tiers": ["a1"], "signals": ["work-email"]}})
    assert r.status_code == 200 and r.json()["ok"]
    cid = r.json()["id"]
    lst = c.get("/v1/campaigns").json()["campaigns"]
    assert len(lst) == 1 and lst[0]["name"] == "Spring"
    assert lst[0]["config"]["tiers"] == ["A1"]                       # normalised to upper-case

    cache.set("shopx", [], {"data": [{"cid": "1", "name": "Ava", "tier": "A1",
              "signals": [{"seg": "work-email", "d": "Work email: X"}],
              "orders": [{"date": "2025-03-10", "amount": 250}]}]}, {})
    try:
        m = c.get(f"/v1/campaigns/{cid}/monitor")
        assert m.status_code == 200 and "Spring" in m.text and "revenue in window" in m.text
        assert "£250" in m.text
        assert "Save as PDF" in m.text        # the print-to-PDF control is present
    finally:
        cache.evict("shopx")

    assert c.post("/v1/campaigns", json={"name": "", "starts": "2025-03-01", "ends": "2025-05-31"}).status_code == 400
    assert c.post("/v1/campaigns", json={"name": "X", "starts": "2025-05-01", "ends": "2025-03-01"}).status_code == 400

    c.delete(f"/v1/campaigns/{cid}")
    assert c.get("/v1/campaigns").json()["campaigns"] == []


def test_api_add_and_remove_member(api):
    c, _ = api
    cid = c.post("/v1/campaigns", json={"name": "W", "starts": "2025-03-01", "ends": "2025-05-31",
                                        "config": {}}).json()["id"]
    r = c.post(f"/v1/campaigns/{cid}/members", json={"cid": "cust_9"})
    assert r.status_code == 200 and r.json()["in"] is True and r.json()["count"] == 1
    # idempotent add (no duplicate)
    c.post(f"/v1/campaigns/{cid}/members", json={"cid": "cust_9"})
    got = c.get("/v1/campaigns").json()["campaigns"][0]
    assert got["config"]["members"] == ["cust_9"]
    # remove
    r2 = c.post(f"/v1/campaigns/{cid}/members", json={"cid": "cust_9", "remove": True})
    assert r2.json()["in"] is False and r2.json()["count"] == 0
    assert c.get("/v1/campaigns").json()["campaigns"][0]["config"]["members"] == []


def test_bulk_members_and_edit_preserves_membership(api):
    c, _ = api
    cid = c.post("/v1/campaigns", json={"name": "W", "starts": "2025-03-01", "ends": "2025-05-31"}).json()["id"]
    # created without config -> no members
    assert c.get("/v1/campaigns").json()["campaigns"][0]["config"]["members"] == []
    # bulk add several at once (cids list), deduped
    r = c.post(f"/v1/campaigns/{cid}/members", json={"cids": ["a", "b", "b", "c"]})
    assert r.status_code == 200 and r.json()["count"] == 3
    # editing name/dates WITHOUT config must not wipe members
    c.post("/v1/campaigns", json={"id": cid, "name": "W2", "starts": "2025-03-02", "ends": "2025-06-01"})
    got = c.get("/v1/campaigns").json()["campaigns"][0]
    assert got["name"] == "W2" and got["starts"] == "2025-03-02"
    assert sorted(got["config"]["members"]) == ["a", "b", "c"]


def test_create_generates_utm_campaign_from_name(api):
    c, _ = api
    r = c.post("/v1/campaigns", json={"name": "Spring Private Preview",
                                      "starts": "2025-03-01", "ends": "2025-05-31"})
    assert r.json()["utm"]["campaign"] == "spring-private-preview"
    got = c.get("/v1/campaigns").json()["campaigns"][0]
    assert got["config"]["utm"]["campaign"] == "spring-private-preview"


def test_utm_campaign_is_stable_across_rename(api):
    c, _ = api
    cid = c.post("/v1/campaigns", json={"name": "Spring", "starts": "2025-03-01",
                                        "ends": "2025-05-31"}).json()["id"]
    c.post("/v1/campaigns", json={"id": cid, "name": "Autumn", "starts": "2025-03-01",
                                  "ends": "2025-05-31"})            # rename, config omitted
    got = c.get("/v1/campaigns").json()["campaigns"][0]
    assert got["name"] == "Autumn" and got["config"]["utm"]["campaign"] == "spring"


def test_metrics_carries_utm_and_backfills_legacy_campaign(api):
    from halia.cache import cache
    c, store = api
    store.save_campaign("camp_old", "shopx", "Winter Sale", "2025-01-01", "2025-02-01",
                        json.dumps({"tiers": ["A1"], "signals": [], "members": []}))  # no utm
    cache.set("shopx", [], {"data": []}, {})
    try:
        m = c.get("/v1/campaigns/camp_old/metrics").json()
        assert m["utm"]["campaign"] == "winter-sale"
    finally:
        cache.evict("shopx")


def test_api_metrics_json_endpoint(api):
    from halia.cache import cache
    c, _ = api
    cid = c.post("/v1/campaigns", json={"name": "M", "starts": "2025-03-01", "ends": "2025-05-31"}).json()["id"]
    cache.set("shopx", [], {"data": [{"cid": "1", "name": "Ava", "tier": "A1",
              "signals": [{"seg": "work-email", "d": "Work email: X"}],
              "orders": [{"date": "2025-03-10", "amount": 250}]}]}, {})
    try:
        c.post(f"/v1/campaigns/{cid}/members", json={"cids": ["1"]})
        j = c.get(f"/v1/campaigns/{cid}/metrics").json()
        assert j["name"] == "M" and j["kpis"]["members"] == 1 and j["kpis"]["revenue"] == 250.0
        assert "series" in j and "by_signal" in j and "top" in j
    finally:
        cache.evict("shopx")
