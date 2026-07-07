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


# Internal tier codes -> human, client-facing labels (no underscores).
_TIER_LABEL = {
    "private_bank": "private-bank",
    "ultra_premium": "ultra-premium",
    "premium": "premium",
}


def _clean_issuer(issuer: object) -> str:
    """Strip operator annotations from a BIN issuer so they never reach a client view.

    'Example - Amex Centurion (VERIFY)' -> 'Amex Centurion'. A licensed BIN list has
    clean issuer names, so this is a no-op there; it only sanitises the seed's
    placeholder markers (which stay in the CSV as a 'replace me' reminder).
    """
    s = str(issuer or "").strip()
    s = re.sub(r"^(?:example|sample|placeholder)\s*[-:]\s*", "", s, flags=re.I)
    s = re.sub(r"\s*[(\[](?:verify|example|placeholder|todo)[)\]]\s*", " ", s, flags=re.I)
    return re.sub(r"\s{2,}", " ", s).strip()


def _tier_label(tier: object) -> str:
    t = str(tier or "").strip()
    return _TIER_LABEL.get(t, t.replace("_", " "))


def match_bin(
    bin_value: object, bins: list[tuple[str, str, str]], company: object = None
) -> tuple[bool, str | None]:
    """Return (is_premium, reason) as human copy, e.g. 'Amex Centurion, ultra-premium card'.

    Internal tier codes and operator annotations are cleaned out so nothing
    developer-y (underscores, [brackets], (VERIFY)) reaches the client dashboard.
    ``company`` (the raw card network) is accepted for signature stability but no
    longer appended: the issuer plus tier is the story, and the raw field is noisy.
    """
    digits = _digits(bin_value)
    if not digits:
        return False, None
    for prefix, issuer, tier in bins:
        if digits.startswith(prefix):
            name = _clean_issuer(issuer)
            tl = _tier_label(tier)
            if name and tl:
                label = f"{name}, {tl} card"
            elif name:
                label = name
            elif tl:
                label = f"{tl} card"
            else:
                label = "premium card"
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
