"""Origin-adjacent prime district signal (Bucket 3) — GATED off by default (Gulf, Lebanon, …)."""
import pandas as pd

from scoring.combine import (
    COUNT_COL,
    ORIGIN_PROXY_SIGNALS,
    REASONS_COL,
    active_signals,
    score_customers,
)
from scoring.signals.origin_adjacent_district import FLAG_COL, flag_origin_adjacent_district


def _row(**addr):
    base = {"Name": "A", "Email": "a@gmail.com", "Spent": 50}
    base.update(addr)
    return pd.DataFrame([base])


def test_is_a_gated_origin_proxy():
    assert "origin_adjacent_district" in ORIGIN_PROXY_SIGNALS
    assert "origin_adjacent_district" not in {s[0] for s in active_signals()}
    assert "origin_adjacent_district" in {s[0] for s in active_signals(include_origin=True)}


def test_matches_gulf_district_by_name_country_guarded():
    out = flag_origin_adjacent_district(_row(LATEST_BILLING_ADDRESS1="Villa 12, Palm Jumeirah",
                                             LATEST_BILLING_ADDRESS4="UAE"))
    assert bool(out[FLAG_COL].iloc[0])
    assert out["origin_adjacent_district_reason"].iloc[0] == "Palm Jumeirah (UAE)"


def test_matches_lebanon_district_now_gated():
    # Lebanon was moved out of the on-by-default hnw_areas into this gated signal.
    out = flag_origin_adjacent_district(_row(LATEST_BILLING_ADDRESS2="Achrafieh, Beirut",
                                             LATEST_BILLING_ADDRESS4="Lebanon"))
    assert bool(out[FLAG_COL].iloc[0]) and "Achrafieh" in out["origin_adjacent_district_reason"].iloc[0]


def test_matches_gulf_postcode():
    out = flag_origin_adjacent_district(_row(LATEST_BILLING_ZIP="11693",
                                             LATEST_BILLING_ADDRESS4="Saudi Arabia"))
    assert bool(out[FLAG_COL].iloc[0])


def test_does_not_fire_by_default_but_fires_when_opted_in():
    df = _row(LATEST_BILLING_ADDRESS1="Emirates Hills", LATEST_BILLING_ADDRESS4="UAE")
    assert score_customers(df).loc[0, COUNT_COL] == 0            # gated off
    opted = score_customers(df, include_origin=True)
    assert "Prime residential district" in opted.loc[0, REASONS_COL]  # available on opt-in


def test_lebanon_no_longer_scores_by_default():
    # Regression: an Achrafieh address must NOT surface on the default path any more.
    df = _row(LATEST_BILLING_ADDRESS2="Achrafieh", LATEST_BILLING_ADDRESS4="Lebanon")
    assert score_customers(df).loc[0, COUNT_COL] == 0


def test_reason_is_factual():
    out = flag_origin_adjacent_district(_row(LATEST_BILLING_ADDRESS1="Downtown Dubai",
                                             LATEST_BILLING_ADDRESS4="UAE"))
    r = str(out["origin_adjacent_district_reason"].iloc[0]).lower()
    assert "tax haven" not in r and "offshore" not in r
