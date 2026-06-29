"""Canonical contracts every Halia surface speaks: CustomerRecord and ScoreResult.

`CustomerRecord` is the engine's INPUT contract — one flat row per customer, the
columns the signals read (`scoring.shopify.LATEST_COLS`) plus the behavioural /
display fields aggregation adds. Any source adapter (Shopify, Klaviyo, …) must
produce these keys; absent keys are tolerated (signals no-op on missing columns).

`ScoreResult` is the engine's OUTPUT contract — the "score + why" answer. It is the
exact shape `scoring/realtime.py` has always returned at the till (so the POS, the
dashboard, the API and the write-back sinks can never disagree), plus identity fields
(`customer_id`/`email`/`phone`) and `hidden_vic` so it can be stored and routed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from scoring.combine import COUNT_COL, HIDDEN_COL, REASONS_COL, SCORE_COL
from scoring.grading import GRADE_LABEL, gesture_for, tier_for, to_score100
from scoring.shopify import LATEST_COLS

# Behavioural / display columns aggregation adds on top of LATEST_COLS. Documented
# here so adapter authors know the full input surface; none are individually required.
BEHAVIOURAL_COLS = [
    "CUST_ID", "Spent", "Items", "Count of CUST_ID", "orders_count", "SEGMENT",
    "avg_order_value", "days_since_last_order", "tenure_days", "full_price_ratio",
    "distinct_shipping_addresses", "single_order_then_silent",
]
# The canonical input contract (order-preserving, de-duped).
CUSTOMER_RECORD_COLS: list[str] = list(dict.fromkeys([*LATEST_COLS, *BEHAVIOURAL_COLS]))


def normalize_record(record: dict | pd.Series) -> dict:
    """Coerce any mapping into a plain CustomerRecord dict (string-keyed)."""
    return {str(k): v for k, v in dict(record).items()}


def _signal_labels(reasons: str) -> list[str]:
    """Split a 'Label: detail; Label: detail' reason string into its labels."""
    return [p.split(":", 1)[0].strip() for p in str(reasons).split(";") if p.strip()]


def _identity(row: pd.Series) -> dict:
    cid = row.get("CUST_ID")
    return {
        "customer_id": None if cid is None or pd.isna(cid) else str(cid),
        "email": (str(row.get("EMAIL_ADDR")) if row.get("EMAIL_ADDR") not in (None, "") else None),
        "phone": (str(row.get("PHONE")) if row.get("PHONE") not in (None, "") else None),
    }


@dataclass
class ScoreResult:
    """The "score + why" answer — one client, fully self-describing."""

    matched: bool
    flagged: bool
    tier: str | None
    grade: str
    score: int | None
    is_priority: bool
    signal_count: int
    signals: list[str]
    reasons: str
    gesture: str
    spend: float
    hidden_vic: bool = False
    customer_id: str | None = None
    email: str | None = None
    phone: str | None = None

    # The keys scoring/realtime.py has always returned to the POS — kept stable.
    POS_KEYS = (
        "matched", "flagged", "tier", "grade", "score", "is_priority",
        "signal_count", "signals", "reasons", "gesture", "spend",
    )

    @classmethod
    def no_match(cls) -> "ScoreResult":
        """A genuine unknown — no customer matched the identifier."""
        return cls(
            matched=False, flagged=False, tier=None, grade="—", score=None,
            is_priority=False, signal_count=0, signals=[], reasons="", gesture="",
            spend=0.0, hidden_vic=False,
        )

    @classmethod
    def from_scored_row(cls, row: pd.Series) -> "ScoreResult":
        """Build from one row of a `score_customers` frame (the canonical mapping)."""
        ident = _identity(row)
        count = int(row[COUNT_COL])
        spend = float(row.get("Spent") or 0)
        hidden = bool(row.get(HIDDEN_COL)) if HIDDEN_COL in row else False
        if count == 0:
            # Matched a customer, but no wealth signal fired — don't flag anything.
            return cls(
                matched=True, flagged=False, tier=None, grade="—", score=to_score100(0),
                is_priority=False, signal_count=0, signals=[], reasons="", gesture="",
                spend=spend, hidden_vic=hidden, **ident,
            )
        s100 = to_score100(float(row[SCORE_COL]))
        tier = tier_for(s100)
        reasons = str(row.get(REASONS_COL) or "")
        return cls(
            matched=True, flagged=True, tier=tier, grade=GRADE_LABEL.get(tier, tier),
            score=s100, is_priority=tier in ("A1", "A"), signal_count=count,
            signals=_signal_labels(reasons), reasons=reasons, gesture=gesture_for(tier),
            spend=spend, hidden_vic=hidden, **ident,
        )

    def pos_dict(self) -> dict:
        """The original POS-facing dict (no identity fields) — back-compat shape."""
        return {k: getattr(self, k) for k in self.POS_KEYS}

    def to_dict(self) -> dict:
        """Full result incl. identity + hidden_vic — what the API/store persist."""
        return asdict(self)
