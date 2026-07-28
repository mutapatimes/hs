"""Wealth-management structure signal (Bucket 2). Origin-neutral, on by default."""
import pandas as pd
import pytest

from scoring.combine import REASONS_COL, score_customers
from scoring.signals.wealth_structure import (
    _OFFSHORE,
    FLAG_COL,
    REASON_COL,
    TYPE_COL,
    flag_wealth_structure,
)


def _row(**addr):
    base = {"Name": "A", "Email": "a@gmail.com", "Spent": 50}
    base.update(addr)
    return pd.DataFrame([base])


def test_named_structures_fire_alone():
    for text, typ in [("Rothschild Family Office", "family_office"),
                      ("The XYZ Trust Company", "trust_company"),
                      ("ABC Registered Agent Ltd", "registered_agent"),
                      ("Fiduciaire de Genève", "fiduciary"),
                      ("Smith Private Trust Company", "private_trust_company"),
                      ("Meridian Corporate Trustees Ltd", "corporate_trustee"),
                      ("Trident Corporate Services", "corporate_services"),
                      ("The Family Private Office", "private_office"),
                      ("Familie Müller Stiftung", "foundation"),
                      ("Vermögens Anstalt", "foundation")]:
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


@pytest.mark.parametrize("jurisdiction,display", [
    ("Bahamas", "Bahamas"),
    ("Nassau, Bahamas", "Bahamas"),
    ("Providenciales, Turks and Caicos", "Turks and Caicos"),
    ("Gibraltar", "Gibraltar"),
    ("Douglas, Isle of Man", "Isle of Man"),
    ("Charlestown, Nevis", "Nevis"),
    ("Vaduz, Liechtenstein", "Liechtenstein"),
])
def test_expanded_offshore_jurisdictions_fire(jurisdiction, display):
    out = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="PO Box 42",
                                     LATEST_BILLING_ADDRESS2=jurisdiction))
    assert bool(out[FLAG_COL].iloc[0]) and out[TYPE_COL].iloc[0] == "offshore_pobox"
    # Reason names the jurisdiction cleanly (no title-case mangling of multi-word territories).
    assert out[REASON_COL].iloc[0] == f"Address is an offshore PO box ({display})"


@pytest.mark.parametrize("addr2,addr3", [
    ("Newark, New Jersey", "United States"),   # not the Channel Island of Jersey
    ("Panama City", "FL 32401"),               # Florida resort, not the Republic of Panama
    ("Panama City Beach", "FL"),
    ("Garden City, Nassau", "NY 11530"),       # Nassau County, NY, not the Bahamian capital
    ("Bermuda Dunes", "CA 92203"),             # Riverside County, CA
])
def test_us_placename_collisions_do_not_fire(addr2, addr3):
    """A PO box at an affluent US place that merely shares a name with an offshore territory must
    not be read as offshore — a false flag there discredits the whole signal."""
    out = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="PO Box 12",
                                     LATEST_BILLING_ADDRESS2=addr2, LATEST_BILLING_ADDRESS3=addr3))
    assert not bool(out[FLAG_COL].iloc[0])


@pytest.mark.parametrize("addr2,addr3,display", [
    ("St Helier", "Jersey", "Jersey"),
    ("Panama City", "Panama", "Panama"),        # the capital still fires on the trailing country
    ("Nassau", "Bahamas", "Bahamas"),           # the capital still fires on the country name
    ("Hamilton", "Bermuda", "Bermuda"),
])
def test_real_offshore_still_fires_past_the_collision_guards(addr2, addr3, display):
    out = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="PO Box 500",
                                     LATEST_BILLING_ADDRESS2=addr2, LATEST_BILLING_ADDRESS3=addr3))
    assert bool(out[FLAG_COL].iloc[0]) and out[REASON_COL].iloc[0] == \
        f"Address is an offshore PO box ({display})"


@pytest.mark.parametrize("token,display", sorted(_OFFSHORE.items()))
def test_every_offshore_token_fires_with_a_clean_reason(token, display):
    """Completeness guard: each token in the map must actually match, and its reason must read
    cleanly (no title-case mangling like 'Isle Of Man'). Catches a future addition that mistypes
    a token so it never fires, or gives it an ugly display string."""
    address = token.title()  # "ISLE OF MAN" -> "Isle Of Man", a plausible address fragment
    out = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="PO Box 1",
                                     LATEST_BILLING_ADDRESS2=address))
    assert bool(out[FLAG_COL].iloc[0]), f"{token} did not fire"
    reason = out[REASON_COL].iloc[0]
    assert reason == f"Address is an offshore PO box ({display})"
    # A clean display name: no stray title-case artefacts and no doubled spaces.
    assert "  " not in display and display == _OFFSHORE[token]


def test_ordinary_address_does_not_fire():
    out = flag_wealth_structure(_row(LATEST_BILLING_ADDRESS1="12 Acacia Avenue",
                                     LATEST_BILLING_ADDRESS4="United Kingdom"))
    assert not bool(out[FLAG_COL].iloc[0])


def test_fires_by_default_in_combine():
    reasons = score_customers(_row(LATEST_BILLING_ADDRESS1="Rothschild Family Office")).loc[0, REASONS_COL]
    assert "Wealth structure" in reasons and "family office" in reasons
