#!/usr/bin/env python3
"""Seed a Shopify development store with a fictional luxury client book (Maison Aurelle), so the
dashboard has a real, two-year, graded book to score for demos and for app review.

Everything created is synthetic and tagged halia-sample, so it can be wiped with --wipe.

Needs write_customers, write_orders and write_products on the DEV store. Two ways in:

  * Dev Dashboard (current Shopify): create an app manually ("Seeder"), give it those Admin API
    scopes, release it and install it on the dev store. Then run with the app's client id and
    secret (SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET): the seeder swaps them for an access token
    with Shopify's client-credentials grant, which works for an app installed on a store in the
    same organisation.
  * Older admins: Settings → Apps and sales channels → Develop apps → create, grant the scopes,
    install, copy the Admin API access token (SHOPIFY_ADMIN_TOKEN).

Halia's own app token deliberately lacks the write scopes. Credentials live in the shell only
(with SHOPIFY_SHOP); never in the repo.

    # 1. the catalogue (12 products with images, served from haliascore.com/img)
    .venv/bin/python scripts/seed_dev_store.py --products
    # 2. look at the plan without touching the store
    .venv/bin/python scripts/seed_dev_store.py --mix "A1:40,A:80,B:280,none:1100" --dry-run
    # 3. the book: ~1,500 clients + ~2,600 orders, about an hour at Shopify's pace; resumable
    .venv/bin/python scripts/seed_dev_store.py --mix "A1:40,A:80,B:280,none:1100" --heroes scripts/demo_heroes.json
    # start again
    .venv/bin/python scripts/seed_dev_store.py --wipe

--mix picks rows from the synthetic file by the grade the engine gives them, so the book has a
rich top end (a random slice of the file has ~3 A* in 1,500; C never surfaces, so it is not a bucket). The no-signal bucket keeps ~10% big
spenders, so proven VICs sit beside the hidden ones. Dates are shifted so the most recent sale was
a few days ago and the book spans two years; emails lose their numeric suffixes.

Shopify sets an order's createdAt itself; the sale date goes in processedAt, which the engine reads.
Without --mix the old behaviour applies: the first --limit rows of the file from --offset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TAG = "halia-sample"
VENDOR = "Maison Aurelle"
IMG_BASE = "https://haliascore.com/img/"
TIERS_CACHE = Path("output/synthetic_tiers.csv")
PLAIN_DOMAINS = ("gmail.com", "gmail.com", "gmail.com", "icloud.com", "btinternet.com")

FIND = """query($q: String!) { customers(first: 1, query: $q) { nodes { id email numberOfOrders } } }"""
CREATE = """mutation($input: CustomerInput!) {
  customerCreate(input: $input) { customer { id } userErrors { field message } } }"""
ORDER = """mutation($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) { order { id name } userErrors { field message } } }"""
PRODUCT_CREATE = """mutation($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
  productCreate(product: $product, media: $media) {
    product { id title variants(first: 1) { nodes { id } } } userErrors { field message } } }"""
VARIANT_PRICE = """mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) { userErrors { field message } } }"""
PRODUCTS_FIND = """query { products(first: 50, query: "tag:%s") {
  nodes { id title variants(first: 1) { nodes { id } } } } }""" % TAG
ORDERS_FIND = """query { orders(first: 100, query: "tag:%s") { nodes { id } } }""" % TAG
CUSTOMERS_FIND = """query { customers(first: 100, query: "tag:%s") { nodes { id } } }""" % TAG
ORDER_DELETE = """mutation($id: ID!) { orderDelete(orderId: $id) { deletedId userErrors { message } } }"""
CUSTOMER_DELETE = """mutation($input: CustomerDeleteInput!) {
  customerDelete(input: $input) { deletedCustomerId userErrors { message } } }"""
PRODUCT_DELETE = """mutation($input: ProductDeleteInput!) {
  productDelete(input: $input) { deletedProductId userErrors { message } } }"""

# The Maison Aurelle catalogue: fictional, luxury fashion first, priced like the real thing.
# (title, type, price, image file, one line of copy)
PRODUCTS = [
    ("Aurelle cashmere coat", "Outerwear", "1450.00", "luxurybag.jpg",
     "Double-faced cashmere, hand-finished seams, made in Italy."),
    ("Marchmont wool coat", "Outerwear", "2400.00", "fashion.jpg",
     "Pressed virgin wool with a horn-button closure."),
    ("Delphine tailored blazer", "Tailoring", "1180.00", "luxury_ceo_client.jpg",
     "Single-breasted, half-canvassed, in midnight wool."),
    ("Solenne silk slip dress", "Dresses", "890.00", "three_clients.jpg",
     "Bias-cut sandwashed silk in ivory."),
    ("Ines cashmere crew", "Knitwear", "520.00", "clientimage.jpg",
     "Twelve-gauge Mongolian cashmere."),
    ("Verity leather tote", "Bags", "1650.00", "luxury_bag_detail.jpg",
     "Full-grain calfskin, unlined, hand-painted edges."),
    ("Estelle pearl necklace", "Fine jewellery", "890.00", "pearl_necklace.jpg",
     "Akoya pearls on an 18ct white gold clasp."),
    ("Camille silk scarf", "Accessories", "180.00", "nice_necklace.jpg",
     "Hand-rolled silk twill, 90cm."),
    ("Odile acetate sunglasses", "Accessories", "320.00", "twoclients.jpg",
     "Hand-polished Italian acetate."),
    ("Satin evening heel", "Shoes", "620.00", "wrapped_luxury_heels.jpg",
     "Duchesse satin on a 85mm heel."),
    ("No. 9 eau de parfum", "Fragrance", "165.00", "perfume.jpg",
     "Iris, vetiver and white musk, 100ml."),
    ("Oak occasional table", "Home", "740.00", "home_furniture.jpg",
     "Solid European oak, oiled finish."),
]


def _s(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null", "nat") else s


def split_name(full: str) -> tuple[str, str]:
    parts = [p for p in _s(full).replace(",", " ").split() if p]
    if not parts:
        return "Sample", "Client"
    if len(parts) == 1:
        return parts[0].title(), ""
    return parts[0].title(), " ".join(parts[1:]).title()


def _addr(row: dict, kind: str) -> dict | None:
    a1, a2, a3, a4 = (_s(row.get(f"LATEST_{kind}_ADDRESS{i}")) for i in range(1, 5))
    zip_ = _s(row.get(f"LATEST_{kind}_ZIP")) or (a4 if a4 and any(ch.isdigit() for ch in a4) else "")
    if not (a1 or a3 or zip_):
        return None
    country = a4 if a4 and not any(ch.isdigit() for ch in a4) else "United Kingdom"
    out = {"address1": a1 or a2, "city": a3 or a2, "zip": zip_, "country": country}
    if a2 and a2 != out["address1"]:
        out["address2"] = a2
    company = _s(row.get("COMPANY_NAME"))
    if company:
        out["company"] = company
    return {k: v for k, v in out.items() if v}


def address(row: dict) -> dict | None:
    """The shipping address (billing falls back to it)."""
    return _addr(row, "SHIPPING") or _addr(row, "BILLING")


def _when(row: dict, now: datetime) -> datetime:
    last = _s(row.get("Last Shopped"))
    try:
        when = datetime.fromisoformat(last[:10]).replace(tzinfo=timezone.utc) if last else now
    except ValueError:
        when = now
    return min(when, now)


def orders_for(row: dict, now: datetime) -> list[tuple[datetime, float]]:
    """(processed_at, amount) per order: the total spend split evenly, the latest on Last Shopped,
    earlier ones every 45 days before it."""
    spent = float(_s(row.get("Spent")) or 0) or 0.0
    n = int(float(_s(row.get("Count of CUST_ID")) or 1) or 1)
    n = max(1, min(n, 12))
    when = _when(row, now)
    amt = round(spent / n, 2) if spent > 0 else 120.0
    return [(when - timedelta(days=45 * i), amt) for i in range(n)]


def _pick_product(email: str, i: int, products: dict) -> tuple[str, str | None]:
    """A product for this order, stable per client: (title, variant gid or None)."""
    if not products:
        return "Sample purchase", None
    titles = sorted(products)
    h = int(hashlib.sha1(f"{email}:{i}".encode()).hexdigest(), 16)
    title = titles[h % len(titles)]
    return title, products[title]


def plan(rows: list[dict], now: datetime | None = None, products: dict | None = None) -> list[dict]:
    """The customer + order payloads for each row, with no network. ``products`` maps a product
    title to its variant gid; when given, orders carry real line items (priced at the order's
    amount, so the book's spend is exactly the file's)."""
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
        ship = address(row)
        bill = _addr(row, "BILLING") or ship
        if ship:
            cust["addresses"] = [{**ship, "firstName": first, "lastName": last}]
        orders = []
        for i, (when, amt) in enumerate(orders_for(row, now)):
            title, variant = _pick_product(email, i, products or {})
            line = {"title": title, "quantity": 1,
                    "priceSet": {"shopMoney": {"amount": f"{amt:.2f}", "currencyCode": "GBP"}}}
            if variant:
                line["variantId"] = variant
            o = {"processedAt": when.isoformat(timespec="seconds"),
                 "financialStatus": "PAID", "tags": [TAG], "currency": "GBP", "lineItems": [line]}
            if ship:
                o["shippingAddress"] = {**ship, "firstName": first, "lastName": last}
            if bill:
                o["billingAddress"] = {**bill, "firstName": first, "lastName": last}
            orders.append(o)
        out.append({"customer": cust, "orders": orders})
    return out


# ── choosing the book ─────────────────────────────────────────────────────────

def parse_mix(spec: str) -> dict[str, int]:
    """'A1:40,A:80,B:280,none:1100' -> {tier: count}."""
    out = {}
    for part in (spec or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = int(v)
    return out


def grade_series(scored):
    """(tier-code Series, surfaced-bool Series) for a frame the engine has scored."""
    from scoring.combine import HIDDEN_COL, SCORE_COL
    from scoring.grading import tier_for, to_score100
    tiers = scored[SCORE_COL].map(lambda raw: tier_for(to_score100(float(raw))))
    return tiers, scored[HIDDEN_COL].astype(bool)


def tiers_for(df, cache: Path | None = TIERS_CACHE, log=print):
    """(tier code, surfaced) per row, from the engine; cached to a small CSV keyed by CUST_ID so the
    100k-row scoring runs once."""
    import pandas as pd
    from scoring.combine import score_customers
    if cache and cache.exists():
        t = pd.read_csv(cache, dtype={"CUST_ID": str})
        if len(t) == len(df) and set(t["CUST_ID"]) == set(df["CUST_ID"].astype(str)):
            t = t.set_index("CUST_ID").loc[df["CUST_ID"].astype(str)]
            return t["tier"].to_numpy(), t["surfaced"].to_numpy().astype(bool)
    log(f"scoring {len(df):,} synthetic rows once (cached to {cache})")
    tiers, surfaced = grade_series(score_customers(df))
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"CUST_ID": df["CUST_ID"].astype(str), "tier": tiers.to_numpy(),
                      "surfaced": surfaced.to_numpy().astype(bool)}).to_csv(cache, index=False)
    return tiers.to_numpy(), surfaced.to_numpy().astype(bool)


def select_mix(df, mix: dict[str, int], seed: int = 7, log=print, cache: Path | None = TIERS_CACHE):
    """Rows per tier: the surfaced (hidden-VIC) rows of each grade, and for 'none' the unsurfaced
    rows, ~10% of them proven VICs (spend over the threshold)."""
    import numpy as np
    tiers, surfaced = tiers_for(df, cache=cache, log=log)
    rng = np.random.default_rng(seed)
    spent = df["Spent"].fillna(0).to_numpy(dtype=float)
    chosen = []
    for tier, n in mix.items():
        if tier == "none":
            idx = np.flatnonzero(~surfaced)
            big = idx[spent[idx] >= 5000]
            small = idx[spent[idx] < 5000]
            n_big = min(len(big), max(1, round(n * 0.10)))
            pick = np.concatenate([rng.choice(big, n_big, replace=False) if n_big else big[:0],
                                   rng.choice(small, min(len(small), n - n_big), replace=False)])
        else:
            idx = np.flatnonzero(surfaced & (tiers == tier))
            pick = rng.choice(idx, min(len(idx), n), replace=False)
            if len(pick) < n:
                log(f"only {len(pick)} {tier} rows in the file (asked {n})")
        chosen.append(pick)
    order = np.concatenate(chosen)
    rng.shuffle(order)
    return df.iloc[order]


def shift_dates(rows: list[dict], now: datetime, recent_days: int = 3, span_days: int = 720) -> list[dict]:
    """Map the rows' Last Shopped onto [now - recent - span, now - recent], keeping their order and
    spread, so the book reads as live: the newest sale a few days ago, the oldest two years back."""
    whens = [_when(r, datetime.max.replace(tzinfo=timezone.utc)) for r in rows]
    lo, hi = min(whens), max(whens)
    end = now - timedelta(days=recent_days)
    start = end - timedelta(days=span_days)
    out = []
    for r, w in zip(rows, whens):
        f = (w - lo) / (hi - lo) if hi > lo else 1.0
        r = dict(r)
        r["Last Shopped"] = (start + (end - start) * f).strftime("%Y-%m-%d")
        out.append(r)
    return out


_SUFFIX = re.compile(r"\d+$")


def polish_emails(rows: list[dict], seed: int = 7) -> list[dict]:
    """Drop the numeric suffix the generator uses for uniqueness (iris.larchmont1589@gmail.com) when
    the bare address is unique in this book, and spread the plain gmail rows over a few consumer
    domains. Signal domains (a bank, an alumni address, a paid mailbox) are left alone: they are
    what the engine scores."""
    import random
    rng = random.Random(seed)
    taken = {_s(r.get("EMAIL_ADDR")).lower() for r in rows}
    out = []
    for r in rows:
        email = _s(r.get("EMAIL_ADDR")).lower()
        local, _, domain = email.partition("@")
        if domain == "gmail.com" and _SUFFIX.search(local):
            bare = _SUFFIX.sub("", local)
            cand = f"{bare}@{rng.choice(PLAIN_DOMAINS)}"
            if cand not in taken:
                taken.discard(email); taken.add(cand)
                r = dict(r); r["EMAIL_ADDR"] = cand
        out.append(r)
    return out


def load_heroes(path: str | Path, now: datetime) -> list[dict]:
    """Hand-written clients for the demo clicks. Each may give days_ago instead of Last Shopped."""
    rows = json.loads(Path(path).read_text())
    out = []
    for r in rows:
        r = dict(r)
        if "days_ago" in r:
            r["Last Shopped"] = (now - timedelta(days=int(r.pop("days_ago")))).strftime("%Y-%m-%d")
        out.append(r)
    return out


# ── the catalogue ─────────────────────────────────────────────────────────────

def product_payloads() -> list[dict]:
    """productCreate variables per product; the default variant's price is set in a second call."""
    out = []
    for title, ptype, price, image, copy in PRODUCTS:
        out.append({"product": {"title": title, "vendor": VENDOR, "productType": ptype,
                                "tags": [TAG], "status": "ACTIVE",
                                "descriptionHtml": f"<p>{copy}</p>"},
                    "media": [{"originalSource": IMG_BASE + image, "mediaContentType": "IMAGE",
                               "alt": title}],
                    "price": price})
    return out


