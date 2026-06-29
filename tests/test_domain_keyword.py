"""Tests for the high-earning domain-keyword signal."""
import pandas as pd

from config import ELITE_FINANCE_KEYWORDS_FILE, HIGH_EARNING_KEYWORDS_FILE
from scoring.combine import REASONS_COL, SCORE_COL, score_customers
from scoring.signals.domain_keyword import flag_domain_keyword, match_domain, load_keywords
from scoring.signals.custom_email import load_excluded


def _lists():
    return (load_keywords(HIGH_EARNING_KEYWORDS_FILE),
            load_keywords(ELITE_FINANCE_KEYWORDS_FILE), load_excluded())


def test_matches_finance_keywords_in_custom_domains():
    g, e, ex = _lists()
    for email in ["a@mercury-capital.com", "b@redwoodequity.com",
                  "c@andersenpartners.com", "d@x-ventures.io", "e@northwealth.co.uk"]:
        assert match_domain(email, g, e, ex)[0], email


def test_ignores_generic_and_known_domains():
    g, e, ex = _lists()
    assert not match_domain("a@gmail.com", g, e, ex)[0]          # free
    assert not match_domain("b@bobsplumbing.com", g, e, ex)[0]   # generic custom
    assert not match_domain("c@adventures.com", g, e, ex)[0]     # false-friend (stoplist)


def test_elite_tier_detected_with_marker():
    g, e, ex = _lists()
    for email in ["a@apex-privateequity.com", "b@private-equity.com",
                  "c@redwoodhedgefund.com", "d@smith-familyoffice.com"]:
        hit, reason, tier = match_domain(email, g, e, ex)
        assert hit and tier == "elite", email
        assert "elite finance" in reason


def test_elite_outranks_general_outranks_generic():
    elite = score_customers(pd.DataFrame([{"Name": "A", "Spent": 200,
        "EMAIL_ADDR": "a@apex-privateequity.com"}])).iloc[0]
    general = score_customers(pd.DataFrame([{"Name": "B", "Spent": 200,
        "EMAIL_ADDR": "b@apex-capital.com"}])).iloc[0]
    generic = score_customers(pd.DataFrame([{"Name": "C", "Spent": 200,
        "EMAIL_ADDR": "c@bobsplumbing.com"}])).iloc[0]
    # elite (3) + custom 0.5 = 3.5 ; general (2) + custom 0.5 = 2.5 ; a bare custom
    # domain is corroboration-only now, so a generic custom domain alone scores 0.
    assert float(elite[SCORE_COL]) == 3.5
    assert float(general[SCORE_COL]) == 2.5
    assert float(generic[SCORE_COL]) == 0.0


def test_finance_domain_outranks_generic_custom_domain():
    finance = score_customers(pd.DataFrame([{"Name": "A", "Spent": 200,
        "EMAIL_ADDR": "a@mercury-capital.com"}])).iloc[0]
    generic = score_customers(pd.DataFrame([{"Name": "B", "Spent": 200,
        "EMAIL_ADDR": "b@bobsplumbing.com"}])).iloc[0]
    assert float(finance[SCORE_COL]) > float(generic[SCORE_COL])
    assert "High-earning domain" in finance[REASONS_COL]


def test_grouped_with_custom_email_no_double_count():
    # domain_keyword (2) + custom_email (1) grouped -> 2 + 0.5 = 2.5, not 3.
    r = score_customers(pd.DataFrame([{"Name": "A", "Spent": 200,
        "EMAIL_ADDR": "a@apex-capital.com"}])).iloc[0]
    assert float(r[SCORE_COL]) == 2.5


def test_missing_column_is_dormant():
    assert not flag_domain_keyword(pd.DataFrame({"x": [1]}))["domain_keyword"].any()
