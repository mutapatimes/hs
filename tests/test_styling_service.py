"""Tests for the styling-service (B2B trade-account) signal."""
import pandas as pd

from scoring.combine import REASONS_COL, score_customers
from scoring.signals.styling_service import flag_styling_service


def test_known_agency_flags_as_b2b():
    out = score_customers(pd.DataFrame([{
        "Name": "Buyer", "Spent": 900, "EMAIL_ADDR": "vip@threadsstyling.com",
    }]))
    reasons = out.loc[0, REASONS_COL]
    assert "Styling service (B2B): Threads Styling" in reasons
    assert "Custom domain" not in reasons        # not double-flagged as custom


def test_flag_and_missing_column():
    df = pd.DataFrame({"EMAIL_ADDR": ["a@thechapar.com", "b@gmail.com"]})
    out = flag_styling_service(df)
    assert out["styling_service"].tolist() == [True, False]
    assert "The Chapar" in str(out.loc[0, "styling_service_reason"])
    assert not flag_styling_service(pd.DataFrame({"x": [1]}))["styling_service"].any()
