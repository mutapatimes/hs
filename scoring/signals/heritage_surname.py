"""Heritage-surname signal — a documented wealth-dynasty surname match.

SENSITIVE SIGNAL (name-based), but EVIDENCE-BACKED. Clark et al. ("The Son Also
Rises") show that RARE elite surnames carry real, measurable inherited-status
signal across many generations. This matches the customer's name against a
curated list of rare, distinctive wealth-dynasty / aristocratic surnames
(reference_data/names/heritage_surnames.csv) — a factual marker of a documented
family, NOT a judgement that a name "sounds" upper-class.

Surnames are shared, so this is deliberately WEIGHTED LOW (collisions: not every
"Astor" is THE Astor) and grouped with the other name signals so name tells don't
stack. Only RARE distinctive names are listed — common surnames are excluded by
design (see the reference file).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import HERITAGE_SURNAMES_FILE

FLAG_COL = "heritage_surname"
REASON_COL = "heritage_surname_reason"


def _normalize(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_surnames(path: Path | str = HERITAGE_SURNAMES_FILE) -> list[tuple[str, str]]:
    """Read [(normalized_surname, 'Family (description)')], longest first."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Heritage-surname reference not found: {path}")
    names: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            surname = row[0].strip()
            if not surname or surname.startswith("#") or surname.lower() == "surname":
                continue
            family = row[1].strip() if len(row) > 1 else surname
            norm = _normalize(surname)
            if norm:
                names.append((norm, family))
    return sorted(names, key=lambda p: -len(p[0]))


def match_name(name: object, surnames: list[tuple[str, str]]) -> tuple[bool, str | None]:
    """Whole-word match of any dynasty surname within the customer's name."""
    norm = _normalize(name)
    if not norm:
        return False, None
    haystack = f" {norm} "
    for surname_norm, family in surnames:
        if f" {surname_norm} " in haystack:
            return True, family
    return False, None


def flag_heritage_surname(df: pd.DataFrame, surnames=None, name_col: str = "Name"):
    """Add heritage-surname flag + matched-family columns to a copy of ``df``."""
    if surnames is None:
        surnames = load_surnames()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: match_name(n, surnames))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [family for _, family in results]
    return out
