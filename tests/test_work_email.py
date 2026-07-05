"""Tests for the work-email-domain signal.

Domains are REAL (all present in sample_data/sample.xlsx), but the local-parts
are synthetic — the signal only looks at the domain, and committing customers'
actual email addresses would leak PII into git.
"""
import pandas as pd

from scoring.signals.work_email import (
    FLAG_COL,
    REASON_COL,
    employer_names,
    flag_work_email,
    load_domains,
    match_company,
    match_email,
)

# (email, should_match_against_the_shipped_reference_list)
ROWS = [
    ("ceo@carlsoncapital.com", True),       # Carlson Capital (hedge fund)
    ("partner@calculuscapital.com", True),  # Calculus Capital (private equity)
    ("analyst@sparkcapital.com", True),     # Spark Capital (private equity/VC)
    ("someone@gmail.com", False),           # personal
    ("someone@qq.com", False),              # personal
    ("staff@doverstreetmarket.com", False), # the retailer's OWN domain
    ("someone@icloud.com", False),          # personal
    ("someone@hotmail.co.uk", False),       # personal
    ("someone@163.com", False),             # personal
    ("someone@btinternet.com", False),      # personal
]


def test_ten_real_domain_rows_against_shipped_list():
    domains = load_domains()
    df = pd.DataFrame({"EMAIL_ADDR": [e for e, _ in ROWS]})

    result = flag_work_email(df, domains)

    assert result[FLAG_COL].tolist() == [should for _, should in ROWS]

    flagged = result[result[FLAG_COL]]
    assert len(flagged) == 3
    reasons = dict(zip(flagged["EMAIL_ADDR"], flagged[REASON_COL]))
    assert reasons["ceo@carlsoncapital.com"] == "Carlson Capital (hedge_fund)"
    assert reasons["partner@calculuscapital.com"] == "Calculus Capital (private_equity)"


def test_subdomain_matches_parent():
    domains = load_domains()
    matched, reason = match_email("j.smith@emea.gs.com", domains)
    assert matched and reason == "Goldman Sachs (banking)"


def test_lookalike_domain_does_not_match():
    domains = load_domains()
    # 'notgs.com' must not match 'gs.com'.
    assert match_email("x@notgs.com", domains) == (False, None)


def test_blank_or_malformed_email_not_flagged():
    domains = load_domains()
    assert match_email(None, domains) == (False, None)
    assert match_email("not-an-email", domains) == (False, None)
    assert match_email("", domains) == (False, None)


# --- company-field matching (A1) -------------------------------------------
def test_employer_named_in_company_field_fires_on_free_email():
    domains = load_domains()
    df = pd.DataFrame({
        "EMAIL_ADDR": ["a@gmail.com", "b@gmail.com", "c@gmail.com"],
        "COMPANY_NAME": ["Goldman Sachs International", "Bob's Plumbing Ltd", None],
    })
    out = flag_work_email(df, domains)
    assert out[FLAG_COL].tolist() == [True, False, False]
    assert "Goldman Sachs" in out.loc[0, REASON_COL] and "company field" in out.loc[0, REASON_COL]


def test_short_or_ambiguous_employer_names_are_skipped():
    domains = load_domains()
    names = employer_names(domains)
    # distinctive names kept; short single tokens (e.g. UBS, GS) skipped as collision-prone.
    assert match_company("UBS", names) == (False, None)
    assert match_company("GS Retail", names) == (False, None)
    assert match_company(None, names) == (False, None)
