"""Companies House control signal (UK, from the open PSC register).

Flags customers whose name matches a Person of Significant Control (PSC) or listed
director in the UK Companies House register — i.e. someone who owns or controls a UK
company. Controlling a company is a WEALTH / WORK FACT, so this signal is ON by default;
it is not an origin proxy.

Because the match is on NAME ALONE against millions of register entries, collisions are
common (many people share a name with a PSC). It is therefore a deliberately WEAK,
CORROBORATION-ONLY signal: it is in SUPPORTING_SIGNALS in the combiner, so it can never
surface a customer on its own — it only adds weight when a stronger signal has also fired.
This is the principled difference from `rich_list`, which is a small curated list of
genuinely-named wealthy individuals (higher precision, so it may stand alone weakly).

The reference table (reference_data/companies/uk_company_controllers.csv) is a compact
seed; regenerate it to national coverage from the free Companies House PSC snapshot with
scripts/build_company_controllers.py. Matching mirrors `rich_list`: whole-phrase, so
"Evgeny Chichvarkin" matches but partial overlaps don't.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import UK_COMPANY_CONTROLLERS_FILE

FLAG_COL = "companies_house"
REASON_COL = "companies_house_reason"


def _normalize(value: object) -> str:
    """Upper-case, strip non-alphanumerics to single spaces (same shape as rich_list)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_controllers(path: Path | str = UK_COMPANY_CONTROLLERS_FILE) -> dict[str, str]:
    """Read {normalized_full_name: display_reason}.

    CSV columns: name[, role]. Blank/comment/header rows are skipped. The optional
    ``role`` column becomes part of the human reason (e.g. "PSC", "Director"); when
    absent we fall back to a generic "person of significant control" wording.

    A dict (exact normalized-name key) is used deliberately: the regenerated register
    can hold millions of names, so matching must be O(1), and exact-name equality is
    also more precise than substring matching (fewer collisions) at that scale.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Company-controllers reference not found: {path}")
    table: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            name = row[0].strip()
            if not name or name.startswith("#") or name.lower() == "name":
                continue
            norm = _normalize(name)
            if not norm:
                continue
            role = row[1].strip() if len(row) > 1 and row[1].strip() else "person of significant control"
            table.setdefault(norm, f"{name} — {role} (Companies House)")
    return table


def match_name(name: object, table: dict[str, str]) -> tuple[bool, str | None]:
    """Exact (normalized) match of a customer name against the controller table."""
    norm = _normalize(name)
    if not norm:
        return False, None
    reason = table.get(norm)
    return (reason is not None), reason


def flag_companies_house(df: pd.DataFrame, table=None, name_col: str = "Name") -> pd.DataFrame:
    """Add companies_house flag + reason columns to a copy of ``df``."""
    if table is None:
        table = load_controllers()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: match_name(n, table))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
