"""Scoring-quality pass: logistic grade, latent cap, confidence split, name-gate, fingerprint."""
import pandas as pd

import build_mvp
from scoring.combine import SUPPORTING_SIGNALS, config_fingerprint, score_customers
from scoring.grading import to_score100, tier_for


# ── logistic grade curve (tier-preserving, top-compressed) ──────────────────────
def test_grade_curve_preserves_tier_boundaries():
    # Old raw cuts: A* raw>=5.0, A raw>=3.5, B raw>=1.75.
    assert tier_for(to_score100(5.0)) == "A1"
    assert tier_for(to_score100(3.5)) == "A"
    assert tier_for(to_score100(1.75)) == "B"
    assert tier_for(to_score100(1.7)) == "C"


def test_top_compressed_and_zero_not_fifty():
    assert to_score100(0) < 20            # zero signals is NOT 50
    assert to_score100(7.75) < 99         # a strong score is high but not the cap
    assert to_score100(20) == 99          # only extreme convergence hits 99


# ── latent value spend-multiple cap ─────────────────────────────────────────────
def test_latent_capped_at_spend_multiple():
    # £1,200 client, high score, huge ceiling -> capped at ~12x, not near the ceiling.
    lat = build_mvp._latent(1200, 1, "A1", store_aov=0, score=97,
                            benchmarks={"aov": 1800, "max_orders": 22, "highest_lt": 95000})
    assert lat == 14400                   # 1200 * 12, not ~£92k


def test_latent_uses_store_aov_floor_for_low_spend():
    # A near-zero-spend row still gets a sensible cap via store_aov.
    lat = build_mvp._latent(0, 1, "A1", store_aov=500, score=90,
                            benchmarks={"highest_lt": 95000})
    assert 0 < lat <= 500 * 12


# ── confidence = independent-evidence breadth ───────────────────────────────────
def test_confidence_single_vs_corroborated():
    # One geo signal only -> single source.
    one = score_customers(pd.DataFrame([{"Name": "A", "EMAIL_ADDR": "a@gmail.com", "Spent": 50,
                                         "LATEST_BILLING_ADDRESS4": "Monaco"}]))
    assert one.loc[0, "signal_confidence"] == 1
    # geo + email (independent groups) -> 2.
    two = score_customers(pd.DataFrame([{"Name": "B", "EMAIL_ADDR": "b@goldmansachs.com", "Spent": 50,
                                        "LATEST_BILLING_ADDRESS4": "Monaco"}]))
    assert two.loc[0, "signal_confidence"] == 2


# ── name-match bright line ──────────────────────────────────────────────────────
def test_name_only_match_never_surfaces_alone():
    for k in ("rich_list", "fashion_stylist", "post_nominal", "companies_house"):
        assert k in SUPPORTING_SIGNALS
    # A rich-list namesake with no other signal -> gated off (count 0, not hidden).
    out = score_customers(pd.DataFrame([{"Name": "James Dyson", "EMAIL_ADDR": "a@gmail.com", "Spent": 50}]))
    assert out.loc[0, "signal_count"] == 0 and not out.loc[0, "hidden_vic"]


# ── audit fingerprint ───────────────────────────────────────────────────────────
def test_config_fingerprint_shape_and_stability():
    fp = config_fingerprint()
    assert set(fp) == {"version", "hash"} and len(fp["hash"]) == 12
    assert config_fingerprint() == fp     # deterministic for a given config
