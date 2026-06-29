"""Wealth-company office signal — CITY-GUARDED.

Flags customers whose billing/shipping address is the HQ of a major bank / PE
firm / hedge fund (reference_data/venues/wealth_offices.csv) — a senior-employee
tell that genuinely works (e.g. a Deutsche Bank associate billing to "21
Moorfields, London").

A building/street token ALONE collides with ordinary streets that share a name
("4 Brookfield Place, Southampton" is NOT Brookfield's HQ), so each office is
tagged with its CITY: a match requires BOTH a distinctive address token AND the
office's city to appear in the address. Same building token in the wrong city =
no match.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from config import WEALTH_OFFICES_FILE
from scoring.signals.delivery_venue import ALL_ADDRESS_COLS, _combine_rows, _normalize

MATCH_COL = "wealth_office_match"
OFFICE_COL = "wealth_office"
TYPE_COL = "wealth_office_type"


def load_offices(
    path: Path | str = WEALTH_OFFICES_FILE,
) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
    """Read [(name, type, city_aliases, address_aliases)], all normalized."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Wealth-offices reference not found: {path}")
    offices = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            name = row[0].strip()
            if not name or name.startswith("#") or name == "venue":
                continue
            signal_type = row[1].strip() if len(row) > 1 else ""
            cities = tuple(
                c for c in (_normalize(p) for p in (row[2] if len(row) > 2 else "").split(";")) if c
            )
            addrs = tuple(
                a for a in (_normalize(p) for p in (row[3] if len(row) > 3 else "").split(";")) if a
            )
            if cities and addrs:
                offices.append((name, signal_type, cities, addrs))
    return offices


def match_address(address: object, offices) -> tuple[bool, str | None, str | None]:
    """Match only when a building token AND the firm's city both appear."""
    norm = _normalize(address)
    if not norm:
        return False, None, None
    hay = f" {norm} "
    for name, signal_type, cities, addrs in offices:
        if any(f" {a} " in hay for a in addrs) and any(f" {c} " in hay for c in cities):
            return True, name, signal_type
    return False, None, None


def flag_wealth_office(df: pd.DataFrame, offices=None, address_cols=None) -> pd.DataFrame:
    """Add city-guarded wealth-office match, firm, and type columns to a copy."""
    if offices is None:
        offices = load_offices()
    cols = [c for c in (address_cols or ALL_ADDRESS_COLS) if c in df.columns]

    out = df.copy()
    if not cols:
        out[MATCH_COL] = False
        out[OFFICE_COL] = None
        out[TYPE_COL] = None
        return out

    combined = _combine_rows(out, cols)
    results = combined.apply(lambda a: match_address(a, offices))
    out[MATCH_COL] = [hit for hit, _, _ in results]
    out[OFFICE_COL] = [name for _, name, _ in results]
    out[TYPE_COL] = [kind for _, _, kind in results]
    return out
