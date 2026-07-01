"""Phone-country ≠ address-country mismatch signal.

Flags a customer whose PHONE dialling code maps to a high-value / GCC / HNW jurisdiction
(reference_data/phone/hnw_dialing_codes.csv) that does NOT match their billing or shipping
country. A matching local number never fires — so this is a mobility / international-ties
tell, not a "where they're from" indicator.

It is still DERIVED from the phone country code (which correlates with national origin), so
it is an ORIGIN PROXY: registered OFF BY DEFAULT in scoring.combine (the include_origin gate),
alongside phone_country/gcc_billing. Nothing derived from a phone-jurisdiction lookup ever
originates a score by default (see docs/geography-signal-taxonomy.md — the one on-by-default
use is agreement-as-confidence corroborating an address, which is a separate signal). The
reason text states only the observed fact — never a wealth or origin inference — so the audit
trail records no sensitive conclusion.
"""
from __future__ import annotations

import pandas as pd

from scoring.signals.gcc_billing import _normalize
from scoring.signals.phone_country import load_codes, match_phone

FLAG_COL = "phone_mismatch"
REASON_COL = "phone_mismatch_reason"

BILLING_COUNTRY_COL = "LATEST_BILLING_ADDRESS4"
SHIPPING_COUNTRY_COL = "LATEST_SHIPPING_ADDRESS4"


def _same_country(jurisdiction: str, country_value: object) -> bool:
    """True if the phone jurisdiction and an address-country string are the same country.
    Whole-word, punctuation-insensitive, checked both ways (so 'United Arab Emirates'
    matches 'UNITED ARAB EMIRATES', and neither 'Oman' nor 'Romania' cross-match)."""
    j = _normalize(jurisdiction)
    c = _normalize(country_value)
    if not j or not c:
        return False
    return f" {j} " in f" {c} " or f" {c} " in f" {j} "


def flag_phone_mismatch(
    df: pd.DataFrame,
    codes=None,
    phone_col: str = "PHONE",
    billing_col: str = BILLING_COUNTRY_COL,
    shipping_col: str = SHIPPING_COUNTRY_COL,
) -> pd.DataFrame:
    """Add mismatch flag + bare-fact reason columns. Dormant if PHONE is absent."""
    if codes is None:
        codes = load_codes()
    out = df.copy()
    if phone_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    n = len(out)
    billing = out[billing_col] if billing_col in out.columns else pd.Series([None] * n, index=out.index)
    shipping = out[shipping_col] if shipping_col in out.columns else pd.Series([None] * n, index=out.index)

    flags: list[bool] = []
    reasons: list[str | None] = []
    for phone, b, s in zip(out[phone_col].tolist(), billing.tolist(), shipping.tolist()):
        hit, juris = match_phone(phone, codes)
        if not hit or _same_country(juris, b) or _same_country(juris, s):
            flags.append(False)
            reasons.append(None)
            continue
        addr = next((str(x).strip() for x in (b, s) if x is not None and str(x).strip()),
                    "no address country on file")
        flags.append(True)
        reasons.append(
            f"Phone jurisdiction ({juris}) differs from billing/shipping country ({addr})")
    out[FLAG_COL] = flags
    out[REASON_COL] = reasons
    return out
