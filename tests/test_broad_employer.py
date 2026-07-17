"""Broad-employer tier: fires on big tech / enterprise / energy, but corroboration-only."""
import pandas as pd

from scoring.combine import score_customers
from scoring.signals.broad_employer import (
    FLAG_COL, REASON_COL, flag_broad_employer, load_domains,
)


def test_fires_on_domain_and_company_with_humanised_reason():
    domains = load_domains()
    df = pd.DataFrame([
        {"EMAIL_ADDR": "a@google.com", "COMPANY_NAME": ""},
        {"EMAIL_ADDR": "b@emea.shell.com", "COMPANY_NAME": ""},   # subdomain
        {"EMAIL_ADDR": "c@gmail.com", "COMPANY_NAME": "Salesforce"},  # named in company field
        {"EMAIL_ADDR": "d@gmail.com", "COMPANY_NAME": ""},        # nothing
    ])
    out = flag_broad_employer(df, domains)
    assert out[FLAG_COL].tolist() == [True, True, True, False]
    assert out.loc[0, REASON_COL] == "Google (big tech)"
    assert out.loc[1, REASON_COL] == "Shell (energy)"
    assert "Salesforce" in out.loc[2, REASON_COL]


def test_corroboration_gate_neutralises_it_alone_but_counts_with_a_core_signal():
    """A broad-employer email alone must NOT surface anyone; with a core signal it counts."""
    df = pd.DataFrame([
        # row 0: only the broad-employer email, no stronger signal -> gated away
        {"EMAIL_ADDR": "a@google.com", "COMPANY_NAME": ""},
        # row 1: broad-employer email PLUS a core work_email (Goldman named in company) -> counts
        {"EMAIL_ADDR": "b@google.com", "COMPANY_NAME": "Goldman Sachs"},
    ])
    scored = score_customers(df)
    # the gate overwrites the flag with (fired AND a core signal also fired)
    assert bool(scored.loc[0, FLAG_COL]) is False   # neutralised: no core signal
    assert bool(scored.loc[1, FLAG_COL]) is True    # kept: Goldman work_email corroborates
    # and it never lifts row 0's score on its own
    assert scored.loc[0, "signal_score"] == 0
    assert scored.loc[1, "signal_score"] > 0
