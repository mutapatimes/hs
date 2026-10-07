"""The dev-store seeder: sample rows become customer + order payloads; existing emails are skipped;
the demo book is chosen by grade, dated like a live store, and its heroes score as intended."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location("seed", Path("scripts/seed_dev_store.py"))
seed = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed)

NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)


def test_plan_builds_customer_and_backdated_orders():
    rows = [{"Name": "GRACE LAWSON", "EMAIL_ADDR": "Grace@X.com", "PHONE": "+447700900123", "Spent": 3000,
             "Count of CUST_ID": 3, "Last Shopped": "2026-08-01", "LATEST_SHIPPING_ADDRESS1": "1 Mount St",
             "LATEST_SHIPPING_ADDRESS3": "London", "LATEST_SHIPPING_ZIP": "W1K 2AA", "COMPANY_NAME": "Lawson Capital"},
            {"Name": "Nobody", "EMAIL_ADDR": "", "Spent": 10}]
    plans = seed.plan(rows, NOW)
    assert len(plans) == 1
    c, orders = plans[0]["customer"], plans[0]["orders"]
    assert c["firstName"] == "Grace" and c["lastName"] == "Lawson" and c["email"] == "grace@x.com" and c["tags"] == ["halia-sample"]
    assert c["addresses"][0]["zip"] == "W1K 2AA" and c["addresses"][0]["city"] == "London"
    assert c["addresses"][0]["company"] == "Lawson Capital"          # scored, so it travels
    assert [o["processedAt"][:10] for o in orders] == ["2026-08-01", "2026-06-17", "2026-05-03"]
    assert all(o["lineItems"][0]["priceSet"]["shopMoney"]["amount"] == "1000.00" for o in orders)
    assert orders[0]["billingAddress"]["zip"] == "W1K 2AA"           # billing falls back to shipping
    assert orders[0]["lineItems"][0]["title"] == "Sample purchase" and "variantId" not in orders[0]["lineItems"][0]


def test_orders_carry_real_products_when_the_catalogue_exists():
    products = {"Ines cashmere crew": "gid://shopify/ProductVariant/1", "Verity leather tote": "gid://shopify/ProductVariant/2"}
    rows = [{"Name": "Grace Lawson", "EMAIL_ADDR": "grace@x.com", "Spent": 900, "Count of CUST_ID": 2}]
    orders = seed.plan(rows, NOW, products)[0]["orders"]
    assert all(o["lineItems"][0]["variantId"] in products.values() for o in orders)
    assert all(o["lineItems"][0]["title"] in products for o in orders)
    assert seed.plan(rows, NOW, products) == seed.plan(rows, NOW, products)   # stable per client


def test_run_skips_existing_and_creates_the_rest(monkeypatch):
    calls = []
    def transport(query, variables):
        calls.append((query, variables))
        if query.startswith("query"):
            return {"customers": {"nodes": [{"id": "gid://c/1", "numberOfOrders": 1}] if variables["q"] == 'email:"old@x.com"' else []}}
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


def test_a_rejected_phone_is_dropped_not_fatal(monkeypatch):
    creates = []
    def transport(query, variables):
        if query.startswith("query"):
            return {"customers": {"nodes": []}}
        if "customerCreate" in query:
            creates.append(variables["input"])
            if "phone" in variables["input"]:
                return {"customerCreate": {"customer": None, "userErrors": [{"field": ["input", "phone"], "message": "Phone is invalid"}]}}
            return {"customerCreate": {"customer": {"id": "gid://c/9"}, "userErrors": []}}
        return {"orderCreate": {"order": {"id": "gid://o/1"}, "userErrors": []}}
    monkeypatch.setattr("scoring.shopify_fetch._run", lambda t, q, v, r: t(q, v))
    plans = seed.plan([{"Name": "New One", "EMAIL_ADDR": "new@x.com", "PHONE": "+44 7000 000000", "Spent": 500}])
    stats = seed.run(transport, plans, sleep=0, log=lambda *a: None)
    assert stats["customers"] == 1 and stats["errors"] == 0 and len(creates) == 2 and "phone" not in creates[1]


def test_dates_are_shifted_onto_a_live_two_year_window():
    rows = [{"EMAIL_ADDR": "a@x.com", "Last Shopped": "2024-06-01"},
            {"EMAIL_ADDR": "b@x.com", "Last Shopped": "2025-06-01 10:00:00"},
            {"EMAIL_ADDR": "c@x.com", "Last Shopped": "2026-05-22"}]
    out = seed.shift_dates(rows, NOW, recent_days=3, span_days=720)
    assert out[-1]["Last Shopped"] == "2026-08-26" and out[0]["Last Shopped"] == "2024-09-05"
    assert "2024-09-05" < out[1]["Last Shopped"] < "2026-08-26"
    assert rows[0]["Last Shopped"] == "2024-06-01"          # input untouched


def test_emails_lose_their_numeric_suffix_but_signal_domains_stay():
    rows = [{"EMAIL_ADDR": "iris.larchmont1589@gmail.com"}, {"EMAIL_ADDR": "iris.larchmont@gmail.com"},
            {"EMAIL_ADDR": "aisha.sutherland26691@gmail.com"}, {"EMAIL_ADDR": "imogen.castellane@jpmorgan.com"}]
    out = [r["EMAIL_ADDR"] for r in seed.polish_emails(rows)]
    assert out[0] == "iris.larchmont1589@gmail.com"          # the bare address is taken by row 2
    assert out[2].startswith("aisha.sutherland@") and out[2].split("@")[1] in seed.PLAIN_DOMAINS
    assert out[3] == "imogen.castellane@jpmorgan.com"
    assert len(set(out)) == 4


def test_mix_is_chosen_by_the_grade_the_engine_gives(tmp_path):
    heroes = seed.load_heroes("scripts/demo_heroes.json", NOW)
    plain = [{"Name": f"Person {i}", "EMAIL_ADDR": f"person.{i}@gmail.com", "Spent": 300 + i, "Count of CUST_ID": 1,
              "Last Shopped": "2026-01-01", "LATEST_BILLING_ADDRESS1": "5 Example Road", "LATEST_BILLING_ADDRESS3": "Leeds",
              "LATEST_BILLING_ADDRESS4": "United Kingdom", "LATEST_BILLING_ZIP": "LS8 2HJ"} for i in range(6)]
    plain[0]["Spent"] = 9000                                   # one proven VIC
    df = pd.DataFrame(heroes + plain); df["CUST_ID"] = [str(i) for i in range(len(df))]
    cache = tmp_path / "tiers.csv"
    picked = seed.select_mix(df, {"A1": 1, "A": 1, "B": 2, "none": 4}, cache=cache, log=lambda *a: None)
    names = set(picked["Name"])
    assert "Lady Ottoline Ferrers-Vane" in names and "Imogen Castellane" in names
    assert {"Rafael Okonkwo-Hale", "Theo Lindqvist"} <= names
    assert "Person 0" in names                                 # the big spender rides in the none bucket
    assert len(picked) == 8 and cache.exists()
    again = seed.select_mix(df, {"A1": 1, "A": 1, "B": 2, "none": 4}, cache=cache, log=lambda *a: None)
    assert list(again["Name"]) == list(picked["Name"])         # cached and deterministic


def test_heroes_score_as_their_stories_say():
    from scoring.combine import score_customers
    rows = seed.load_heroes("scripts/demo_heroes.json", NOW)
    df = pd.DataFrame(rows); df["CUST_ID"] = range(len(df))
    tiers, surfaced = seed.grade_series(score_customers(df))
    got = dict(zip(df["Name"], zip(tiers, surfaced)))
    assert got["Lady Ottoline Ferrers-Vane"] == ("A1", True)
    assert got["Imogen Castellane"] == ("A", True)
    assert got["Rafael Okonkwo-Hale"] == ("B", True)
    assert got["Celeste Marchetti"][1] is False                # proven: spend above the threshold
    assert got["Theo Lindqvist"] == ("B", True)
    assert all("days_ago" not in r for r in rows) and rows[1]["Last Shopped"] == "2025-06-25"


def test_catalogue_is_twelve_priced_products_with_public_images():
    pp = seed.product_payloads()
    assert len(pp) == 12 and len({p["product"]["title"] for p in pp}) == 12
    assert all(p["media"][0]["originalSource"].startswith("https://haliascore.com/img/") for p in pp)
    assert all(p["product"]["tags"] == ["halia-sample"] and p["product"]["status"] == "ACTIVE" for p in pp)
    assert all(float(p["price"]) >= 150 for p in pp)
    for _t, _k, _p, image, _c in seed.PRODUCTS:
        assert (Path("web/site/img") / image).exists(), image


def test_wipe_deletes_orders_before_customers(monkeypatch):
    seen = []
    state = {"orders": [{"id": "gid://o/1"}], "customers": [{"id": "gid://c/1"}], "products": []}
    def transport(query, variables):
        for key in ("orders", "customers", "products"):
            if query.lstrip().startswith("query") and f"{key}(first" in query:
                return {key: {"nodes": list(state[key])}}
        name = query.split("{")[1].split("(")[0].strip()
        seen.append(name)
        key = {"orderDelete": "orders", "customerDelete": "customers", "productDelete": "products"}[name]
        state[key] = []
        return {name: {"userErrors": []}}
    monkeypatch.setattr("scoring.shopify_fetch._run", lambda t, q, v, r: t(q, v))
    stats = seed.wipe(transport, sleep=0, log=lambda *a: None)
    assert seen == ["orderDelete", "customerDelete"] and stats["orders"] == 1 and stats["customers"] == 1


def test_a_customer_left_without_orders_gets_them_on_the_rerun(monkeypatch):
    made = []
    def transport(query, variables):
        if query.startswith("query"):
            return {"customers": {"nodes": [{"id": "gid://c/5", "numberOfOrders": 0}]}}
        if "orderCreate" in query:
            made.append(variables["order"]["customerId"])
            return {"orderCreate": {"order": {"id": "gid://o/1"}, "userErrors": []}}
        raise AssertionError("must not create the customer twice")
    monkeypatch.setattr("scoring.shopify_fetch._run", lambda t, q, v, r: t(q, v))
    plans = seed.plan([{"Name": "Half Done", "EMAIL_ADDR": "half@x.com", "Spent": 600, "Count of CUST_ID": 2}])
    stats = seed.run(transport, plans, sleep=0, log=lambda *a: None)
    assert made == ["gid://c/5", "gid://c/5"] and stats["orders"] == 2 and stats["customers"] == 0


def test_stops_early_when_shopify_denies_customer_data(monkeypatch):
    calls = []
    def transport(query, variables):
        calls.append(query)
        raise RuntimeError("This app is not approved to access the Customer object. See protected-customer-data")
    monkeypatch.setattr("scoring.shopify_fetch._run", lambda t, q, v, r: t(q, v))
    rows = [{"Name": f"P {i}", "EMAIL_ADDR": f"p{i}@x.com", "Spent": 100} for i in range(20)]
    lines = []
    seed.run(transport, seed.plan(rows), sleep=0, log=lines.append)
    assert len(calls) == 3 and "Protected customer data" in lines[-1]