def existing_products(transport) -> dict[str, str]:
    from scoring.shopify_fetch import _run
    nodes = _run(transport, PRODUCTS_FIND, {}, 3)["products"]["nodes"]
    return {n["title"]: n["variants"]["nodes"][0]["id"] for n in nodes if n["variants"]["nodes"]}


def create_products(transport, sleep: float = 0.35, log=print) -> dict[str, str]:
    """Create the catalogue (skipping titles already there); returns title -> variant gid."""
    from scoring.shopify_fetch import _run
    have = existing_products(transport)
    for p in product_payloads():
        title = p["product"]["title"]
        if title in have:
            continue
        d = _run(transport, PRODUCT_CREATE, {"product": p["product"], "media": p["media"]}, 3)["productCreate"]
        if d.get("userErrors") or not d.get("product"):
            log(f"  {title}: {d.get('userErrors')}")
            continue
        pid = d["product"]["id"]
        variants = d["product"]["variants"]["nodes"]
        if variants:
            vid = variants[0]["id"]
            r = _run(transport, VARIANT_PRICE, {"productId": pid, "variants": [{"id": vid, "price": p["price"]}]}, 3)
            errs = r["productVariantsBulkUpdate"].get("userErrors")
            if errs:
                log(f"  {title} price: {errs}")
            have[title] = vid
        log(f"+ {title} £{p['price']}")
        time.sleep(sleep)
    return have


