"""Name-mismatch: the email's implied person differs from the account name (corroboration-only)."""
import pandas as pd

from scoring.combine import COUNT_COL, HIDDEN_COL, score_customers
from scoring.signals.name_mismatch import detect, flag_name_mismatch


# --- detection --------------------------------------------------------------
def test_fires_when_email_name_differs_from_account():
    hit, reason = detect("Mr David Rothschild", "sarah.jones@x.com")
    assert hit and "sarah" in reason and "Rothschild" in reason


def test_does_not_fire_when_names_overlap():
    assert detect("Sarah Jones", "sarah.jones@x.com") == (False, None)     # same person
    assert detect("Jane Doe", "john.doe@x.com") == (False, None)           # shared surname (household)
    assert detect("David Rothschild", "d.rothschild@x.com") == (False, None)


def test_ignores_role_and_function_mailboxes():
    assert detect("David Rothschild", "pa.jones@x.com") == (False, None)   # role -> assistant_order's job
    assert detect("David Rothschild", "office@x.com") == (False, None)
    assert detect("David Rothschild", "sales.team@x.com") == (False, None)  # generic function


def test_needs_a_structured_two_token_name():
    assert detect("David Rothschild", "sarah@x.com") == (False, None)       # single token -> not confident
    assert detect("David Rothschild", "jazzcat88@x.com") == (False, None)   # handle, not a name


def test_flag_frame_and_missing_columns():
    df = pd.DataFrame({"Name": ["David Rothschild", "Sarah Jones"],
                       "EMAIL_ADDR": ["sarah.jones@x.com", "sarah.jones@x.com"]})
    out = flag_name_mismatch(df)
    assert out["name_mismatch"].tolist() == [True, False]
    assert not flag_name_mismatch(pd.DataFrame({"x": [1]}))["name_mismatch"].any()


# --- corroboration gate -----------------------------------------------------
def _row(**kw):
    base = {"Name": "David Rothschild", "Spent": 100, "EMAIL_ADDR": "sarah.jones@gmail.com",
            "LATEST_BILLING_ZIP": "LS1 1AA", "LATEST_BILLING_ADDRESS4": "United Kingdom"}
    base.update(kw)
    return base


def test_name_mismatch_alone_never_flags():
    # A mismatch on a free provider with no other signal -> uncorroborated, hidden.
    out = score_customers(pd.DataFrame([_row()]))
    assert out.loc[0, COUNT_COL] == 0 and not out.loc[0, HIDDEN_COL]


def test_name_mismatch_counts_when_corroborated():
    # Mismatch AND a work/wealth email domain -> work_email corroborates it.
    out = score_customers(pd.DataFrame([_row(EMAIL_ADDR="sarah.jones@gs.com")]))  # gs.com = Goldman
    assert out.loc[0, COUNT_COL] == 2     # work_email + name_mismatch
