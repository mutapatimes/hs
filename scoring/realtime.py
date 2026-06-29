"""Real-time, single-client grading — the POS-facing shim over the engine.

Clienteling starts at the till. The shop floor needs a fast answer for ONE
identified client: their grade, and the discreet gesture to offer ("coffee in
the cafe", "mention the private preview"), right as they're standing there.

This module now delegates to `halia.engine` (the one scoring brain every surface
shares) and returns the same POS-shaped dict it always has, so the till and the
dashboard always agree. The canonical result type lives in `halia.schema.ScoreResult`;
here we return its `.pos_dict()` for back-compat.

Honest limit: this only fires once the client is IDENTIFIABLE — a returning
customer, a loyalty sign-in, or an email/card captured early in the interaction.
A true unknown walk-in has no history to match on until they pay.

    grade_record(aggregated_customer_dict)     # already have the record
    grade_from_orders(orders)                  # have raw orders for one customer
    lookup_and_grade("a@b.com")                # live: fetch by email/phone + grade
"""
from __future__ import annotations

from halia.engine import engine
from halia.schema import ScoreResult

# Returned when no customer matches the identifier (a genuine unknown walk-in).
NO_MATCH = ScoreResult.no_match().pos_dict()


def grade_record(record: dict, today=None) -> dict:
    """Grade one already-aggregated customer record (the orders_to_customers shape)."""
    return engine.score_one(record).pos_dict()


def grade_from_orders(orders: list[dict], today=None) -> dict:
    """Aggregate one customer's raw orders and grade them. Empty -> no-match."""
    from scoring.shopify import orders_to_customers

    if not orders:
        return dict(NO_MATCH)
    customers = orders_to_customers(orders, today=today)
    if customers.empty:
        return dict(NO_MATCH)
    return ScoreResult.from_scored_row(engine.score_frame(customers).iloc[0]).pos_dict()


def lookup_and_grade(identifier: str, transport=None, by: str = "email", today=None) -> dict:
    """Live POS path: fetch one customer by email/phone from Shopify and grade them.

    ``by`` is "email" or "phone"; ``transport`` is injectable for testing.
    """
    from scoring.shopify_fetch import fetch_customer_orders

    orders = fetch_customer_orders(identifier, transport=transport, by=by)
    return grade_from_orders(orders, today=today)