# ── writing and wiping ────────────────────────────────────────────────────────

def _phone_error(errs) -> bool:
    return any("phone" in str(e.get("field") or "").lower() or "phone" in str(e.get("message") or "").lower()
               for e in errs or [])


# Development stores accept at most 5 new orders a minute, so orders are spaced 12.5 s apart and
# a "Too many attempts" answer waits a minute and tries the same order again.
ORDER_GAP = 12.5
_last_order = [0.0]


def _create_orders(transport, cid, email, orders, stats, sleep, log, gap=None) -> int:
    from scoring.shopify_fetch import _run
    gap = ORDER_GAP if gap is None else gap
    made = 0
    for o in orders:
        for attempt in range(6):
            wait = _last_order[0] + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last_order[0] = time.monotonic()
            r = _run(transport, ORDER, {"order": {**o, "customerId": cid},
                                        "options": {"inventoryBehaviour": "BYPASS", "sendReceipt": False}}, 3)["orderCreate"]
            errs = r.get("userErrors") or []
            if errs and any("too many attempts" in str(e.get("message", "")).lower() for e in errs) and attempt < 5:
                time.sleep(65 if gap else 0)
                continue
            if errs:
                stats["errors"] += 1
                log(f"  {email} order: {errs}")
            else:
                made += 1
            break
    return made


