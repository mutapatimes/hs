#!/usr/bin/env python3
"""Seed a Shopify development store with the sample client book, so the dashboard has something
real to score. Creates each customer (name, email, phone, shipping address) and their orders,
spread back in time from their "Last Shopped" date, all tagged halia-sample.

Needs a token with write_customers AND write_orders on the DEV store: in its admin go to
Settings → Apps and sales channels → Develop apps → create one, grant those scopes, install,
copy the Admin API access token. Halia's own app token deliberately lacks write_orders.

    .venv/bin/python scripts/seed_dev_store.py --shop glen-norah-vmskd33v.myshopify.com \\
        --token shpat_... --source sample_data/sample_two.xlsx --limit 300

Orders are created "now" (Shopify sets created_at itself) with processed_at backdated, so they sit
inside the 60-day window an unapproved app can read. Re-running skips customers already there.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TAG = "halia-sample"

FIND = """query($q: String!) { customers(first: 1, query: $q) { nodes { id email } } }"""
CREATE = """mutation($input: CustomerInput!) {
  customerCreate(input: $input) { customer { id } userErrors { field message } } }"""
ORDER = """mutation($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) { order { id name } userErrors { field message } } }"""


def _s(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def split_name(full: str) -> tuple[str, str]:
    parts = [p for p in _s(full).replace(",", " ").split() if p]
    if not parts:
        return "Sample", "Client"
    if len(parts) == 1:
        return parts[0].title(), ""
    return parts[0].title(), " ".join(parts[1:]).title()


def address(row: dict) -> dict | None:
    a1, a2, a3, a4 = (_s(row.get(f"LATEST_SHIPPING_ADDRESS{i}")) for i in range(1, 5))
    zip_ = _s(row.get("LATEST_SHIPPING_ZIP")) or (a4 if a4 and any(ch.isdigit() for ch in a4) else "")
    if not (a1 or a3 or zip_):
        return None
    out = {"address1": a1 or a2, "city": a3 or a2, "zip": zip_, "country": "United Kingdom"}
    if a2 and a2 != out["address1"]:
        out["address2"] = a2
    return {k: v for k, v in out.items() if v}


def orders_for(row: dict, now: datetime) -> list[tuple[datetime, float]]:
    """(processed_at, amount) per order: the total spend split evenly, the latest on Last Shopped,
    earlier ones every 45 days before it."""
    spent = float(_s(row.get("Spent")) or 0) or 0.0
    n = int(float(_s(row.get("Count of CUST_ID")) or 1) or 1)
    n = max(1, min(n, 12))
    last = _s(row.get("Last Shopped"))
    try:
        when = datetime.fromisoformat(last[:10]).replace(tzinfo=timezone.utc) if last else now
    except ValueError:
        when = now
    when = min(when, now)
    amt = round(spent / n, 2) if spent > 0 else 120.0
    return [(when - timedelta(days=45 * i), amt) for i in range(n)]


def plan(rows: list[dict], now: datetime | None = None) -> list[dict]:
    """The customer + order payloads for each row, with no network."""
    now = now or datetime.now(timezone.utc)
    out = []
    for row in rows:
        email = _s(row.get("EMAIL_ADDR")).lower()
        if "@" not in email:
            continue
        first, last = split_name(row.get("Name") or row.get("FIRST_NAME"))
        cust = {"firstName": first, "lastName": last, "email": email, "tags": [TAG]}
        phone = _s(row.get("PHONE"))
        if phone:
            cust["phone"] = phone
        addr = address(row)
        if addr:
            cust["addresses"] = [{**addr, "firstName": first, "lastName": last}]
        orders = []
        for when, amt in orders_for(row, now):
            o = {"processedAt": when.isoformat(timespec="seconds"),
                 "financialStatus": "PAID", "tags": [TAG], "currency": "GBP",
                 "lineItems": [{"title": "Sample purchase", "quantity": 1,
                                "priceSet": {"shopMoney": {"amount": f"{amt:.2f}", "currencyCode": "GBP"}}}]}
            if addr:
                o["shippingAddress"] = {**addr, "firstName": first, "lastName": last}
            orders.append(o)
        out.append({"customer": cust, "orders": orders})
    return out


def run(transport, plans: list[dict], sleep: float = 0.35, log=print) -> dict:
    from scoring.shopify_fetch import _run
    stats = {"customers": 0, "skipped": 0, "orders": 0, "errors": 0}
    for p in plans:
        email = p["customer"]["email"]
        try:
            found = _run(transport, FIND, {"q": f'email:"{email}"'}, 3)["customers"]["nodes"]
            if found:
                stats["skipped"] += 1
                continue
            d = _run(transport, CREATE, {"input": p["customer"]}, 3)["customerCreate"]
            if d.get("userErrors"):
                stats["errors"] += 1
                log(f"  {email}: {d['userErrors']}")
                continue
            cid = d["customer"]["id"]
            stats["customers"] += 1
            for o in p["orders"]:
                r = _run(transport, ORDER, {"order": {**o, "customerId": cid},
                                            "options": {"inventoryBehaviour": "BYPASS", "sendReceipt": False}}, 3)["orderCreate"]
                if r.get("userErrors"):
                    stats["errors"] += 1
                    log(f"  {email} order: {r['userErrors']}")
                else:
                    stats["orders"] += 1
                time.sleep(sleep)
            log(f"+ {email}: {len(p['orders'])} order(s)")
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            log(f"  {email}: {exc}")
        time.sleep(sleep)
    return stats


def main() -> None:
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default=os.environ.get("SHOPIFY_SHOP"))
    ap.add_argument("--token", default=os.environ.get("SHOPIFY_ADMIN_TOKEN"))
    ap.add_argument("--source", default="sample_data/sample_two.xlsx")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    df = pd.read_excel(a.source)
    rows = df.iloc[a.offset:a.offset + a.limit].to_dict("records")
    plans = plan(rows)
    print(f"{len(plans)} customers, {sum(len(p['orders']) for p in plans)} orders from {a.source}")
    if a.dry_run:
        for p in plans[:5]:
            print(p["customer"]["email"], [o["processedAt"][:10] for o in p["orders"]])
        return
    if not (a.shop and a.token):
        sys.exit("--shop and --token (write_customers + write_orders) are required")
    from scoring.shopify_fetch import http_transport
    stats = run(http_transport(a.shop, a.token), plans)
    print(stats)


if __name__ == "__main__":
    main()
