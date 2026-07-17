"""Store Concierge's clienteling view: pure RFM over a customer frame, no wealth engine.

This is the whole point of the separate brand. It reads only the order behaviour a shop
already has (how recently, how often, how much) and never runs a Halia wealth signal, never
produces a grade. Like the rest of the platform it is zero-retention: it takes a DataFrame
that already lives in RAM and returns a plain dict. It stores nothing, anywhere.

The one durable thing Store Concierge offers, per-client notes, is written to the merchant's
OWN Shopify (a customer metafield), never to us, so zero-retention holds there too.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

# The frame comes from either the Shopify adapter (orders_to_customers) or the sample loader,
# whose column names differ. Pick the first that is present.
_ORDERS_COLS = ("Count of CUST_ID", "orders_count")
_SPENT_COLS = ("LT Spent", "Spent", "total_spent")
_LAST_COLS = ("Last Shopped", "last_order_at")

WINBACK_DAYS = 90          # "gone quiet" once this many days have passed since the last order
WINBACK_MIN_ORDERS = 2     # only proven, repeat customers belong on a win-back list
ORDER_FRESH_DAYS = 30      # a purchase this recent still counts as a live order in the orders view


def _first_col(df: pd.DataFrame, names: tuple) -> Optional[str]:
    for n in names:
        if n in df.columns:
            return n
    return None


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def clienteling_payload(
    df: pd.DataFrame,
    *,
    as_of: Optional[pd.Timestamp] = None,
    winback_days: int = WINBACK_DAYS,
    winback_min_orders: int = WINBACK_MIN_ORDERS,
    winback_min_spend: Optional[float] = None,
    limit: int = 600,
) -> dict:
    """Build the clienteling payload from a customer frame. Recency is measured against
    ``as_of`` (defaults to today; a demo can anchor it to the data's most recent order so a
    stale sample still reads sensibly).

    A customer is 'worth a nudge' (win-back) when they've gone quiet AND they are either a
    proven repeat customer (>= ``winback_min_orders`` orders) OR a valuable one (lifetime
    spend at or above ``winback_min_spend``, which defaults to the median spend so the rule
    adapts to any shop and does not depend on order counts being present). Nothing is
    persisted."""
    orders_col = _first_col(df, _ORDERS_COLS)
    spent_col = _first_col(df, _SPENT_COLS)
    last_col = _first_col(df, _LAST_COLS)

    if df is None or len(df) == 0 or last_col is None:
        return {"stats": {"customers": 0, "active": 0, "lapsed": 0, "winback": 0,
                          "orders": 0, "ltv": 0.0},
                "customers": [], "winback": [], "orders": []}

    g = df.copy()
    g["_orders"] = _num(g[orders_col]).astype(int).clip(lower=1) if orders_col else 1
    g["_spent"] = _num(g[spent_col]).round(2) if spent_col else 0.0
    g["_last"] = pd.to_datetime(g[last_col], errors="coerce")

    ref = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.today().normalize()
    g["_days"] = (ref - g["_last"]).dt.days
    # a customer with no known last-order date is treated as long-lapsed, not active
    g["_days"] = g["_days"].fillna(10 ** 6).astype(int)
    g["_active"] = g["_days"] <= winback_days

    def _row(r) -> dict:
        last = r["_last"]
        return {
            "cid": str(r.get("CUST_ID", "") or "").split(".")[0],
            "name": str(r.get("Name", "") or "").strip() or "Customer",
            "email": str(r.get("EMAIL_ADDR", "") or "").strip(),
            "phone": str(r.get("PHONE", "") or r.get("phone", "") or "").strip(),
            "orders": int(r["_orders"]),
            "spent": float(r["_spent"]),
            "last": last.date().isoformat() if pd.notna(last) else "",
            "days": int(r["_days"]),
            "status": "active" if r["_active"] else "lapsed",
        }

    ranked = g.sort_values("_spent", ascending=False)
    customers = [_row(r) for _, r in ranked.head(limit).iterrows()]

    positive = g.loc[g["_spent"] > 0, "_spent"]
    spend_ref = (winback_min_spend if winback_min_spend is not None
                 else (float(positive.median()) if len(positive) else 0.0))
    worth = (ranked["_orders"] >= winback_min_orders) | (ranked["_spent"] >= spend_ref)
    winback_frame = ranked[(~ranked["_active"]) & worth]
    winback = [_row(r) for _, r in winback_frame.head(limit).iterrows()]

    # Orders view: a customer's most recent purchase, still fresh enough to be a live order,
    # with a lifecycle stage inferred from how long ago it landed. Real Shopify orders carry a
    # true fulfilment status; this reads the aggregate frame we have and stages by recency.
    def _stage(days: int) -> str:
        if days <= 2:
            return "preparing"
        if days <= 9:
            return "on its way"
        return "delivered"

    recent = g[g["_days"] <= ORDER_FRESH_DAYS].sort_values("_days")
    orders = []
    for _, r in recent.head(limit).iterrows():
        row = _row(r)
        row["stage"] = _stage(int(r["_days"]))
        orders.append(row)

    stats = {
        "customers": int(len(g)),
        "active": int(g["_active"].sum()),
        "lapsed": int((~g["_active"]).sum()),
        "winback": int(len(winback_frame)),
        "orders": int(len(recent)),
        "ltv": round(float(g["_spent"].sum()), 2),
    }
    return {"stats": stats, "customers": customers, "winback": winback, "orders": orders}
