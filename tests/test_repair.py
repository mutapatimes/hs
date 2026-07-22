"""Deterministic data repair + record quality (scoring/repair.py).

The property that matters most is the conservative one: a repair may turn a provably malformed
value into a provably well-formed one, and must never rewrite a value that was already good or
guess between two equally plausible candidates. Most of these tests are there to hold that line.
"""
import pandas as pd

from scoring.repair import (FLAGS_COL, QUALITY_COL, REPAIRS_COL, quality_of, repair_email,
                            repair_frame, repair_name, repair_postcode)


# ── postcode ──────────────────────────────────────────────────────────────────
def test_postcode_glyph_confusions_are_recovered():
    assert repair_postcode("SW1A lAA")[0] == "SW1A 1AA"    # letter l typed for the digit 1
    assert repair_postcode("SW1A OAA")[0] == "SW1A 0AA"    # letter O typed for zero
    assert repair_postcode("0X1 3PN")[0] == "OX1 3PN"      # zero typed for the letter O
    assert repair_postcode("SW1A lAA")[1] == "glyph"


def test_junk_separators_are_stripped():
    fixed, rule = repair_postcode("SW1A-1AA")
    assert fixed == "SW1A 1AA" and rule == "spacing"
    assert repair_postcode("W1K.7TN")[0] == "W1K 7TN"


def test_spacing_alone_is_not_treated_as_damage():
    """The signals compact a postcode before comparing, so an unspaced or loosely spaced one
    already matches. Repairing it would be churn in the audit log for no gain."""
    assert repair_postcode("sw1a1aa") == (None, None)
    assert repair_postcode("  W1K   7TN ") == (None, None)


def test_postcode_already_valid_is_never_touched():
    for good in ("SW1A 1AA", "W1K 7TN", "EC4N 8AF", "M1 1AE"):
        assert repair_postcode(good) == (None, None)


def test_postcode_junk_is_left_alone():
    for junk in ("", "   ", "hello", "12345", "ABCDEFGH", None, "N/A"):
        assert repair_postcode(junk) == (None, None)


def test_postcode_repair_only_accepts_a_valid_result():
    # Coercing the unambiguous positions still doesn't produce a postcode, so nothing is claimed.
    assert repair_postcode("ZZZZ ZZZ") == (None, None)


# ── email ─────────────────────────────────────────────────────────────────────
def test_email_domain_typos_are_recovered():
    assert repair_email("grace@gmial.com")[0] == "grace@gmail.com"     # transposition
    assert repair_email("grace@gmai.com")[0] == "grace@gmail.com"      # deletion
    assert repair_email("grace@hotmial.com")[0] == "grace@hotmail.com"
    assert repair_email("grace@gmial.com")[1] == "domain"


def test_email_known_domain_is_never_touched():
    assert repair_email("grace@gmail.com") == (None, None)
    assert repair_email("grace@goldmansachs.com") == (None, None)      # unknown but plausible


def test_email_widens_to_a_caller_supplied_table():
    known = frozenset({"goldmansachs.com"})
    assert repair_email("g@goldmansach.com", known)[0] == "g@goldmansachs.com"
    assert repair_email("g@goldmansach.com")[0] is None                # not without the table


def test_email_ambiguity_is_left_alone():
    """One edit from two different real domains is a guess, not a repair."""
    known = frozenset({"abc.com", "abd.com"})
    assert repair_email("x@abe.com", known) == (None, None)


def test_email_junk_is_left_alone():
    for junk in ("", "no-at-sign", "@nolocal.com", "local@", None):
        assert repair_email(junk) == (None, None)


# ── name ──────────────────────────────────────────────────────────────────────
def test_single_case_names_are_recased():
    assert repair_name("GRACE LADOJA")[0] == "Grace Ladoja"
    assert repair_name("grace ladoja")[0] == "Grace Ladoja"
    assert repair_name("GRACE LADOJA")[1] == "case"


