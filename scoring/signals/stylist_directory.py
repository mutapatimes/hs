"""Broad fashion-stylist DIRECTORY name match (Tier 2 — corroboration only).

The curated `fashion_stylist` signal holds recognisable celebrity stylists. This one
holds the much broader trade directory (hundreds of working stylists, hair & make-up
artists), where many entries are common names. So it is registered as a SUPPORTING
signal in the combiner: a match here NEVER surfaces a customer on its own — it only adds
weight/count when a stronger wealth signal has already fired. That captures breadth
without flagging an ordinary "Emily Lee".

Reuses the whole-phrase matching + normalisation from the curated signal.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import FASHION_STYLISTS_DIRECTORY_FILE
from scoring.signals.fashion_stylist import _normalize, load_stylists

FLAG_COL = "stylist_directory"
REASON_COL = "stylist_directory_reason"


def load_directory(path: Path | str = FASHION_STYLISTS_DIRECTORY_FILE) -> list[tuple[str, str]]:
    """Read [(normalized_name, display_name)], longest first."""
    return load_stylists(path)


def match_name(name: object, people: list[tuple[str, str]]) -> tuple[bool, str | None]:
    norm = _normalize(name)
    if not norm:
        return False, None
    haystack = f" {norm} "
    for stylist_norm, display in people:
        if f" {stylist_norm} " in haystack:
            return True, f"{display} (verify)"
    return False, None


def flag_stylist_directory(df: pd.DataFrame, people=None, name_col: str = "Name"):
    """Add directory-stylist flag + matched-name columns to a copy of ``df``."""
    if people is None:
        people = load_directory()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: match_name(n, people))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [d for _, d in results]
    return out
