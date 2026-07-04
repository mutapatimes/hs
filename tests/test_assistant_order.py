"""Tests for the corroboration-only assistant/PA-order signal."""
import pandas as pd

from scoring.combine import COUNT_COL, HIDDEN_COL, score_customers
from scoring.signals.assistant_order import detect, flag_assistant_order


# --- detection --------------------------------------------------------------
def test_detects_co_address_pa_name_and_role_email():
    assert detect("Jane Doe", "x@gmail.com", "Lansdowne House | c/o John Smith")[0]
    assert detect("Sarah Jenkins (PA to CEO)", "s@x.com", "1 St")[0]
    assert detect("Mark Davis (EA)", "m@x.com", "1 St")[0]
    assert detect("Bob", "ea.to.md@firm.com", "1 St")[0]
    assert detect("Bob", "pa.team@firm.com", "1 St")[0]
    r = detect("Jane", "execoffice@firm.co.uk", "1 St")
    assert r[0] and "role email" in r[1]


def test_detects_pa_mailbox_and_assistant_substring():
    assert detect("Bob", "pa@doverstreetmarket.com", "1 St")[0]        # email starts with "pa@"
    assert detect("Bob", "executiveassistant@x.com", "1 St")[0]        # "assistant" as a substring
    assert detect("Bob", "assistant.to.ceo@x.com", "1 St")[0]


def test_detects_the_household_staff_ecosystem():
    for local in ("ea", "exec", "office", "diary", "scheduling", "chiefofstaff",   # exec office
                  "housemanager", "estatemanager", "butler", "housekeeper",         # household & estate
                  "household", "residence", "nanny", "chauffeur", "wardrobe",
                  "crew", "captain", "chiefsteward", "chalet", "villa",              # yacht / property
                  "concierge", "lifestyle", "members",                              # private concierge
                  "curator", "collection", "stables", "groom",                      # collection / equestrian
                  "chef", "trustee",                                                # chef / fiduciary
                  "officeofjohnsmith", "jsmith.office", "the.smith-estateoffice"):  # spelled-out office-of
        assert detect("Bob", f"{local}@x.com", "1 St")[0], local


def test_address_notes_and_office_of_name():
    assert detect(None, "x@gmail.com", "1 St, office of Lord A")[0]
    assert detect("Office of Lord Ashcroft", "x@gmail.com", "1 St")[0]
    assert detect(None, "x@gmail.com", "Please leave with the housekeeper")[0]
    assert detect(None, "x@gmail.com", "Deliver to the staff entrance")[0]


def test_order_note_staff_phrasing_fires():
    # Staff placing the order surfaces in the note / gift message.
    assert detect("Jane", "jane@gmail.com", "1 St", "Ordering on behalf of Mr Rothschild")[0]
    assert detect("Jane", "jane@gmail.com", "1 St", "Please deliver to his office")[0]
    r = detect("Jane", "jane@gmail.com", "1 St", "Gift for Lord Ashcroft — leave with the concierge")
    assert r[0] and "order note" in r[1]
    assert detect("Jane", "jane@gmail.com", "1 St", "c/o the housekeeper, side gate")[0]


def test_plain_gift_notes_do_not_fire():
    assert detect("John Smith", "john@gmail.com", "1 St", "Happy birthday! Love, the team") == (False, None)
    assert detect("John Smith", "john@gmail.com", "1 St", "Please gift wrap and no receipt") == (False, None)
    assert detect("John Smith", "john@gmail.com", "1 St", "Leave at the front door if out") == (False, None)


def test_flag_frame_reads_order_note_column():
    df = pd.DataFrame({
        "Name": ["Jo Bloggs", "Jo Bloggs"],
        "EMAIL_ADDR": ["jo@gmail.com", "jo@gmail.com"],
        "ORDER_NOTE": ["on behalf of Mr X", "just a normal note"],
    })
    out = flag_assistant_order(df)
    assert out["assistant_order"].tolist() == [True, False]


def test_plain_orders_and_lookalike_emails_do_not_fire():
    assert detect("John Smith", "john@gmail.com", "1 Normal Road, London") == (False, None)
    assert detect("Paul Sean", "paul@gmail.com", "1 St") == (False, None)   # 'pa' prefix, not "pa@"
    assert detect("Pat", "pat@x.com", "1 St") == (False, None)              # 'pa' prefix, not "pa@"
    assert detect("Papa Tortelli", "sean@x.com", "1 St") == (False, None)
    for local in ("realestate", "collections", "helpdesk", "trustpilot", "grooming", "chelsea"):
        assert detect("Bob", f"{local}@x.com", "1 Normal Road") == (False, None), local


def test_flag_frame_and_missing_columns():
    df = pd.DataFrame({"Name": ["Anne (EA)", "Jo Bloggs"], "EMAIL_ADDR": ["a@x.com", "jo@gmail.com"]})
    out = flag_assistant_order(df)
    assert out["assistant_order"].tolist() == [True, False]
    assert not flag_assistant_order(pd.DataFrame({"x": [1]}))["assistant_order"].any()


# --- corroboration gate -----------------------------------------------------
def _row(**kw):
    base = {"Name": "x", "Spent": 100, "EMAIL_ADDR": "x@gmail.com",
            "LATEST_BILLING_ZIP": "LS1 1AA", "LATEST_BILLING_ADDRESS4": "United Kingdom"}
    base.update(kw)
    return base


def test_assistant_order_alone_never_flags():
    # Role email on a FREE provider -> no other signal -> uncorroborated, hidden.
    # (A role email on a custom/corporate domain WOULD be corroborated by
    #  custom_email — which is the right read: an assistant at a real firm.)
    out = score_customers(pd.DataFrame([_row(EMAIL_ADDR="pa.team@gmail.com")]))
    assert out.loc[0, COUNT_COL] == 0
    assert not out.loc[0, HIDDEN_COL]


def test_assistant_order_counts_when_corroborated():
    # Assistant email AT a wealth-employer domain -> work_email corroborates it.
    out = score_customers(pd.DataFrame([_row(EMAIL_ADDR="pa.to.md@gs.com")]))  # gs.com = Goldman
    assert out.loc[0, COUNT_COL] == 2     # work_email + assistant_order