def test_name_particles_and_prefixes_survive_recasing():
    assert repair_name("LUDWIG VAN BEETHOVEN")[0] == "Ludwig van Beethoven"
    assert repair_name("fiona macleod")[0] == "Fiona MacLeod"
    assert repair_name("SEAN O'BRIEN")[0] == "Sean O'Brien"
    assert repair_name("anne smith-jones")[0] == "Anne Smith-Jones"


def test_mixed_case_names_are_left_exactly_as_typed():
    for good in ("Grace Ladoja", "Ludwig van Beethoven", "eBay Support", "Fiona MacLeod"):
        assert repair_name(good) == (None, None)


# ── quality ───────────────────────────────────────────────────────────────────
def _row(**kw):
    base = {"Name": "Grace Ladoja", "EMAIL_ADDR": "grace@x.com", "PHONE": "+44 7700 900123",
            "LATEST_BILLING_ZIP": "SW1A 1AA", "LATEST_SHIPPING_ZIP": ""}
    base.update(kw)
    return base


def test_a_complete_record_scores_full_marks():
    score, flags = quality_of(_row())
    assert score == 100 and flags == []


def test_placeholders_are_caught():
    score, flags = quality_of(_row(Name="test"))
    assert "placeholder name" in flags and score < 70
    assert "placeholder email" in quality_of(_row(EMAIL_ADDR="asdf@x.com"))[1]


def test_missing_fields_are_flagged_and_cost_score():
    score, flags = quality_of(_row(Name="", EMAIL_ADDR="", LATEST_BILLING_ZIP="", PHONE=""))
    assert {"no name", "no email", "no address", "no phone"} <= set(flags)
    assert score <= 30


def test_malformed_email_is_flagged():
    assert "malformed email" in quality_of(_row(EMAIL_ADDR="grace-at-x.com"))[1]


def test_quality_never_leaves_the_scale():
    score, _ = quality_of({"Name": "x", "EMAIL_ADDR": "n/a", "PHONE": "",
                           "LATEST_BILLING_ZIP": "zzz", "LATEST_SHIPPING_ZIP": ""})
    assert 0 <= score <= 100


# ── the whole-book pass ───────────────────────────────────────────────────────
def test_repair_frame_repairs_records_and_logs_every_change():
    df = pd.DataFrame([
        {"Name": "GRACE LADOJA", "EMAIL_ADDR": "grace@gmial.com", "PHONE": "07700900123",
         "LATEST_BILLING_ZIP": "SW1A lAA", "LATEST_SHIPPING_ZIP": ""},
        {"Name": "Ada Lovelace", "EMAIL_ADDR": "ada@gmail.com", "PHONE": "07700900124",
         "LATEST_BILLING_ZIP": "W1K 7TN", "LATEST_SHIPPING_ZIP": ""},
    ])
    out = repair_frame(df)
    assert out.loc[0, "LATEST_BILLING_ZIP"] == "SW1A 1AA"
    assert out.loc[0, "EMAIL_ADDR"] == "grace@gmail.com"
    assert out.loc[0, "Name"] == "Grace Ladoja"
    assert len(out.loc[0, REPAIRS_COL]) == 3                     # every change is auditable
    assert any("SW1A lAA -> SW1A 1AA" in r for r in out.loc[0, REPAIRS_COL])
    # the already-clean record is untouched and carries no repair log
    assert out.loc[1, "EMAIL_ADDR"] == "ada@gmail.com" and out.loc[1, REPAIRS_COL] == []
    assert out.loc[1, QUALITY_COL] == 100 and out.loc[1, FLAGS_COL] == []
    assert df.loc[0, "EMAIL_ADDR"] == "grace@gmial.com"          # the caller's frame is not mutated


def test_repair_frame_handles_an_empty_book():
    out = repair_frame(pd.DataFrame(columns=["Name", "EMAIL_ADDR"]))
    assert len(out) == 0 and QUALITY_COL in out.columns and FLAGS_COL in out.columns


def test_repair_frame_tolerates_missing_columns():
    out = repair_frame(pd.DataFrame([{"Name": "GRACE LADOJA"}]))
    assert out.loc[0, "Name"] == "Grace Ladoja"
    assert "no email" in out.loc[0, FLAGS_COL]
