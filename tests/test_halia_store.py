"""ScoreStore: shop-scoped upsert, lookups, order join, and tenant isolation."""
from halia.schema import ScoreResult
from halia.store import ScoreStore, ShopStore

SHOP = "acme.myshopify.com"
OTHER = "rival.myshopify.com"


def _result(cid, grade, tier, score, hidden=True, email=None):
    return ScoreResult(
        matched=True, flagged=True, tier=tier, grade=grade, score=score,
        is_priority=tier in ("A1", "A"), signal_count=2, signals=["Work email"],
        reasons="Work email: GS", gesture="coffee", spend=400.0, hidden_vic=hidden,
        customer_id=cid, email=email or f"{cid}@x.com", phone=None,
    )


def _store(tmp_path):
    return ScoreStore(db_path=tmp_path / "t.db")


def test_upsert_and_get(tmp_path):
    s = _store(tmp_path)
    assert s.upsert_many([_result("c1", "A*", "A1", 99)], shop=SHOP) == 1
    got = s.get_by_customer_id(SHOP, "c1")
    assert got.grade == "A*" and got.is_priority and got.signals == ["Work email"]
    assert s.get_by_email(SHOP, "c1@x.com").customer_id == "c1"


def test_upsert_is_idempotent_update(tmp_path):
    s = _store(tmp_path)
    s.upsert_many([_result("c1", "C", "C", 60)], shop=SHOP)
    s.upsert_many([_result("c1", "A", "A", 80)], shop=SHOP)
    assert s.count(SHOP) == 1 and s.get_by_customer_id(SHOP, "c1").grade == "A"


def test_tenant_isolation(tmp_path):
    s = _store(tmp_path)
    s.upsert_many([_result("c1", "A*", "A1", 99)], shop=SHOP)
    s.upsert_many([_result("c1", "B", "B", 70)], shop=OTHER)  # same id, different shop
    assert s.get_by_customer_id(SHOP, "c1").grade == "A*"
    assert s.get_by_customer_id(OTHER, "c1").grade == "B"
    assert s.count(SHOP) == 1 and s.count(OTHER) == 1
    assert [r.customer_id for r in s.top_hidden(OTHER, 10)] == ["c1"]


def test_top_hidden_ranks_by_score(tmp_path):
    s = _store(tmp_path)
    s.upsert_many(
        [_result("c1", "B", "B", 70), _result("c2", "A*", "A1", 99),
         _result("c3", "A", "A", 80, hidden=False)],
        shop=SHOP)
    assert [r.customer_id for r in s.top_hidden(SHOP, 10)] == ["c2", "c1"]  # c3 not hidden


def test_order_join_and_priority_ordering(tmp_path):
    s = _store(tmp_path)
    s.upsert_many([_result("c1", "C", "C", 60), _result("c2", "A*", "A1", 99)], shop=SHOP)
    s.upsert_orders([
        {"order_id": "o1", "customer_id": "c1", "email": None, "created_at": "2026-06-01"},
        {"order_id": "o2", "customer_id": "c2", "email": None, "created_at": "2026-06-02"},
        {"order_id": "o3", "customer_id": "unknown", "email": None, "created_at": "2026-06-03"},
    ], shop=SHOP)
    assert s.score_for_order(SHOP, "o2").grade == "A*"
    assert s.score_for_order(SHOP, "o3") is None
    recent = s.recent_orders(SHOP, 10)
    assert recent[0]["order_id"] == "o2"
    assert recent[-1]["result"] is None


def test_shop_store_token_roundtrip(tmp_path):
    ss = ShopStore(db_path=tmp_path / "t.db")
    assert ss.get_token(SHOP) is None
    ss.save_shop(SHOP, "shpat_offline_123")
    assert ss.get_token(SHOP) == "shpat_offline_123"
    ss.save_shop(SHOP, "shpat_rotated")  # upsert
    assert ss.get_token(SHOP) == "shpat_rotated"