class _Denied(Exception):
    pass


def run(transport, plans: list[dict], sleep: float = 0.35, log=print, gap: float | None = None) -> dict:
    from scoring.shopify_fetch import _run
    stats = {"customers": 0, "skipped": 0, "orders": 0, "errors": 0}
    denied = 0
    for p in plans:
        if denied >= 3:
            log("Stopped: Shopify refuses this app access to customer data. In the Partner Dashboard,\n"
                "open the app → API access requests → Protected customer data access, fill in the\n"
                "form (name, email, phone, address), save, then run the same command again.")
            break
        email = p["customer"]["email"]
        try:
            found = _run(transport, FIND, {"q": f'email:"{email}"'}, 3)["customers"]["nodes"]
            have = int(found[0].get("numberOfOrders") or 0) if found else 0
            if found and have >= len(p["orders"]):
                stats["skipped"] += 1
                continue
            if found:
                # Created on an earlier run that stopped before all its orders: finish it.
                cid = found[0]["id"]
                stats["skipped"] += 1
                n = _create_orders(transport, cid, email, p["orders"][have:], stats, sleep, log, gap)
                stats["orders"] += n
                log(f"+ {email}: {n} more order(s), customer already there")
                continue
            d = _run(transport, CREATE, {"input": p["customer"]}, 3)["customerCreate"]
            if d.get("userErrors") and _phone_error(d["userErrors"]) and "phone" in p["customer"]:
                # Shopify validates numbers against real ranges; a made-up one is dropped, not fatal.
                cust = {k: v for k, v in p["customer"].items() if k != "phone"}
                d = _run(transport, CREATE, {"input": cust}, 3)["customerCreate"]
            if d.get("userErrors"):
                stats["errors"] += 1
                log(f"  {email}: {d['userErrors']}")
                continue
            cid = d["customer"]["id"]
            stats["customers"] += 1
            n = _create_orders(transport, cid, email, p["orders"], stats, sleep, log, gap)
            stats["orders"] += n
            log(f"+ {email}: {n} order(s)  [{stats['customers'] + stats['skipped']}/{len(plans)}]")
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            if "protected-customer-data" in str(exc) or "not approved to access the Customer" in str(exc):
                denied += 1
                log(f"  {email}: no access to customer data")
            else:
                log(f"  {email}: {exc}")
        time.sleep(sleep)
    return stats


