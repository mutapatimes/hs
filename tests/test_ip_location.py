"""Tests for the IP-location signal (matcher + dormancy + resolver fallback)."""
import pandas as pd

from scoring.signals.ip_location import (
    FLAG_COL,
    REASON_COL,
    flag_ip_location,
    load_locations,
    match_location,
    resolve_ip,
)


def test_us_locations_are_in_the_list():
    labels = [label for _, label in load_locations()]
    joined = " | ".join(labels)
    for expected in ["Beverly Hills", "Aspen", "East Hampton", "Palm Beach"]:
        assert expected in joined


def test_match_hnw_city():
    locs = load_locations()
    assert match_location("Beverly Hills", "California", "United States", locs)[0]
    assert match_location("Aspen", "Colorado", "United States", locs)[1].startswith("Aspen")
    assert match_location("East Hampton", "New York", "United States", locs)[0]


def test_non_hnw_city_does_not_match():
    locs = load_locations()
    assert match_location("Manchester", "England", "United Kingdom", locs) == (False, None)
    assert match_location(None, None, None, locs) == (False, None)


def test_dormant_when_no_ip_columns():
    df = pd.DataFrame({"Name": ["a", "b"], "Spent": [1, 2]})
    out = flag_ip_location(df)
    assert out[FLAG_COL].tolist() == [False, False]


def test_fires_when_resolved_columns_present():
    df = pd.DataFrame(
        {
            "ip_city": ["Aspen", "Leeds"],
            "ip_region": ["Colorado", "England"],
            "ip_country": ["United States", "United Kingdom"],
        }
    )
    out = flag_ip_location(df)
    assert out[FLAG_COL].tolist() == [True, False]
    assert out.loc[0, REASON_COL].startswith("Aspen")


def test_resolve_ip_is_graceful_without_geoip():
    # No geoip2 / MaxMind DB in the test env -> Nones, never raises.
    assert resolve_ip("8.8.8.8") == (None, None, None)
    assert resolve_ip("") == (None, None, None)
