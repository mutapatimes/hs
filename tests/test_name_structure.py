"""Tests for the sensitive, corroboration-only name-structure signal.

Covers a double-barrelled name, a plain name (~zero), a particle name (NOT
flagged — we don't infer origin), the opt-in multi-part case, and the core
guarantee that this signal can never flag/grade a customer on its own.
"""
import pandas as pd

from scoring.combine import COUNT_COL, HIDDEN_COL, SCORE_COL, score_customers
from scoring.realtime import grade_record
from scoring.signals.name_structure import detect_structure, flag_name_structure


# --- detection (structure only, no origin) ----------------------------------
def test_double_barrelled_name_is_detected():
    matched, reason = detect_structure("Anne Pelham-Clinton")
    assert matched
    assert "weak" in reason and "possible" in reason     # hedged, not "aristocratic"


def test_plain_name_scores_zero():
    assert detect_structure("John Smith") == (False, None)
    assert detect_structure("Mary Jones") == (False, None)


def test_particle_names_are_not_flagged():
    # We deliberately do NOT detect nobiliary/language particles — that would be
    # inferring national origin. These must NOT fire on structure alone.
    assert detect_structure("Otto von Bismarck") == (False, None)
    assert detect_structure("Maria de la Cruz") == (False, None)
    assert detect_structure("Jan van Dijk") == (False, None)


def test_multipart_is_opt_in_only():
    name = "Maria de los Santos Garcia"          # 5 parts
    assert detect_structure(name) == (False, None)             # off by default
    assert detect_structure(name, include_multipart=True)[0]    # only when asked


def test_initials_are_not_counted_as_parts():
    assert detect_structure("J. P. Morgan", include_multipart=True) == (False, None)


def test_flag_frame_and_missing_column():
    df = pd.DataFrame({"Name": ["Anne Pelham-Clinton", "John Smith"]})
    out = flag_name_structure(df)
    assert out["name_structure"].tolist() == [True, False]
    # No Name column -> safe no-op.
    assert not flag_name_structure(pd.DataFrame({"x": [1]}))["name_structure"].any()


# --- the critical guarantee: never a sole basis -----------------------------
def _row(**kw):
    base = {"Name": "x", "Spent": 100, "EMAIL_ADDR": "x@gmail.com",
            "LATEST_BILLING_ZIP": "LS1 1AA", "LATEST_BILLING_ADDRESS4": "United Kingdom"}
    base.update(kw)
    return base


def test_name_structure_alone_never_flags():
    # Hyphenated name, low spend, and NOTHING else fires.
    out = score_customers(pd.DataFrame([_row(Name="Anne Pelham-Clinton")]))
    assert out.loc[0, COUNT_COL] == 0          # uncorroborated -> does not count
    assert out.loc[0, SCORE_COL] == 0
    assert not out.loc[0, HIDDEN_COL]          # cannot be surfaced on its own


def test_name_structure_only_nudges_when_corroborated():
    # Hyphenated name + a real signal (work email). Now it counts, as a nudge.
    out = score_customers(pd.DataFrame([_row(
        Name="Anne Pelham-Clinton", EMAIL_ADDR="anne@gs.com")]),   # work_email, w=3
        include_origin=True)  # name_structure is off by default; opt in to test the nudge
    assert out.loc[0, COUNT_COL] == 2
    assert out.loc[0, SCORE_COL] == 4          # 3 (work email) + 1 (name nudge)


def test_grade_is_never_driven_by_name_alone():
    res = grade_record({"Name": "Anne Pelham-Clinton", "Spent": 100})
    assert not res["flagged"] and not res["is_priority"]
    assert res["gesture"] == ""
