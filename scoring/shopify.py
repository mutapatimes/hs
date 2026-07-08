"""Flatten Shopify order JSON into the per-customer schema the engine expects.

Shopify gives one JSON object per ORDER; the engine scores one row per CUSTOMER.
So we map each order's fields to the engine's column names, then aggregate all of
a customer's orders into a single row (lifetime spend, total items, latest
address). The output of ``orders_to_customers`` can be fed straight into
``add_ip_geolocation`` (optional) and ``score_customers``.

Card BIN/brand are NOT on the order object — they come from the Order
Transactions endpoint. Pass them per order via ``transactions``.
"""
from __future__ import annotations

import pandas as pd

# Engine column names (must match what scoring.signals.* read).
LATEST_COLS = [
    "Name", "EMAIL_ADDR", "PHONE", "Last Shopped", "COMPANY_NAME",
    "LATEST_BILLING_ADDRESS1", "LATEST_BILLING_ADDRESS2",
    "LATEST_BILLING_ADDRESS3", "LATEST_BILLING_ADDRESS4", "LATEST_BILLING_ZIP",
    "LATEST_SHIPPING_ADDRESS1", "LATEST_SHIPPING_ADDRESS2",
    "LATEST_SHIPPING_ADDRESS3", "LATEST_SHIPPING_ADDRESS4", "LATEST_SHIPPING_ZIP",
    "browser_ip", "credit_card_bin", "credit_card_company", "ORDER_NOTE",
]
KNOWN_VIC_TAGS = {"vip", "vic"}
SILENT_DAYS = 180  # a single order older than this = "tested us once, then silence"


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def abandoned_to_cart(node: dict) -> dict:
    """Map one abandoned-checkout GraphQL node to a compact 'open basket' dict.

    Shape: {cid, email, value (int £), count, items:[{title,qty}], started (YYYY-MM-DD), url}.
    """
    cust = node.get("customer") or {}
    li_nodes = ((node.get("lineItems") or {}).get("nodes")) or []
    items = [{"title": (n.get("title") or "Item"), "qty": int(n.get("quantity") or 0)}
             for n in li_nodes]
    total = _to_float((((node.get("totalPriceSet") or {}).get("shopMoney")) or {}).get("amount"))
    cid = cust.get("id")
    return {
        "id": None if node.get("id") is None else str(node.get("id")),   # stable dedup key
        "cid": None if cid is None else str(cid),
        "email": cust.get("email"),
        "value": int(round(total)),
        "count": sum(i["qty"] for i in items),
        "items": items,
        "started": str(node.get("createdAt") or "")[:10],
        "url": node.get("abandonedCheckoutUrl") or "",
    }


def carts_by_customer(nodes: list[dict]) -> dict:
    """CUST_ID -> most recent non-empty open basket. Nodes arrive newest-first, so the first
    seen for a customer is kept (their latest abandoned checkout)."""
    by: dict[str, dict] = {}
    for n in nodes:
        cart = abandoned_to_cart(n)
        cid = cart["cid"]
        if not cid or cart["count"] <= 0:
            continue
        by.setdefault(cid, cart)
    return by


def _tags(*sources) -> set[str]:
    out: set[str] = set()
    for src in sources:
        if not src:
            continue
        out.update(t.strip().lower() for t in str(src).split(",") if t.strip())
    return out


def _order_note(order: dict) -> str | None:
    """Combine the merchant-facing order note + note attributes (gift messages,
    delivery instructions) into one scannable string. ``None`` when empty — most
    channels/exports carry no note, so the notes signal stays dormant then."""
    parts = [order.get("note")]
    for attr in order.get("note_attributes") or []:
        parts.append(f"{attr.get('name') or ''} {attr.get('value') or ''}")
    text = " | ".join(p.strip() for p in parts if p and str(p).strip())
    return text or None


def _card_from_transactions(transactions) -> tuple[str | None, str | None]:
    for txn in transactions or []:
        details = (txn or {}).get("payment_details") or {}
        if details.get("credit_card_bin"):
            return details.get("credit_card_bin"), details.get("credit_card_company")
    return None, None


