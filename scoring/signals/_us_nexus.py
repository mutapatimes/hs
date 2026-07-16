"""US-nexus gate for the US name-match signals.

``us_insider`` (SEC Forms 3/4/5) and ``us_foundation`` (IRS 990-PF) match a customer's NAME against
a US public register. A shared name ("John Smith") could belong to someone with no US connection,
so those signals only fire when the customer is INDEPENDENTLY pinned to the US by a geo field:
  * an explicit US billing/shipping country, or
  * a +1 (North American) phone number, or
  * a US-format ZIP (5 digits), UNLESS a country field names a non-US country — a bare 5-digit code
    also matches continental-EU postcodes (Milan 20121, Paris 75001), so an explicit foreign country
    vetoes the ZIP path.

The ZIP-based US signals (``us_zip``, ``us_property``) are already geo-anchored and need no gate.
"""
from __future__ import annotations

import re

import pandas as pd

_ZIP_COLS = ["LATEST_BILLING_ZIP", "LATEST_SHIPPING_ZIP", "ACCOUNT_ZIP"]
_COUNTRY_COLS = ["LATEST_BILLING_ADDRESS4", "LATEST_SHIPPING_ADDRESS4"]
_PHONE_COL = "PHONE"
_US_COUNTRY = {"US", "USA", "U.S.", "U.S.A.", "UNITED STATES", "UNITED STATES OF AMERICA", "AMERICA"}
_US_ZIP = re.compile(r"^\d{5}(-?\d{4})?$")


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or not str(v).strip()


def _is_us_zip(v) -> bool:
    return not _blank(v) and bool(_US_ZIP.match(str(v).strip()))


def _is_us_phone(v) -> bool:
    if _blank(v):
        return False
    s = re.sub(r"[^0-9+]", "", str(v))
    if s.startswith("00"):
        s = "+" + s[2:]
    return s.startswith("+1") and len(re.sub(r"\D", "", s)) >= 11   # +1 plus 10 local digits


def _country_state(v) -> str:
    """'us' / 'foreign' / '' (unknown) for one country cell."""
    if _blank(v):
        return ""
    return "us" if str(v).strip().upper() in _US_COUNTRY else "foreign"


def us_nexus_mask(df: pd.DataFrame):
    """Boolean Series: True where the row is independently pinned to the US.

    Returns None when the frame has none of the geo columns to judge on (e.g. a minimal test
    frame) — the caller then leaves the name match ungated rather than suppressing everything.
    """
    zip_cols = [c for c in _ZIP_COLS if c in df.columns]
    country_cols = [c for c in _COUNTRY_COLS if c in df.columns]
    has_phone = _PHONE_COL in df.columns
    if not zip_cols and not country_cols and not has_phone:
        return None

    country_us = pd.Series(False, index=df.index)
    country_foreign = pd.Series(False, index=df.index)
    for c in country_cols:
        st = df[c].map(_country_state)
        country_us = country_us | (st == "us")
        country_foreign = country_foreign | (st == "foreign")

    us_zip = pd.Series(False, index=df.index)
    for c in zip_cols:
        us_zip = us_zip | df[c].map(_is_us_zip)

    phone_us = df[_PHONE_COL].map(_is_us_phone) if has_phone else pd.Series(False, index=df.index)

    # explicit US country or +1 phone always count; a US-format ZIP counts unless a country
    # field explicitly names a non-US country (which would make a 5-digit code an EU postcode).
    return country_us | phone_us | (us_zip & ~country_foreign)


def gate(df: pd.DataFrame, flag) -> "pd.Series":
    """AND a name-match boolean Series with the US-nexus mask (no-op when the mask is None)."""
    mask = us_nexus_mask(df)
    flag = pd.Series(list(flag), index=df.index)
    return flag if mask is None else (flag & mask)
