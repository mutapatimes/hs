"""IP-location signal — for the Shopify phase.

Flags customers whose checkout IP geolocates to a wealthy residential area or a
common HNW vacation spot (reference_data/locations/hnw_locations.csv).

Two parts, deliberately separated:
  - the SIGNAL matches resolved location columns (``ip_city``, ``ip_region``,
    optionally ``ip_country``) against the list — pure and testable, DORMANT
    until those columns exist (e.g. an IP from Shopify's browser_ip);
  - ``resolve_ip`` / ``add_ip_geolocation`` turn a raw IP into those columns
    using MaxMind GeoIP2 IF installed and a GeoLite2 DB is configured. With no
    geoip2 package / DB they return None, so nothing breaks offline.

Caveat: IPs are noisy (VPNs, mobile carriers, offices), so this is weighted LOW
in the combiner — strongest as corroboration (IP in Aspen AND ships to Aspen).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import GEOIP_DB_FILE, HNW_LOCATIONS_FILE

FLAG_COL = "ip_location"
REASON_COL = "ip_location_reason"

CITY_COL = "ip_city"
REGION_COL = "ip_region"
COUNTRY_COL = "ip_country"


def _normalize(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_locations(path: Path | str = HNW_LOCATIONS_FILE) -> list[tuple[str, str]]:
    """Read [(normalized_location, 'Location (type)')], longest first."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"HNW-locations reference not found: {path}")
    locations: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            name = row[0].strip()
            if not name or name.startswith("#") or name.lower() == "location":
                continue
            loc_type = row[1].strip() if len(row) > 1 else ""
            norm = _normalize(name)
            if norm:
                label = f"{name} ({loc_type})" if loc_type else name
                locations.append((norm, label))
    return sorted(locations, key=lambda x: -len(x[0]))


def match_location(
    city: object, region: object, country: object, locations: list[tuple[str, str]]
) -> tuple[bool, str | None]:
    """Whole-phrase match of any HNW location within the resolved place text."""
    haystack = f" {_normalize(city)} {_normalize(region)} {_normalize(country)} "
    if haystack.strip() == "":
        return False, None
    for loc_norm, label in locations:
        if f" {loc_norm} " in haystack:
            return True, label
    return False, None


def flag_ip_location(
    df: pd.DataFrame,
    locations: list[tuple[str, str]] | None = None,
    city_col: str = CITY_COL,
    region_col: str = REGION_COL,
    country_col: str = COUNTRY_COL,
) -> pd.DataFrame:
    """Add IP-location flag + reason columns. Dormant if no resolved IP columns."""
    if locations is None:
        locations = load_locations()

    out = df.copy()
    if city_col not in out.columns and region_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    def col(name):
        return out[name] if name in out.columns else pd.Series([None] * len(out))

    results = [
        match_location(c, r, co, locations)
        for c, r, co in zip(col(city_col).tolist(), col(region_col).tolist(), col(country_col).tolist())
    ]
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out


# --------------------------------------------------------------------------
# Optional IP -> location resolution (used at data-load time, not in tests).
# --------------------------------------------------------------------------
def resolve_ip(ip: object, db_path: Path | str = GEOIP_DB_FILE):
    """Return (city, region, country) for an IP, or (None, None, None).

    Requires `pip install geoip2` and a GeoLite2-City.mmdb at db_path. Returns
    Nones (never raises) if either is missing, so callers stay robust offline.
    """
    if ip is None or str(ip).strip() == "":
        return (None, None, None)
    try:
        import geoip2.database  # optional dependency
    except ImportError:
        return (None, None, None)
    if not Path(db_path).exists():
        return (None, None, None)
    try:
        with geoip2.database.Reader(str(db_path)) as reader:
            resp = reader.city(str(ip).strip())
            region = resp.subdivisions.most_specific.name if resp.subdivisions else None
            return (resp.city.name, region, resp.country.name)
    except Exception:
        return (None, None, None)


def add_ip_geolocation(
    df: pd.DataFrame, ip_col: str = "browser_ip", db_path: Path | str = GEOIP_DB_FILE
) -> pd.DataFrame:
    """Populate ip_city/ip_region/ip_country from an IP column (best-effort)."""
    out = df.copy()
    if ip_col not in out.columns:
        return out
    resolved = [resolve_ip(ip, db_path) for ip in out[ip_col].tolist()]
    out[CITY_COL] = [c for c, _, _ in resolved]
    out[REGION_COL] = [r for _, r, _ in resolved]
    out[COUNTRY_COL] = [co for _, _, co in resolved]
    return out
