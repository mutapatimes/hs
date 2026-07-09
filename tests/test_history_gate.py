"""Paid full-history gate: un-upgraded tenants only see the last 30 days of clients/orders."""
import datetime as dt

from build_mvp import cap_payload_recent, render_payload


def _payload():
    now = dt.datetime.now(dt.timezone.utc)
    recent = int((now - dt.timedelta(days=5)).timestamp())
    old = int((now - dt.timedelta(days=90)).timestamp())
    rd = (now - dt.timedelta(days=5)).strftime("%Y-%m-%d")
    od = (now - dt.timedelta(days=90)).strftime("%Y-%m-%d")
    return {
        "segments": {}, "data": [
            {"lastSort": recent, "latent": 100, "spend": 50, "grade": "A*"},
            {"lastSort": old, "latent": 999, "spend": 500, "grade": "A"},
        ],
        "orders": [{"date": rd}, {"date": od}],
        "stat_scored": "2", "stat_latent": "£1,099", "stat_count": "2",
        "stat_avgspend": "£275", "stat_toptier": "2", "full_history": True,
    }


def test_cap_keeps_only_recent_and_recomputes_stats():
    capped = cap_payload_recent(_payload(), 30)
    assert len(capped["data"]) == 1 and capped["data"][0]["grade"] == "A*"   # 90-day-old client dropped
    assert len(capped["orders"]) == 1                                        # 90-day-old order dropped
    assert capped["full_history"] is False and capped["history_days"] == 30
    assert capped["stat_count"] == "1" and capped["stat_toptier"] == "1"     # recomputed from the capped set


def test_render_injects_full_history_flag():
    assert "const FULL_HISTORY = true" in render_payload(_payload())
    assert "const FULL_HISTORY = false" in render_payload(cap_payload_recent(_payload(), 30))
