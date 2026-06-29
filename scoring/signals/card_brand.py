"""Premium card-brand signal (§3).

Flags customers paying with a card brand that skews affluent — American Express,
Diners Club. Reads ``credit_card_company`` (from the Order Transactions data, the
same source as the BIN signal), so it is DORMANT until that column is present.
Sensitive/gated payment data — keep weighted low and never load-bearing; it is a
brand only, never a card number. Grouped with the BIN signal under "payment".
"""
from __future__ import annotations

import pandas as pd

FLAG_COL = "card_brand"
REASON_COL = "card_brand_reason"

PREMIUM_BRANDS = {"AMERICAN EXPRESS", "AMEX", "DINERS CLUB", "DINERS"}


def flag_card_brand(
    df: pd.DataFrame, company_col: str = "credit_card_company"
) -> pd.DataFrame:
    """Add premium card-brand flag + reason columns. Dormant without the column."""
    out = df.copy()
    if company_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    norm = out[company_col].astype("string").str.upper().str.strip()
    fired = norm.isin(PREMIUM_BRANDS)
    out[FLAG_COL] = fired.fillna(False)
    out[REASON_COL] = [
        f"{str(b).title()} card" if bool(f) else None
        for f, b in zip(out[FLAG_COL].tolist(), out[company_col].fillna("").tolist())
    ]
    return out
