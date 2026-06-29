"""Rich-list name-match signal.

Flags customers whose name matches a publicly-named wealthy individual
(reference_data/names/rich_list.csv). Matched as a whole phrase, so "Evgeny
Chichvarkin" matches but partial overlaps don't.

Name collisions are common (many people share a name with a rich-list entry),
so this is a deliberately WEAK signal: weighted low in the combiner ("flag all,
rank low"). It's strongest as corroboration when another signal also fires.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import RICH_LIST_FILE

FLAG_COL = "rich_list"
REASON_COL = "rich_list_reason"


def _normalize(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_rich_list(path: Path | str = RICH_LIST_FILE) -> list[tuple[str, str]]:
    """Read [(normalized_name, display_name)], longest first."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Rich-list reference not found: {path}")
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
    for rich_norm, display in people:
        if f" {rich_norm} " in haystack:
            return True, display
    return False, None


def flag_rich_list(df: pd.DataFrame, people=None, name_col: str = "Name"):
    """Add rich-list flag + matched-name columns to a copy of ``df``."""
    if people is None:
        people = load_rich_list()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: match_name(n, people))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [d for _, d in results]
    return out
