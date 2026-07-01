"""Wealth-management structure signal (Bucket 2). Origin-neutral, on by default."""
import pandas as pd

from scoring.combine import REASONS_COL, score_customers
from scoring.signals.wealth_structure import FLAG_COL, TYPE_COL, flag_wealth_structure


def _row(**addr):
    base = {"Name": "A", "Email": "a@gmail.com", "Spent": 50}
    base.update(addr)
    return pd.DataFrame([base])


def test_named_structures_fire_alone():
    for text, typ in [("Rothschild Family Office", "family_office"),
                      ("The XYZ Trust Company", "trust_company"),
                      ("ABC Registered Agent Ltd", "registered_agent"),
                      ("Fiduciaire de Genève", "fiduciary")]:
        out = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1=text))
        assert out[FLAG_COL].iloc[0] is True or bool(out[FLAG_COL].iloc[0])
        assert out[TYPE_COL].iloc[0] == typ


def test_reason_is_factual():
    out = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="Smith Family Office"))
    assert out["wealth_structure_reason"].iloc[0] == "Address routed through a family office"


def test_offshore_pobox_needs_offshore_jurisdiction():
    # PO box alone: does NOT fire (too common).
    plain = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="PO Box 100",
                                       LATEST_BILLING_ADDRESS4="United Kingdom"))
    assert not bool(plain[FLAG_COL].iloc[0])
    # PO box + offshore jurisdiction: fires.
    off = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="P.O. Box 3175",
                                     LATEST_BILLING_ADDRESS2="Road Town, Tortola",
                                     LATEST_BILLING_ADDRESS4="British Virgin Islands"))
    assert bool(off[FLAG_COL].iloc[0]) and off[TYPE_COL].iloc[0] == "offshore_pobox"


def test_ordinary_address_does_not_fire():
    out = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="12 Acacia Avenue",
                                     LATEST_BILLING_ADDRESS4="United Kingdom"))
    assert not bool(out[FLAG_COL].iloc[0])


def test_fires_by_default_in_combine():
    reasons = score_customers(_row(LATEST_BILLING_ADDRESS1="Rothschild Family Office")).loc[0, REASONS_COL]
    assert "Wealth structure" in reasons and "family office" in reasons
