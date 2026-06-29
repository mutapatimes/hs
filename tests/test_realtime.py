"""Tests for the real-time single-client grading (the POS-flagging brain)."""
from scoring.realtime import grade_from_orders, grade_record, lookup_and_grade


def test_grade_record_flags_and_recommends_a_gesture():
    # A prime-postcode client -> a signal fires -> graded + given a POS gesture.
    res = grade_record({"Name": "A. Client", "Spent": 400, "LATEST_BILLING_ZIP": "SW1X 7XL"})
    assert res["matched"] and res["flagged"]
    assert res["tier"] in ("A1", "A", "B", "C")
    assert res["is_priority"] is (res["tier"] in ("A1", "A"))
    assert res["gesture"]                       # an associate prompt is present
    assert "HNWI postcode" in res["reasons"]


def test_grade_record_no_signal_is_not_flagged():
    res = grade_record({"Name": "Jo Bloggs", "Spent": 50, "EMAIL_ADDR": "jo@gmail.com",
                        "LATEST_BILLING_ZIP": "LS1 1AA"})
    assert res["matched"] and not res["flagged"]
    assert res["tier"] is None and res["gesture"] == ""


def test_grade_record_priority_gets_coffee_gesture():
    # Stack independent signals to push into A/A+ and check the gesture wording.
    res = grade_record({
        "Name": "Sir John Smith",                 # honorific (name group)
        "EMAIL_ADDR": "p@a16z.com",               # work email (VC)
        "LATEST_BILLING_ZIP": "SW1X 7XL",         # HNWI postcode
        "Spent": 300,
    })
    assert res["is_priority"]
    assert "coffee" in res["gesture"].lower()


# --- Live POS path (fake Shopify, no creds) ---------------------------------
def _customer_node():
    return {
        "id": "gid://shopify/Customer/55", "email": "vic@bespoke.co", "phone": None,
        "firstName": "Val", "lastName": "Ic", "tags": [], "numberOfOrders": 1,
        "amountSpent": {"amount": "300.00", "currencyCode": "GBP"},
        "orders": {"nodes": [{
            "id": "gid://shopify/Order/9", "createdAt": "2024-05-01T00:00:00Z", "tags": [],
            "totalPriceSet": {"shopMoney": {"amount": "300.00"}},
            "totalDiscountsSet": {"shopMoney": {"amount": "0.00"}},
            "billingAddress": {"address1": "1 St", "address2": None, "city": "London",
                               "country": "United Kingdom", "countryCodeV2": "GB",
                               "zip": "SW1X 7XL", "company": None, "phone": None},
            "shippingAddress": None, "clientDetails": {"browserIp": None},
            "lineItems": {"nodes": [{"quantity": 1}]},
        }]},
    }


def test_lookup_and_grade_live_path_with_fake_transport():
    def transport(query, variables):
        assert variables["q"].startswith("email:")        # POS searches by email
        return {"data": {"customers": {"nodes": [_customer_node()]}}}

    res = lookup_and_grade("vic@bespoke.co", transport=transport)
    assert res["matched"] and res["flagged"]
    assert res["gesture"]


def test_lookup_unknown_walkin_returns_no_match():
    def transport(query, variables):
        return {"data": {"customers": {"nodes": []}}}      # nobody matches

    res = lookup_and_grade("stranger@nowhere.com", transport=transport)
    assert res["matched"] is False and res["flagged"] is False
    assert res["gesture"] == ""


def test_grade_from_orders_empty_is_no_match():
    assert grade_from_orders([])["matched"] is False
