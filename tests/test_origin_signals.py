"""Regression guard: origin-proxy signals are OFF by default.

Halia is lawful-by-default. Signals that sort by national / ethnic / name origin
(see ``scoring.combine.ORIGIN_PROXY_SIGNALS``) must never apply, score, or appear in
``reasons`` through the default ``score_customers(df)`` path. They are only re-enabled
when a caller explicitly opts in (``include_origin=True``) for a tenant that has
documented a lawful basis. If anyone reintroduces them by default, these tests fail.
"""
import pandas as pd

from scoring.combine import (
    CORE_DATA_ONLY,
    COUNT_COL,
    HIDDEN_COL,
    ORIGIN_PROXY_SIGNALS,
    PARKED_SIGNALS,
    REASONS_COL,
    SCORE_COL,
    SIGNAL_WEIGHTS,
    active_signals,
    score_customers,
)


def _blank_row(**overrides):
    # Defaults trip NO signal: free-mail address, ordinary UK postcode, UK country.
    row = {
        "Name": "Jane Smith",
        "Spent": 100,
        "EMAIL_ADDR": "jane@gmail.com",
        "LATEST_BILLING_ZIP": "E14 9GU",
        "LATEST_BILLING_ADDRESS4": "United Kingdom",
        "LATEST_SHIPPING_ADDRESS3": "London",
        "LATEST_SHIPPING_ADDRESS4": "United Kingdom",
        "LATEST_SHIPPING_ZIP": "E14 9GU",
        "PHONE": "+44 7700 900000",   # a mobile — trips no signal (a landline would)
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_gcc_billing_does_not_fire_by_default():
    # A customer whose ONLY tell is a GCC billing country (an origin proxy).
    df = _blank_row(LATEST_BILLING_ADDRESS4="Qatar")
    out = score_customers(df)  # default: include_origin=False
    assert out.loc[0, COUNT_COL] == 0
    assert out.loc[0, SCORE_COL] == 0
    assert out.loc[0, REASONS_COL] == ""
    assert not out.loc[0, HIDDEN_COL]


def test_gcc_billing_fires_only_when_opted_in():
    df = _blank_row(LATEST_BILLING_ADDRESS4="Qatar")
    out = score_customers(df, include_origin=True)
    assert out.loc[0, COUNT_COL] == 1
    assert out.loc[0, SCORE_COL] == SIGNAL_WEIGHTS["gcc_billing"]
    assert "GCC billing" in out.loc[0, REASONS_COL]
    assert out.loc[0, HIDDEN_COL]  # £100 spend + a signal -> hidden VIC


def test_reasons_never_carry_origin_proxies_by_default():
    # Trip several origin proxies at once; by default none should surface.
    df = _blank_row(
        Name="Jean de la Tour",                 # nobiliary_particle / name_structure
        LATEST_BILLING_ADDRESS4="United Arab Emirates",  # gcc_billing
        PHONE="+971 50 123 4567",               # phone_country
    )
    reasons = score_customers(df).loc[0, REASONS_COL]
    for term in ("GCC", "Prime Gulf", "Phone", "Nobiliary", "Name", "Heritage", "currency"):
        assert term not in reasons


def test_active_signals_excludes_origin_proxies_by_default():
    default_keys = {s[0] for s in active_signals()}
    assert ORIGIN_PROXY_SIGNALS.isdisjoint(default_keys)


def test_active_signals_restores_origin_proxies_when_opted_in():
    opted_keys = {s[0] for s in active_signals(include_origin=True)}
    # foreign_currency is also parked (CORE_DATA_ONLY), so it stays out even when opted in.
    expected = ORIGIN_PROXY_SIGNALS - (PARKED_SIGNALS if CORE_DATA_ONLY else set())
    assert expected.issubset(opted_keys)
