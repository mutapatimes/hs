"""Geo-confirmation: agreement-as-confidence. Corroborates a wealth-geo address, never originates."""
import pandas as pd

from scoring.combine import (
    ORIGIN_PROXY_SIGNALS,
    REASONS_COL,
    SIGNALS,
    SUPPORTING_SIGNALS,
    active_signals,
    score_customers,
)
from scoring.signals import geo_confirmation as gc


def _row(**kw):
    base = {"Name": "A", "EMAIL_ADDR": "a@gmail.com", "Spent": 50}
    base.update(kw)
    return pd.DataFrame([base])


def test_on_by_default_supporting_not_origin_proxy():
    assert "geo_confirmation" in {s[0] for s in active_signals()}      # on by default
    assert "geo_confirmation" in SUPPORTING_SIGNALS                    # never a sole basis
    assert "geo_confirmation" not in ORIGIN_PROXY_SIGNALS              # not an origin proxy
    assert SIGNALS[-1][0] == "geo_confirmation"                        # must run last


def test_phone_agreement_confirms_a_high_value_address():
    out = score_customers(_row(LATEST_BILLING_ADDRESS4="Monaco", PHONE="+377 6 12 34 56"))
    assert "Geo confirmation: Phone jurisdiction consistent with billing address" in out.loc[0, REASONS_COL]


def test_disagreement_does_nothing():
    # Monaco address, UK phone: no agreement -> geo_confirmation must NOT fire, no penalty.
    out = score_customers(_row(LATEST_BILLING_ADDRESS4="Monaco", PHONE="+44 7700 900000"))
    assert "Geo confirmation" not in out.loc[0, REASONS_COL]
    assert "High-value area" in out.loc[0, REASONS_COL]  # the address itself still scores


def test_never_originates_without_a_wealth_geo_signal():
    # Phone agrees with country, but no wealth-geo address signal fired -> must not fire.
    out = score_customers(_row(LATEST_BILLING_ADDRESS4="United Kingdom", PHONE="+44 7700 900000"))
    assert "Geo confirmation" not in out.loc[0, REASONS_COL]


def test_email_cctld_agreement_confirms():
    out = score_customers(_row(EMAIL_ADDR="x@maison.fr",
                               LATEST_BILLING_ZIP="75116", LATEST_BILLING_ADDRESS4="France"))
    assert "Email domain jurisdiction consistent with billing address" in out.loc[0, REASONS_COL]


def test_email_cctld_disagreement_does_nothing():
    out = score_customers(_row(EMAIL_ADDR="x@haus.de",
                               LATEST_BILLING_ZIP="75116", LATEST_BILLING_ADDRESS4="France"))
    assert "Geo confirmation" not in out.loc[0, REASONS_COL]


def test_direct_flag_requires_geo_column_present():
    # With a wealth-geo flag column already set + agreeing phone, it fires.
    df = pd.DataFrame([{"wealth_jurisdiction": True, "LATEST_BILLING_ADDRESS4": "Monaco",
                        "PHONE": "+377 1", "EMAIL_ADDR": "a@gmail.com"}])
    out = gc.flag_geo_confirmation(df)
    assert bool(out[gc.FLAG_COL].iloc[0])
    # No wealth-geo column at all -> safe no-op.
    bare = gc.flag_geo_confirmation(pd.DataFrame([{"PHONE": "+377 1"}]))
    assert not bool(bare[gc.FLAG_COL].iloc[0])
