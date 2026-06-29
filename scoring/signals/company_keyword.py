"""Company-keyword signal.

Flags customers whose COMPANY_NAME contains a wealth-linked keyword
(reference_data/companies/company_keywords.csv) — Capital, Holdings, Family
Office, LLP, etc. Whole-word matching, so "Capital" matches but "Capitals" /
street names do not.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import COMPANY_KEYWORDS_FILE

FLAG_COL = "company_keyword"
REASON_COL = "company_keyword_reason"


def _normalize(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_keywords(path: Path | str = COMPANY_KEYWORDS_FILE) -> list[tuple[str, str]]:
    """Read [(keyword, category)], longest keyword first."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Company-keyword reference list not found: {path}")
    keywords: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            kw = row[0].strip()
            if not kw or kw.startswith("#") or kw.lower() == "keyword":
                continue
            category = row[1].strip() if len(row) > 1 else ""
            norm = _normalize(kw)
            if norm:
                keywords.append((norm, category))
    return sorted(keywords, key=lambda k: -len(k[0]))


def match_company(company: object, keywords: list[tuple[str, str]]) -> tuple[bool, str | None]:
    norm = _normalize(company)
    if not norm:
        return False, None
    haystack = f" {norm} "
    for kw, _category in keywords:
        if f" {kw} " in haystack:
            return True, kw
    return False, None


def flag_company_keyword(df: pd.DataFrame, keywords=None, company_col: str = "COMPANY_NAME"):
    """Add company-keyword flag + matched-keyword columns to a copy of ``df``."""
    if keywords is None:
        keywords = load_keywords()
    out = df.copy()
    if company_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[company_col].apply(lambda c: match_company(c, keywords))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [kw for _, kw in results]
    return out
