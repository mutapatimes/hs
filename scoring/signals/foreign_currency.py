"""Foreign-currency checkout signal (§3).

Flags customers who check out in a currency other than the store's home currency
— an international / travelling-shopper tell. Reads an order ``currency`` column
(presentment currency code, e.g. "USD", "AED"); DORMANT until ingestion supplies
it. Grouped with the geographic signals, since currency largely echoes location.
"""
from __future__ import annotations

import pandas as pd

FLAG_COL = "foreign_currency"
REASON_COL = "foreign_currency_reason"

HOME_CURRENCY = "GBP"  # the store's settlement currency — set per merchant


def flag_foreign_currency(
    df: pd.DataFrame,
    home: str = HOME_CURRENCY,
    currency_col: str = "currency",
) -> pd.DataFrame:
    """Add foreign-currency flag + reason columns. Dormant without a currency column."""
    out = df.copy()
    if currency_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    cur = out[currency_col].astype("string").str.upper().str.strip()
    home_norm = str(home).upper().strip()
    fired = cur.notna() & (cur != "") & (cur != home_norm)
    out[FLAG_COL] = fired.fillna(False)
    out[REASON_COL] = [
        f"checks out in {c} (foreign currency)" if bool(f) else None
        for f, c in zip(out[FLAG_COL].tolist(), cur.fillna("").tolist())
    ]
    return out
