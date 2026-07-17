"""Store Concierge clienteling engine: pure RFM, no wealth, zero-retention."""
import pandas as pd

from halia.storeconcierge.clienteling import clienteling_payload


def _frame():
    return pd.DataFrame([
        {"CUST_ID": 1, "Name": "Ava Reed",   "EMAIL_ADDR": "a@x.com", "Count of CUST_ID": 5,
         "LT Spent": 9000, "Last Shopped": "2026-07-10"},   # active, big spender
        {"CUST_ID": 2, "Name": "Ben Cole",   "EMAIL_ADDR": "b@x.com", "Count of CUST_ID": 4,
         "LT Spent": 6000, "Last Shopped": "2026-01-01"},   # lapsed, repeat -> win-back
        {"CUST_ID": 3, "Name": "Cara Dunn",  "EMAIL_ADDR": "c@x.com", "Count of CUST_ID": 1,
         "LT Spent": 8000, "Last Shopped": "2026-01-01"},   # lapsed, single order but valuable -> win-back
        {"CUST_ID": 4, "Name": "Gus Hale",   "EMAIL_ADDR": "g@x.com", "Count of CUST_ID": 1,
         "LT Spent": 100,  "Last Shopped": "2026-01-01"},   # lapsed, single order, low value -> NOT win-back
    ])


def test_stats_and_status_are_pure_rfm():
    p = clienteling_payload(_frame(), as_of=pd.Timestamp("2026-07-17"))
    s = p["stats"]
    assert s["customers"] == 4
    assert s["active"] == 1 and s["lapsed"] == 3
    assert s["ltv"] == 23100.0
    # ranked by spend, highest first
    assert [c["name"] for c in p["customers"]][:2] == ["Ava Reed", "Cara Dunn"]


def test_winback_is_lapsed_repeat_or_valuable():
    p = clienteling_payload(_frame(), as_of=pd.Timestamp("2026-07-17"))
    names = [c["name"] for c in p["winback"]]
    assert names == ["Cara Dunn", "Ben Cole"]       # valuable (8000) then repeat (6000), by spend
    assert "Gus Hale" not in names                  # lapsed but neither repeat nor valuable
    assert "Ava Reed" not in names                  # active, not gone quiet


def test_no_wealth_or_score_fields_leak():
    p = clienteling_payload(_frame(), as_of=pd.Timestamp("2026-07-17"))
    for c in p["customers"]:
        assert set(c) == {"cid", "name", "email", "orders", "spent", "last", "days", "status"}
        assert "score" not in c and "grade" not in c and "tier" not in c


def test_empty_frame_does_not_crash():
    p = clienteling_payload(pd.DataFrame(), as_of=pd.Timestamp("2026-07-17"))
    assert p["stats"]["customers"] == 0 and p["customers"] == [] and p["winback"] == []


def test_reads_shopify_style_columns_too():
    df = pd.DataFrame([
        {"CUST_ID": 9, "Name": "Eve Gray", "EMAIL_ADDR": "e@x.com",
         "orders_count": 3, "Spent": 1200, "last_order_at": "2026-06-30"},
    ])
    p = clienteling_payload(df, as_of=pd.Timestamp("2026-07-17"))
    assert p["stats"]["customers"] == 1
    assert p["customers"][0]["orders"] == 3 and p["customers"][0]["spent"] == 1200.0
