"""Honorific-title signal.

Flags customers whose name begins with an aristocratic / royal / honorific title
(reference_data/names/honorifics.csv). Titles are matched only as LEADING tokens
of the name ("HRH Prince ...", "Sir ...") so a trailing surname like "... Baron"
does not false-fire.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import HONORIFICS_FILE

FLAG_COL = "honorific"
REASON_COL = "honorific_reason"


def _normalize(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_titles(path: Path | str = HONORIFICS_FILE) -> list[str]:
    """Read titles, longest first (so 'THE RIGHT HON' wins over 'THE HON')."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Honorifics reference list not found: {path}")
    titles: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            cell = row[0].strip()
            if not cell or cell.startswith("#") or cell.lower() == "title":
                continue
            norm = _normalize(cell)
            if norm:
                titles.append(norm)
    return sorted(set(titles), key=lambda t: -len(t))


def match_name(name: object, titles: list[str]) -> tuple[bool, str | None]:
    """Return (has_title, title) if the name starts with a known title."""
    norm = _normalize(name)
    if not norm:
        return False, None
    for title in titles:
        if norm == title or norm.startswith(title + " "):
            return True, title
    return False, None


def flag_honorific(df: pd.DataFrame, titles=None, name_col: str = "Name"):
    """Add honorific flag + matched-title columns to a copy of ``df``."""
    if titles is None:
        titles = load_titles()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: match_name(n, titles))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [title for _, title in results]
    return out
