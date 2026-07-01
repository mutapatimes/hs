"""Geo-confirmation signal — agreement-as-confidence (origin fields corroborate, never originate).

A phone dialling code and an email country-code TLD are origin-correlated fields: they say where a
number/inbox was once registered, not where someone lives, and they are weaker evidence than an
operationally-verified address. So the class rule is absolute — **nothing derived from a phone or
email jurisdiction originates a score** (phone_country / phone_mismatch stay gated). This signal is
the one sanctioned on-by-default use: if a customer ALREADY fired a wealth-geography *address*
signal, and their phone (or email ccTLD) jurisdiction **agrees** with that address's country, the
agreement slightly raises confidence that this is genuine residence rather than a forwarding
address. It can only ever *agree* with — and help — a signal we've already justified; **disagreement
does nothing** (it never fires, no penalty, no mismatch). It is therefore a low-weight CORROBORATION
signal (SUPPORTING; never a sole basis), on by default, and not an origin proxy.

Precondition is enforced by reading the wealth-geo flag columns already present on the frame (this
signal runs last in scoring.combine.SIGNALS). Reason text is a bare fact: "Phone jurisdiction
consistent with billing address". See docs/geography-signal-taxonomy.md.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from config import CCTLD_COUNTRIES_FILE, DIALING_CODE_COUNTRIES_FILE
from scoring.signals import (
    hnw_area,
    hnwi_postcode,
    intl_postcode,
    prime_residence,
    property_value,
    us_zip,
    wealth_jurisdiction,
)
from scoring.signals.custom_email import _email_domain
from scoring.signals.gcc_billing import _normalize as _norm_country
from scoring.signals.phone_country import _normalize as _norm_phone

FLAG_COL = "geo_confirmation"
REASON_COL = "geo_confirmation_reason"

# The on-by-default wealth-geography ADDRESS signals this may confirm (gated Gulf is excluded
# deliberately — an on-by-default corroborator never reaches into the gated tier).
WEALTH_GEO_COLS = [
    wealth_jurisdiction.FLAG_COL, intl_postcode.FLAG_COL, hnwi_postcode.FLAG_COL,
    us_zip.FLAG_COL, hnw_area.MATCH_COL, prime_residence.MATCH_COL, property_value.FLAG_COL,
]
_COUNTRY_COLS = ["LATEST_BILLING_ADDRESS4", "LATEST_SHIPPING_ADDRESS4"]


def _load_map(path: Path | str, longest_first: bool = False) -> list[tuple[str, frozenset]]:
    """Read [(key, {normalized country aliases})]. Optionally longest-key-first (dialling codes)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Geo-confirmation reference not found: {path}")
    rows: list[tuple[str, frozenset]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            key = row[0].strip()
            if not key or key.startswith("#") or key in ("code", "cctld"):
                continue
            raw = row[1] if len(row) > 1 else ""
            countries = frozenset(c for c in (_norm_country(p) for p in raw.split(";")) if c)
            if countries:
                rows.append((key, countries))
    if longest_first:
        rows.sort(key=lambda r: -len(r[0]))
    return rows


def _phone_countries(phone: object, codes) -> frozenset:
    norm = _norm_phone(phone)
    if not norm.startswith("+"):
        return frozenset()
    for code, countries in codes:               # longest prefix first
        if norm.startswith(code):
            return countries
    return frozenset()


def _email_countries(email: object, cctlds: dict) -> frozenset:
    domain = _email_domain(email)
    if not domain or "." not in domain:
        return frozenset()
    return cctlds.get(domain.rsplit(".", 1)[-1].lower(), frozenset())


def flag_geo_confirmation(df: pd.DataFrame, codes=None, cctlds=None) -> pd.DataFrame:
    """Add geo_confirmation flag + factual reason. Fires only when a wealth-geo address signal
    already fired AND the phone/email jurisdiction agrees with the billing/shipping country."""
    if codes is None:
        codes = _load_map(DIALING_CODE_COUNTRIES_FILE, longest_first=True)
    if cctlds is None:
        cctlds = dict(_load_map(CCTLD_COUNTRIES_FILE))

    out = df.copy()
    n = len(out)
    geo_cols = [c for c in WEALTH_GEO_COLS if c in out.columns]
    if not geo_cols:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    geo_fired = out[geo_cols].fillna(False).astype(bool).any(axis=1).tolist()
    phones = out["PHONE"].tolist() if "PHONE" in out.columns else [None] * n
    emails = out["EMAIL_ADDR"].tolist() if "EMAIL_ADDR" in out.columns else [None] * n
    country_series = [out[c] if c in out.columns else pd.Series([None] * n, index=out.index)
                      for c in _COUNTRY_COLS]

    flags, reasons = [], []
    for i in range(n):
        if not geo_fired[i]:
            flags.append(False)
            reasons.append(None)
            continue
        addr = frozenset(v for v in (_norm_country(s.iloc[i]) for s in country_series) if v)
        if not addr:
            flags.append(False)
            reasons.append(None)
            continue
        if _phone_countries(phones[i], codes) & addr:
            flags.append(True)
            reasons.append("Phone jurisdiction consistent with billing address")
        elif _email_countries(emails[i], cctlds) & addr:
            flags.append(True)
            reasons.append("Email domain jurisdiction consistent with billing address")
        else:
            flags.append(False)
            reasons.append(None)
    out[FLAG_COL] = flags
    out[REASON_COL] = reasons
    return out
