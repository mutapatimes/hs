"""Tests for the Shopify order-flattener, using the real order resource shape."""
import pandas as pd

from scoring.combine import score_customers
from scoring.shopify import flatten_order, orders_to_customers

# Trimmed version of the Shopify order resource the user supplied.
SAMPLE_ORDER = {
    "id": 450789469,
    "email": "bob.norman@mail.example.com",
    "phone": "+557734881234",
    "browser_ip": "216.191.105.146",
    "created_at": "2008-01-10T11:00:00-05:00",
    "total_price": "409.94",
    "tags": "imported, vip",
    "customer": {"id": 207119551, "email": "bob.norman@mail.example.com",
                 "first_name": "Bob", "last_name": "Norman", "phone": "+13125551212",
                 "tags": "loyal"},
    "billing_address": {"address1": "2259 Park Ct", "address2": "Apartment 5",
                        "city": "Drayton Valley", "country": "Canada", "zip": "T0E 0M0",
                        "company": None, "phone": "(555)555-5555"},
    "shipping_address": {"address1": "123 Amoebobacterieae St", "address2": "",
                         "city": "Ottawa", "country": "Canada", "zip": "K2P0V6"},
    "line_items": [{"quantity": 1}, {"quantity": 2}],
    "client_details": {"browser_ip": "216.191.105.146"},
}

SAMPLE_TXNS = [{"payment_details": {"credit_card_bin": "453201",
                                    "credit_card_company": "Visa"}}]


def test_flatten_single_order():
    row = flatten_order(SAMPLE_ORDER, SAMPLE_TXNS)
    assert row["Name"] == "Bob Norman"
    assert row["EMAIL_ADDR"] == "bob.norman@mail.example.com"
    assert row["PHONE"] == "+13125551212"            # customer phone preferred
    assert row["Spent"] == 409.94
    assert row["Items"] == 3                          # 1 + 2
    assert row["LATEST_BILLING_ZIP"] == "T0E 0M0"
    assert row["LATEST_SHIPPING_ADDRESS3"] == "Ottawa"
    assert row["browser_ip"] == "216.191.105.146"
    assert row["credit_card_bin"] == "453201"
    assert row["tags"] == {"imported", "vip", "loyal"}


def test_order_note_and_attributes_carried_through():
    order = {**SAMPLE_ORDER, "note": "On behalf of Mr Rothschild",
             "note_attributes": [{"name": "Gift message", "value": "Leave with the housekeeper"}]}
    row = flatten_order(order)
    assert "On behalf of Mr Rothschild" in row["ORDER_NOTE"]
    assert "housekeeper" in row["ORDER_NOTE"]
    # A note on ANY of a customer's orders survives aggregation (not just the latest).
    plain = {**SAMPLE_ORDER, "created_at": "2009-01-01T00:00:00Z"}   # newer, no note
    cust = orders_to_customers([order, plain])
    assert "Rothschild" in cust.iloc[0]["ORDER_NOTE"]


def test_no_note_leaves_column_empty():
    cust = orders_to_customers([SAMPLE_ORDER])
    assert pd.isna(cust.iloc[0]["ORDER_NOTE"]) or cust.iloc[0]["ORDER_NOTE"] is None


def test_aggregate_two_orders_one_customer():
    older = {**SAMPLE_ORDER, "total_price": "100.00", "created_at": "2007-01-01T00:00:00Z",
             "line_items": [{"quantity": 1}], "tags": ""}
    newer = SAMPLE_ORDER
    cust = orders_to_customers([older, newer])
    assert len(cust) == 1
    assert cust.iloc[0]["Spent"] == 509.94            # 100 + 409.94
    assert cust.iloc[0]["Items"] == 4                 # 1 + 3
    assert cust.iloc[0]["LATEST_BILLING_ADDRESS3"] == "Drayton Valley"  # from newer order
    assert cust.iloc[0]["SEGMENT"] == "VIP"           # 'vip' tag on the newer order


def test_flattened_frame_runs_through_the_engine():
    cust = orders_to_customers([SAMPLE_ORDER])
    scored = score_customers(cust)            # must not raise; all signal cols exist
    assert scored.iloc[0]["SEGMENT"] == "VIP"   # tag still surfaced for display
    assert "signal_score" in scored.columns


def test_behavioural_features():
    today = pd.Timestamp("2008-07-01T00:00:00Z")
    o1 = {**SAMPLE_ORDER, "id": 1, "created_at": "2008-01-10T00:00:00Z",
          "total_price": "400.00", "total_discounts": "0.00",
          "shipping_address": {"address1": "A St", "zip": "AA1"}}
    o2 = {**SAMPLE_ORDER, "id": 2, "created_at": "2008-02-10T00:00:00Z",
          "total_price": "100.00", "total_discounts": "20.00",
          "shipping_address": {"address1": "B St", "zip": "BB2"}}
    r = orders_to_customers([o1, o2], today=today).iloc[0]
    assert r["orders_count"] == 2
    assert r["avg_order_value"] == 250.0
    assert r["full_price_ratio"] == 0.5             # one of two orders discounted
    assert r["distinct_shipping_addresses"] == 2
    assert r["tenure_days"] == 31                   # 10 Jan -> 10 Feb
    assert r["days_since_last_order"] == 142        # 10 Feb -> 1 Jul
    assert not r["single_order_then_silent"]


def test_single_order_then_silent_flag():
    today = pd.Timestamp("2009-01-01T00:00:00Z")
    o = {**SAMPLE_ORDER, "created_at": "2008-01-10T00:00:00Z"}
    r = orders_to_customers([o], today=today).iloc[0]
    assert r["single_order_then_silent"]            # 1 order, ~357 days of silence


def test_empty_orders():
    cust = orders_to_customers([])
    assert cust.empty
