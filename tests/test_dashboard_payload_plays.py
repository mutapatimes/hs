"""Wealth x behaviour plays in the dashboard payload (bands, Gone quiet rows, landscape).

The behaviour axis (RFM) stays OUT of the Halia score; these tests pin the presentation-time
crossing: band boundaries, the appended known sleeping VICs, and the landscape aggregate.
"""
import time

import pandas as pd
import pytest

import build_mvp as bm
from build_mvp import _band, dashboard_payload
from scoring.combine import HIDDEN_COL, REASONS_COL, SCORE_COL, VIC_SPEND_THRESHOLD
from scoring.grading import tier_for, to_score100

NOW = time.time()
# The smallest raw engine score whose 0-100 mapping lands in the A tiers.
RAW_A = next(v for v in range(0, 80) if tier_for(to_score100(float(v))) in ("A1", "A"))
RAW_C = 0.0


def _days_ago(days: float) -> pd.Timestamp:
    return pd.Timestamp.now() - pd.Timedelta(days=days)


def _row(name, raw, spend, orders, last, hidden):
    return {
        "Name": name, "EMAIL_ADDR": f"{name.split()[0].lower()}@example.com", "CUST_ID": name,
        SCORE_COL: raw, HIDDEN_COL: hidden, REASONS_COL: "Work email: wealth-linked employer",
        "signal_count": 1, "signal_confidence": 1,
        "Spent": spend, "Count of CUST_ID": orders, "Last Shopped": last,
    }


def _frame():
    return pd.DataFrame([
        _row("Fresh Hidden", RAW_A, 900, 1, _days_ago(20), True),      # hidden, active
        _row("Lapsed Hidden", RAW_A, 2400, 3, _days_ago(420), True),   # hidden, lapsed (play via UI)
        _row("Known Sleeper", RAW_A, 22000, 6, _days_ago(400), False), # proven VIC gone quiet -> appended
        _row("Known Cooling", RAW_A, 18000, 5, _days_ago(250), False), # cooling counts as sleeping too
        _row("Known Active", RAW_A, 30000, 9, _days_ago(15), False),   # active -> NOT appended
        _row("Devoted Regular", RAW_C, 1200, 6, _days_ago(30), False), # B/C + frequent + active
    ])


def test_band_boundaries():
    assert _band(int(NOW - 179 * 86400), NOW) == "active"
    assert _band(int(NOW - 181 * 86400), NOW) == "cooling"
    assert _band(int(NOW - 366 * 86400), NOW) == "lapsed"
    assert _band(0, NOW) == "new"                                      # no dated order


def test_sleeping_vics_appended_flagged_and_capped(monkeypatch):
    payload = dashboard_payload(_frame())
    by_name = {c["name"]: c for c in payload["data"]}
    assert by_name["Known Sleeper"]["known"] is True
    assert by_name["Known Sleeper"]["band"] == "lapsed"
    assert by_name["Known Cooling"]["known"] is True
    assert "Known Active" not in by_name                               # active proven VICs stay out
    assert by_name["Fresh Hidden"]["known"] is False                   # the core surface is unflagged
    assert by_name["Lapsed Hidden"]["band"] == "lapsed"
    # ranked by spend and capped
    monkeypatch.setattr(bm, "SLEEPING_CAP", 1)
    capped = dashboard_payload(_frame())
    known = [c for c in capped["data"] if c["known"]]
    assert [c["name"] for c in known] == ["Known Sleeper"]             # highest spend survives the cap


def test_landscape_counts_and_stats_unchanged():
    payload = dashboard_payload(_frame())
    ls = payload["landscape"]
    assert ls["hidden"]["n"] == 2                                      # the two hidden rows
    assert ls["sleeping"]["n"] == 2 and ls["sleeping"]["value"] == 40000
    assert ls["active"]["n"] == 2                                      # Fresh Hidden + Known Active
    assert ls["regulars"]["n"] == 1                                    # Devoted Regular
    # headline stats stay the hidden-VIC story; appended rows never inflate them
    assert payload["stat_count"] == "2"


def test_known_rows_carry_full_client_shape():
    payload = dashboard_payload(_frame())
    sleeper = next(c for c in payload["data"] if c["name"] == "Known Sleeper")
    assert sleeper["spend"] == 22000 and sleeper["ordersCount"] == 6
    assert sleeper["signals"] and sleeper["grade"] in ("A*", "A")      # scored like any client


def test_render_injects_landscape():
    html = bm.render_payload(dashboard_payload(_frame()))
    assert "__LANDSCAPE__" not in html and '"sleeping"' in html