def wipe(transport, sleep: float = 0.2, log=print) -> dict:
    """Delete everything tagged halia-sample: orders first (a customer with orders cannot be
    deleted), then customers, then products."""
    from scoring.shopify_fetch import _run
    stats = {"orders": 0, "customers": 0, "products": 0, "errors": 0}
    steps = (("orders", ORDERS_FIND, "orders", ORDER_DELETE, lambda i: {"id": i}),
             ("customers", CUSTOMERS_FIND, "customers", CUSTOMER_DELETE, lambda i: {"input": {"id": i}}),
             ("products", PRODUCTS_FIND, "products", PRODUCT_DELETE, lambda i: {"input": {"id": i}}))
    for key, find, field, delete, var in steps:
        while True:
            ids = [n["id"] for n in _run(transport, find, {}, 3)[field]["nodes"]]
            if not ids:
                break
            for i in ids:
                r = _run(transport, delete, var(i), 3)
                errs = next(iter(r.values())).get("userErrors")
                if errs:
                    stats["errors"] += 1
                    log(f"  {i}: {errs}")
                else:
                    stats[key] += 1
                time.sleep(sleep)
            log(f"- {stats[key]} {key} so far")
            if stats["errors"] > 50:
                break
    return stats


def client_credentials_token(shop: str, client_id: str, client_secret: str) -> str:
    """An Admin API access token for a Dev Dashboard app installed on this store (24h life)."""
    import requests
    r = requests.post(f"https://{shop}/admin/oauth/access_token",
                      data={"grant_type": "client_credentials", "client_id": client_id,
                            "client_secret": client_secret}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"token exchange failed ({r.status_code}): {r.text[:300]}\n"
                 "Is the app installed on this store, with the write scopes, and released?")
    return r.json()["access_token"]


