"""Fashion-stylist / personal-shopper name-match signal.

Flags customers whose name matches a known celebrity stylist, personal shopper, or
wardrobe stylist (reference_data/names/fashion_stylists.csv). For a luxury retailer these
are exceptionally valuable clients — a stylist buys for many UHNW / celebrity wardrobes —
so a match is a strong clienteling tell.

Matched as a whole phrase (so "Law Roach" matches but partial overlaps don't). Names still
collide (some entries are common names), so this is "flag + verify": weighted in the
correlated `name` group, not treated as proof on its own.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import FASHION_STYLISTS_FILE

FLAG_COL = "fashion_stylist"
REASON_COL = "fashion_stylist_reason"


def _normalize(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_stylists(path: Path | str = FASHION_STYLISTS_FILE) -> list[tuple[str, str]]:
    """Read [(normalized_name, display_name)], longest first."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Fashion-stylist reference not found: {path}")
    people: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            name = row[0].strip()
            if not name or name.startswith("#") or name.lower() == "name":
                continue
            norm = _normalize(name)
            if norm:
                people.append((norm, name))
    return sorted(people, key=lambda p: -len(p[0]))


def match_name(name: object, people: list[tuple[str, str]]) -> tuple[bool, str | None]:
    norm = _normalize(name)
    if not norm:
        return False, None
    haystack = f" {norm} "
    for stylist_norm, display in people:
        if f" {stylist_norm} " in haystack:
            return True, f"{display} (verify)"
    return False, None


def flag_fashion_stylist(df: pd.DataFrame, people=None, name_col: str = "Name"):
    """Add fashion-stylist flag + matched-name columns to a copy of ``df``."""
    if people is None:
        people = load_stylists()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: match_name(n, people))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [d for _, d in results]
    return out
