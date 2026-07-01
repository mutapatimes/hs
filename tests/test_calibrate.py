"""Conversion-feedback calibration: lift measurement + bounded weight re-tuning."""
from __future__ import annotations

import numpy as np
import pandas as pd

from scoring.calibrate import calibrate_weights, calibration_report, signal_lift
from scoring.combine import score_customers


def _synthetic(n=400, seed=0):
    """Build a frame where a prime postcode genuinely predicts high spend."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        prime = i % 2 == 0
        # prime-postcode customers spend a lot more; everyone else is low + noisy
        spent = float(rng.normal(4000 if prime else 600, 200))
        rows.append({
            "Name": f"Cust {i}",
            "Email": f"user{i}@gmail.com",
            "LATEST_BILLING_ZIP": "SW10 9SJ" if prime else "M1 1AA",
            "Spent": max(0.0, spent),
        })
    return pd.DataFrame(rows)


def test_lift_ranks_a_predictive_signal_high():
    scored = score_customers(_synthetic())
    lifts = {r["key"]: r for r in signal_lift(scored)}
    assert "hnwi_postcode" in lifts
    assert lifts["hnwi_postcode"]["lift"] > 1.2  # firers spend well above average
    assert lifts["hnwi_postcode"]["n_fired"] >= 25


def test_calibrate_upweights_predictive_signal():
    scored = score_customers(_synthetic())
    base = {"hnwi_postcode": 3, "landline": 1}
    new = calibrate_weights(scored, base_weights=base, min_fired=10)
    assert new["hnwi_postcode"] >= base["hnwi_postcode"]  # predictive -> not reduced, likely raised


def test_weights_are_bounded_and_never_zeroed():
    scored = score_customers(_synthetic())
    new = calibrate_weights(scored, base_weights={"hnwi_postcode": 3}, min_fired=10, hi=2.0)
    assert new["hnwi_postcode"] <= 6  # at most doubled
    assert all(v >= 1 for v in new.values())


def test_low_sample_signal_keeps_base_weight():
    scored = score_customers(_synthetic())
    # An absurd min_fired means nothing qualifies -> weights unchanged.
    new = calibrate_weights(scored, base_weights={"hnwi_postcode": 3}, min_fired=10_000)
    assert new == {"hnwi_postcode": 3}


def test_report_shape_and_notes():
    scored = score_customers(_synthetic())
    rows = calibration_report(scored, min_fired=10)
    assert rows and {"key", "lift", "base_weight", "suggested_weight", "note"} <= set(rows[0])


def test_empty_or_spendless_frame_is_safe():
    df = pd.DataFrame({"Name": ["A", "B"], "Email": ["a@company.com", "b@company.com"]})
    scored = score_customers(df)  # no Spent column
    assert calibrate_weights(scored, base_weights={"work_email": 3}) == {"work_email": 3}
    assert signal_lift(scored)  # doesn't raise