def main() -> None:
    import pandas as pd

    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default=os.environ.get("SHOPIFY_SHOP"))
    ap.add_argument("--token", default=os.environ.get("SHOPIFY_ADMIN_TOKEN"))
    ap.add_argument("--client-id", default=os.environ.get("SHOPIFY_CLIENT_ID"))
    ap.add_argument("--client-secret", default=os.environ.get("SHOPIFY_CLIENT_SECRET"))
    ap.add_argument("--source", default="sample_data/synthetic_100k.xlsx")
    ap.add_argument("--mix", help='rows per grade, e.g. "A1:40,A:80,B:280,none:1100"')
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--recent-days", type=int, default=3, help="the newest sale is this many days ago")
    ap.add_argument("--span-days", type=int, default=720, help="the book spans this many days")
    ap.add_argument("--heroes", help="JSON of hand-written clients to add (scripts/demo_heroes.json)")
    ap.add_argument("--products", action="store_true", help="create the catalogue only")
    ap.add_argument("--wipe", action="store_true", help="delete everything tagged halia-sample")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    def need_store():
        if a.shop and not a.token and a.client_id and a.client_secret:
            a.token = client_credentials_token(a.shop, a.client_id, a.client_secret)
        if not (a.shop and a.token):
            sys.exit("--shop plus either --token or --client-id/--client-secret "
                     "(write_customers + write_orders + write_products) are required")
        from scoring.shopify_fetch import http_transport
        return http_transport(a.shop, a.token)

    if a.wipe:
        print(wipe(need_store()))
        return
    if a.products:
        print(f"{len(create_products(need_store()))} products in the catalogue")
        return

    now = datetime.now(timezone.utc)
    df = pd.read_excel(a.source)
    if a.mix:
        rows = select_mix(df, parse_mix(a.mix), seed=a.seed).to_dict("records")
        rows = shift_dates(rows, now, a.recent_days, a.span_days)
        rows = polish_emails(rows, seed=a.seed)
    else:
        rows = df.iloc[a.offset:a.offset + a.limit].to_dict("records")
    if a.heroes:
        rows = load_heroes(a.heroes, now) + rows
    products = {}
    if not a.dry_run:
        transport = need_store()
        products = existing_products(transport)
        if not products:
            print("no catalogue in the store yet: run --products first for real line items")
    plans = plan(rows, now, products)
    print(f"{len(plans)} customers, {sum(len(p['orders']) for p in plans)} orders from {a.source}")
    if a.dry_run:
        for p in plans[:8]:
            print(p["customer"]["email"], [o["processedAt"][:10] for o in p["orders"]],
                  [o["lineItems"][0]["title"] for o in p["orders"]][:1])
        whens = sorted(o["processedAt"][:10] for p in plans for o in p["orders"])
        print(f"sales from {whens[0]} to {whens[-1]}")
        return
    print(run(transport, plans))


if __name__ == "__main__":
    main()
