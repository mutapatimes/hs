"""Engine facade: canonical ScoreResult + parity with the POS path."""
from halia.engine import HaliaEngine, score_many, score_one
from scoring import realtime

A_STAR = {
    "CUST_ID": "c-1", "Name": "Sir John Smith", "EMAIL_ADDR": "john@gs.com",
    "LATEST_BILLING_ZIP": "SW1X 7XL", "LATEST_BILLING_ADDRESS4": "United Kingdom",
    "Spent": 400,
}
PLAIN = {"CUST_ID": "c-2", "Name": "Jane Plain", "EMAIL_ADDR": "jane@gmail.com", "Spent": 200}


def test_score_one_grades_and_identifies():
    r = score_one(A_STAR)
    assert r.matched and r.flagged and r.is_priority
    assert r.grade == "A*" and r.tier == "A1"
    assert r.customer_id == "c-1" and r.email == "john@gs.com"
    assert r.hidden_vic is True  # spend 400 < threshold, signal fired
    assert "Work email" in r.signals


def test_unflagged_customer_not_hidden():
    r = score_one(PLAIN)
    assert r.matched and not r.flagged
    assert r.grade == "—" and r.hidden_vic is False


def test_pos_dict_matches_realtime_shim():
    # realtime.grade_record now delegates to the engine — they must agree exactly.
    assert score_one(A_STAR).pos_dict() == realtime.grade_record(A_STAR)


def test_score_many_preserves_order_and_count():
    rs = score_many([A_STAR, PLAIN])
    assert [r.customer_id for r in rs] == ["c-1", "c-2"]
    assert rs[0].is_priority and not rs[1].flagged


def test_threshold_is_configurable():
    # A high threshold makes even a big spender count as hidden when a signal fires.
    rich = {**A_STAR, "Spent": 1_000_000}
    assert HaliaEngine(vic_threshold=50).score_one(rich).hidden_vic is False
    assert HaliaEngine(vic_threshold=2_000_000).score_one(rich).hidden_vic is True
