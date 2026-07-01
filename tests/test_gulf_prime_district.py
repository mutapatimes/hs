"""Prime Gulf district signal (Bucket 3) — GATED off by default."""
import pandas as pd

from scoring.combine import (
    COUNT_COL,
    ORIGIN_PROXY_SIGNALS,
    REASONS_COL,
    active_signals,
    score_customers,
)
from scoring.signals.gulf_prime_district import FLAG_COL, flag_gulf_prime_district


def _row(**addr):
    base = {"Name": "A", "Email": "a@gmail.com", "Spent": 50}
    base.update(addr)
    return pd.DataFrame([base])


def test_is_a_gated_origin_proxy():
    assert "gulf_prime_district" in ORIGIN_PROXY_SIGNALS
    assert "gulf_prime_district" not in {s[0] for s in active_signals()}
    assert "gulf_prime_district" in {s[0] for s in active_signals(include_origin=True)}


def test_matches_district_by_name_country_guarded():
    out = flag_gulf_prime_district(_row(LATEST_BILLING_ADDRESS1="Villa 12, Palm Jumeirah",
                                        LATEST_BILLING_ADDRESS4="UAE"))
    assert bool(out[FLAG_COL].iloc[0])
    assert "prime residential district" in out["gulf_prime_district_reason"].iloc[0]


def test_matches_gulf_postcode():
    out = flag_gulf_prime_district(_row(LATEST_BILLING_ZIP="11693",
                                        LATEST_BILLING_ADDRESS4="Saudi Arabia"))
    assert bool(out[FLAG_COL].iloc[0])


def test_does_not_fire_by_default_but_fires_when_opted_in():
    df = _row(LATEST_BILLING_ADDRESS1="Emirates Hills", LATEST_BILLING_ADDRESS4="UAE")
    assert score_customers(df).loc[0, COUNT_COL] == 0            # gated off
    opted = score_customers(df, include_origin=True)
    assert "Prime Gulf district" in opted.loc[0, REASONS_COL]     # available on opt-in


def test_reason_is_factual():
    out = flag_gulf_prime_district(_row(LATEST_BILLING_ADDRESS1="Downtown Dubai",
                                        LATEST_BILLING_ADDRESS4="UAE"))
    r = out["gulf_prime_district_reason"].iloc[0].lower()
    assert "tax haven" not in r and "offshore" not in r
