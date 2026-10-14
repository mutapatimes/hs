"""Store or online client: facts per client, label by the house rule."""
from halia import channels
from halia.api.data import _history
from scoring.shopify_graphql import order_node_to_rest


def _rows(*orders):
    """(date, channel, amount) newest first, as _history emits them."""
    return [{"date": d, "ch": ch, "amount": a} for d, ch, a in orders]


def test_channel_of_reads_shopifys_source():
    assert channels.channel_of({"source_name": "pos"}) == "store"
    assert channels.channel_of({"source_name": "shopify_draft_order"}) == "store"
    assert channels.channel_of({"source_name": "web"}) == "online"
    assert channels.channel_of({"source_name": "580111"}) == "online"     # another sales channel
    assert channels.channel_of({}) is None                                 # other platforms


def test_the_dsm_case_first_in_store_most_spend_online():
    # £100 in store, first; £6,000 online since.
    s = channels.summary(_rows(("2026-09-01", "online", 4000), ("2026-05-01", "online", 2000),
                               ("2025-01-10", "store", 100)))
    assert s["first"] == "store" and s["last"] == "online"
    assert s["storeSpend"] == 100 and s["onlineSpend"] == 6000 and s["storeShare"] == 2
    assert channels.label(s, "first") == "store"
    assert channels.label(s, "spend") == "online"
    assert channels.label(s, "recent") == "online"


def test_both_when_each_channel_carries_its_share():
    s = channels.summary(_rows(("2026-09-01", "online", 600), ("2026-01-01", "store", 400)))
    assert channels.label(s, "first", both=25) == "both"
    assert channels.label(s, "first", both=45) == "store"       # 40% in store is under 45%
    assert channels.label(s, "first", both=0) == "store"        # 0 turns "both" off


def test_one_channel_only_is_never_both():
    s = channels.summary(_rows(("2026-09-01", "store", 900), ("2026-01-01", "store", 300)))
    assert s["storeShare"] == 100 and channels.label(s, "spend") == "store"


def test_no_channel_facts_without_a_source():
    assert channels.summary([{"date": "2026-01-01", "amount": 50}]) is None
    assert channels.label(None) is None


def test_store_and_associate_come_through_from_shopify():
    node = {"id": "gid://shopify/Order/1", "createdAt": "2026-10-01T10:00:00Z", "sourceName": "pos",
            "retailLocation": {"name": "Dover Street"}, "staffMember": {"name": "Amara Okafor"},
            "totalPriceSet": {"shopMoney": {"amount": "250.00"}}, "lineItems": {"nodes": []}}
    cust = {"id": "gid://shopify/Customer/9", "email": "a@x.com"}
    rest = order_node_to_rest(node, cust)
    assert rest["source_name"] == "pos" and rest["location_name"] == "Dover Street"
    rows = _history([rest])["gid://shopify/Customer/9"]
    assert rows[0]["ch"] == "store" and rows[0]["loc"] == "Dover Street" and rows[0]["staff"] == "Amara Okafor"
    s = channels.summary(rows)
    assert s["store"] == "Dover Street" and s["associate"] == "Amara Okafor"


def test_rules_and_shares_are_cleaned():
    assert channels.clean_rule("SPEND") == "spend" and channels.clean_rule("nonsense") == "first"
    assert channels.clean_both("80") == 50 and channels.clean_both("-3") == 0 and channels.clean_both("x") == 25


def test_fetch_drops_store_fields_when_shopify_refuses_them():
    from scoring import shopify_fetch
    from scoring.shopify_fetch import ShopifyError, fetch_customer_nodes
    seen = []
    def transport(query, variables):
        seen.append("retailLocation" in query)
        if "retailLocation" in query:
            return {"errors": [{"message": "Access denied for staffMember field.", "extensions": {"code": "ACCESS_DENIED"}}]}
        return {"data": {"customers": {"nodes": [{"id": "c1"}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
    nodes = list(fetch_customer_nodes(transport, retries=1, _sleep=lambda s: None))
    assert nodes == [{"id": "c1"}] and seen[0] is True and seen[-1] is False


def test_house_rule_saves_and_reads_back(monkeypatch, tmp_path):
    import json
    from fastapi.testclient import TestClient
    from halia.api import shopify_auth
    from halia.api.app import app
    from halia.api.roles import require_manager
    from halia.api.settings import settings_for
    from halia.store import ShopStore
    store = ShopStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    app.dependency_overrides[require_manager] = lambda: "shopx"
    try:
        c = TestClient(app)
        assert settings_for("shopx")["channel_rule"] == "first" and settings_for("shopx")["channel_both"] == 25
        r = c.post("/v1/settings", json={"vic_threshold": 5000, "channel_rule": "spend", "channel_both": 30})
        assert r.status_code == 200
        assert settings_for("shopx")["channel_rule"] == "spend" and settings_for("shopx")["channel_both"] == 30
        # a save from a screen that does not send the rule keeps it
        c.post("/v1/settings", json={"vic_threshold": 6000})
        assert settings_for("shopx")["channel_rule"] == "spend"
    finally:
        app.dependency_overrides.pop(require_manager, None)
