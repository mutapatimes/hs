"""Campaign monitoring: member selection, window metrics, and store persistence."""
import json

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
