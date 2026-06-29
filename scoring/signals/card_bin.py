"""Premium-card (BIN) signal — for the Shopify phase.

Flags customers who paid with a premium / private-bank card, identified by the
card BIN (reference_data/cards/premium_bins.csv).

Shopify exposes the BIN on the Order Transactions endpoint as
``payment_details.credit_card_bin`` (with ``credit_card_company`` for the brand);
flatten those onto the customer record as the ``credit_card_bin`` /
``credit_card_company`` columns. The current spreadsheet export has neither, so
this signal stays DORMANT (flags nothing) until that data is present — by design.

Only the BIN (first 6-8 digits) is ever used — never a full card number.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import PREMIUM_BINS_FILE

FLAG_COL = "premium_card"
REASON_COL = "premium_card_reason"

BIN_COL = "credit_card_bin"
COMPANY_COL = "credit_card_company"


def _digits(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\D", "", str(value))


def load_bins(path: Path | str = PREMIUM_BINS_FILE) -> list[tuple[str, str, str]]:
    """Read [(bin_prefix, issuer, tier)], longest prefix first."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Premium-BIN reference list not found: {path}")
    bins: list[tuple[str, str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            prefix = _digits(row[0])
            first = row[0].strip()
            if not prefix or first.startswith("#") or first.lower() == "bin_prefix":
                continue
            issuer = row[1].strip() if len(row) > 1 else ""
            tier = row[2].strip() if len(row) > 2 else ""
            bins.append((prefix, issuer, tier))
    return sorted(bins, key=lambda b: -len(b[0]))


def match_bin(
    bin_value: object, bins: list[tuple[str, str, str]], company: object = None
) -> tuple[bool, str | None]:
    """Return (is_premium, reason). Reason is 'Issuer (tier)', + brand if known."""
    digits = _digits(bin_value)
    if not digits:
        return False, None
    for prefix, issuer, tier in bins:
        if digits.startswith(prefix):
            label = f"{issuer} ({tier})" if tier else issuer
            brand = str(company).strip() if company not in (None, "") else ""
            if brand and not (isinstance(company, float) and pd.isna(company)):
                label = f"{label} [{brand}]"
            return True, label
    return False, None


def flag_card_bin(
    df: pd.DataFrame,
    bins: list[tuple[str, str, str]] | None = None,
    bin_col: str = BIN_COL,
    company_col: str = COMPANY_COL,
) -> pd.DataFrame:
    """Add premium-card flag + reason columns. Dormant if no BIN column."""
    if bins is None:
        bins = load_bins()

    out = df.copy()
    if bin_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    companies = out[company_col] if company_col in out.columns else pd.Series([None] * len(out))
    results = [
        match_bin(b, bins, c)
        for b, c in zip(out[bin_col].tolist(), companies.tolist())
    ]
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