def flatten_order(order: dict, transactions: list | None = None) -> dict:
    """Map a single Shopify order to engine columns (not yet aggregated)."""
    cust = order.get("customer") or {}
    bill = order.get("billing_address") or {}
    ship = order.get("shipping_address") or {}
    client = order.get("client_details") or {}

    name = " ".join(p for p in [cust.get("first_name"), cust.get("last_name")] if p)
    name = name or bill.get("name") or ship.get("name")
    items = sum(int(li.get("quantity") or 0) for li in (order.get("line_items") or []))
    card_bin, card_company = _card_from_transactions(transactions)

    # Per-order behavioural inputs (aggregated later, spec §5a).
    discounted = _to_float(order.get("total_discounts")) > 0
    ship_a1 = str(ship.get("address1") or "").strip().lower()
    ship_zip = str(ship.get("zip") or "").strip().lower()
    ship_key = f"{ship_a1}|{ship_zip}" if (ship_a1 or ship_zip) else None

    return {
        "CUST_ID": cust.get("id") or cust.get("email") or order.get("email"),
        "Name": name,
        "EMAIL_ADDR": cust.get("email") or order.get("email"),
        "PHONE": cust.get("phone") or order.get("phone") or bill.get("phone"),
        "Spent": _to_float(order.get("total_price") or order.get("current_total_price")),
        "Items": items,
        "Discounted": discounted,
        "ShipKey": ship_key,
        "Last Shopped": order.get("created_at"),
        "tags": _tags(order.get("tags"), cust.get("tags")),
        "COMPANY_NAME": bill.get("company"),
        "LATEST_BILLING_ADDRESS1": bill.get("address1"),
        "LATEST_BILLING_ADDRESS2": bill.get("address2"),
        "LATEST_BILLING_ADDRESS3": bill.get("city"),
        "LATEST_BILLING_ADDRESS4": bill.get("country"),
        "LATEST_BILLING_ZIP": bill.get("zip"),
        "LATEST_SHIPPING_ADDRESS1": ship.get("address1"),
        "LATEST_SHIPPING_ADDRESS2": ship.get("address2"),
        "LATEST_SHIPPING_ADDRESS3": ship.get("city"),
        "LATEST_SHIPPING_ADDRESS4": ship.get("country"),
        "LATEST_SHIPPING_ZIP": ship.get("zip"),
        "browser_ip": order.get("browser_ip") or client.get("browser_ip"),
        "credit_card_bin": card_bin,
        "credit_card_company": card_company,
        "ORDER_NOTE": _order_note(order),
    }


def _join_notes(series) -> str | None:
    seen, out = set(), []
    for note in series:
        if not note or (isinstance(note, float) and pd.isna(note)):
            continue
        text = str(note).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return " | ".join(out) or None


def _add_behavioural_features(g: pd.DataFrame, today) -> None:
    """Derive the spec §5a behavioural columns in place (consumes ``_discounted``).

    ``today`` is the reference date for recency (defaults to now, UTC). Pass a
    fixed Timestamp in tests for determinism.
    """
    if today is None:
        today = pd.Timestamp.now(tz="UTC")
    g["avg_order_value"] = (g["Spent"] / g["orders_count"]).round(2)
    g["full_price_ratio"] = (1 - g["_discounted"] / g["orders_count"]).round(3)
    g["tenure_days"] = (g["last_order_at"] - g["first_order_at"]).dt.days
    g["days_since_last_order"] = (today - g["last_order_at"]).dt.days
    g["single_order_then_silent"] = (
        (g["orders_count"] == 1) & (g["days_since_last_order"] > SILENT_DAYS)
    )
    g.drop(columns=["_discounted"], inplace=True)


def orders_to_customers(
    orders: list[dict],
    transactions_by_order: dict | None = None,
    today=None,
) -> pd.DataFrame:
    """Flatten + aggregate many orders into one row per customer.

    ``transactions_by_order`` optionally maps order id -> its transactions list.
    ``today`` sets the recency reference date (defaults to now, UTC).
    """
    rows = [
        flatten_order(o, (transactions_by_order or {}).get(o.get("id")))
        for o in orders
    ]
    df = pd.DataFrame(
        rows,
        columns=["CUST_ID", "Spent", "Items", "tags", "Discounted", "ShipKey"] + LATEST_COLS,
    )
    if df.empty:
        df["SEGMENT"] = []
        return df

    df["Last Shopped"] = pd.to_datetime(df["Last Shopped"], errors="coerce", utc=True)
    df = df.sort_values("Last Shopped", na_position="first")

    grouped = df.groupby("CUST_ID", as_index=False, sort=False).agg(
        Spent=("Spent", "sum"),
        Items=("Items", "sum"),
        tags=("tags", lambda s: set().union(*s)),
        orders_count=("CUST_ID", "size"),
        first_order_at=("Last Shopped", "min"),
        last_order_at=("Last Shopped", "max"),
        _discounted=("Discounted", "sum"),
        distinct_shipping_addresses=("ShipKey", "nunique"),
        # A staffed-household note may sit on any order, not just the latest —
        # keep every distinct non-empty note so the notes signal can see it.
        ORDER_NOTE=("ORDER_NOTE", _join_notes),
        **{c: (c, "last") for c in LATEST_COLS if c != "ORDER_NOTE"},
    )
    grouped["SEGMENT"] = grouped["tags"].apply(
        lambda t: "VIP" if t & KNOWN_VIC_TAGS else "Final Client"
    )
    _add_behavioural_features(grouped, today)
    return grouped
