"""Tests for the nobiliary-particle signal (low-weight, corroboration-only)."""
import pandas as pd

from scoring.combine import HIDDEN_COL, REASONS_COL, score_customers
from scoring.signals.nobiliary_particle import detect_particle, flag_nobiliary_particle


def test_detects_french_and_german_particles():
    assert detect_particle("Côme de Bouchony")[0]
    assert detect_particle("DE BOUCHONY")[0]           # surname-only field
    assert detect_particle("Otto von und zu Habsburg")[0]
    assert detect_particle("Henri du Pont")[0]


def test_does_not_match_without_particle_or_surname():
    assert not detect_particle("Maria Garcia")[0]
    assert not detect_particle("Sarah")[0]
    assert not detect_particle("de")[0]                # particle alone, no surname


def test_particle_alone_never_surfaces_a_client():
    # A nobiliary particle with NO other signal must NOT make a hidden VIC.
    out = score_customers(pd.DataFrame([{
        "Name": "Côme de Bouchony", "Spent": 300, "EMAIL_ADDR": "come@gmail.com",
    }]))
    assert not bool(out.loc[0, HIDDEN_COL])
    assert "particle" not in (out.loc[0, REASONS_COL] or "")


def test_particle_corroborates_a_real_signal():
    # With a stronger (core) signal present — a wealth-employer work email — the
    # nobiliary particle corroborates and counts.
    out = score_customers(pd.DataFrame([{
        "Name": "Côme de Bouchony", "Spent": 300,
        "EMAIL_ADDR": "come@goldmansachs.com",
    }]), include_origin=True)  # origin proxies are off by default; opt in to test corroboration
    reasons = out.loc[0, REASONS_COL]
    assert bool(out.loc[0, HIDDEN_COL])
    assert "Nobiliary particle" in reasons


def test_missing_name_column_is_dormant():
    out = flag_nobiliary_particle(pd.DataFrame({"x": [1]}))
    assert not out["nobiliary_particle"].any()
