"""The dev-store seeder: sample rows become customer + order payloads; existing emails are skipped."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("seed", Path("scripts/seed_dev_store.py"))
seed = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed)


def test_plan_builds_customer_and_backdated_orders():
    now = datetime(2026, 8, 29, tzinfo=timezone.utc)
    rows = [{"Name": "GRACE LADOJA", "EMAIL_ADDR": "Grace@X.com", "PHONE": "+447700900123", "Spent": 3000,
             "Count of CUST_ID": 3, "Last Shopped": "2026-08-01", "LATEST_SHIPPING_ADDRESS1": "1 Mount St",
             "LATEST_SHIPPING_ADDRESS3": "London", "LATEST_SHIPPING_ZIP": "W1K 2AA"},
            {"Name": "Nobody", "EMAIL_ADDR": "", "Spent": 10}]
    plans = seed.plan(rows, now)
    assert len(plans) == 1
    c, orders = plans[0]["customer"], plans[0]["orders"]
    assert c["firstName"] == "Grace" and c["lastName"] == "Ladoja" and c["email"] == "grace@x.com" and c["tags"] == ["halia-sample"]
    assert c["addresses"][0]["zip"] == "W1K 2AA" and c["addresses"][0]["city"] == "London"
    assert [o["processedAt"][:10] for o in orders] == ["2026-08-01", "2026-06-17", "2026-05-03"]
    assert all(o["lineItems"][0]["priceSet"]["shopMoney"]["amount"] == "1000.00" for o in orders)


def test_run_skips_existing_and_creates_the_rest(monkeypatch):
    calls = []
    def transport(query, variables):
        calls.append((query, variables))
        if query.startswith("query"):
            return {"customers": {"nodes": [{"id": "gid://c/1"}] if variables["q"] == 'email:"old@x.com"' else []}}
        if "customerCreate" in query:
            return {"customerCreate": {"customer": {"id": "gid://c/9"}, "userErrors": []}}
        return {"orderCreate": {"order": {"id": "gid://o/1", "name": "#1"}, "userErrors": []}}
    monkeypatch.setattr("scoring.shopify_fetch._run", lambda t, q, v, r: t(q, v))
    plans = seed.plan([{"Name": "Old One", "EMAIL_ADDR": "old@x.com", "Spent": 100},
                       {"Name": "New One", "EMAIL_ADDR": "new@x.com", "Spent": 500, "Count of CUST_ID": 2}])
    stats = seed.run(transport, plans, sleep=0, log=lambda *a: None)
    assert stats == {"customers": 1, "skipped": 1, "orders": 2, "errors": 0}
    order_calls = [v for q, v in calls if "orderCreate" in q]
    assert order_calls[0]["order"]["customerId"] == "gid://c/9" and order_calls[0]["options"]["sendReceipt"] is False
