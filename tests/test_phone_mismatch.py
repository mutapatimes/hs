"""Tests for the phone-vs-address mismatch signal (an off-by-default origin proxy).

Only fires when the phone's jurisdiction differs from the billing/shipping country — a
matching local number never flags, so it's a mobility tell, not a nationality indicator.
"""
import pandas as pd

from scoring.combine import ORIGIN_PROXY_SIGNALS, active_signals
from scoring.signals.phone_mismatch import FLAG_COL, REASON_COL, flag_phone_mismatch


def test_flags_only_on_mismatch():
    df = pd.DataFrame({
        "PHONE": [
            "+971 50 123 4567",   # UAE phone, UK billing        -> flag
            "+971 50 999 8888",   # UAE phone, UAE billing       -> local, no flag
            "+971 50 111 2222",   # UAE phone, UAE *shipping*     -> local, no flag
            "+44 7700 900123",    # UK phone (not a listed code)  -> no flag
            "+1 345 555 1212",    # Cayman phone, UK billing      -> flag
            "00971501234567",     # 00-prefixed UAE, UK billing   -> flag (00 -> +)
        ],
        "LATEST_BILLING_ADDRESS4": [
            "United Kingdom", "United Arab Emirates", "United Kingdom",
            "United Kingdom", "United Kingdom", "United Kingdom",
        ],
        "LATEST_SHIPPING_ADDRESS4": [
            None, None, "United Arab Emirates", None, None, None,
        ],
    })
    out = flag_phone_mismatch(df)
    assert out[FLAG_COL].tolist() == [True, False, False, False, True, True]

    # Reason is a bare, checkable fact — names the jurisdiction + address, no inference.
    reason = out[REASON_COL].tolist()[0]
    assert "United Arab Emirates" in reason and "differs from" in reason and "United Kingdom" in reason
    for banned in ("HNW", "wealth", "wealthy", "rich", "likely", "nationality"):
        assert banned.lower() not in reason.lower()


def test_dormant_without_phone_column():
    out = flag_phone_mismatch(pd.DataFrame({"x": [1, 2]}))
    assert out[FLAG_COL].tolist() == [False, False]
    assert out[REASON_COL].tolist() == [None, None]


def test_off_by_default_origin_proxy():
    assert "phone_mismatch" in ORIGIN_PROXY_SIGNALS
    default_keys = {s[0] for s in active_signals(include_origin=False)}
    origin_keys = {s[0] for s in active_signals(include_origin=True)}
    assert "phone_mismatch" not in default_keys        # gated off by default
    assert "phone_mismatch" in origin_keys             # available when opted in
    # its raw siblings stay gated too
    assert {"phone_country", "gulf_prime_district", "gcc_billing"}.isdisjoint(default_keys)
