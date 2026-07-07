"""Known-VIPs demo strip: sample dashboards also show high spenders whose evidence is strong."""
from __future__ import annotations

import pandas as pd

from build_mvp import known_vips_strip, render_dashboard
from scoring.combine import score_customers


def _scored(spent: float):
    # A talent-mgmt domain makes the evidence strong; Spent controls hidden vs known.
    return score_customers(pd.DataFrame([{
        "Name": "Kiari Cephus", "Spent": spent, "EMAIL_ADDR": "k@blvdmgmt.com",
        "LATEST_BILLING_ZIP": "SW10 9SJ",
    }]))


def test_known_high_spender_appears_in_strip():
    html = known_vips_strip(_scored(spent=10_000))     # above the VIC threshold: known client
    assert "Known VIPs, understood" in html
    assert "Kiari Cephus" in html
    assert "blvdmgmt.com" in html                      # the reason chips travel with the card


def test_hidden_vic_is_not_a_known_client():
    assert known_vips_strip(_scored(spent=100)) == ""  # low spend -> hidden list, strip empty


def test_strip_renders_into_the_sample_page_only_when_populated():
    scored = _scored(spent=10_000)
    assert "Known VIPs, understood" in render_dashboard(scored)
    assert "Known VIPs, understood" not in render_dashboard(_scored(spent=100))


def test_missing_columns_are_safe():
    assert known_vips_strip(pd.DataFrame({"x": [1]})) == ""
