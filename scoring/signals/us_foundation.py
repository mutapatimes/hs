"""US private-foundation trustee signal (from IRS Form 990-PF filings).

Flags customers whose name matches a trustee, officer or director of an EPONYMOUS US private
foundation, i.e. one whose own surname appears in the foundation's name ("The [Surname] Family
Foundation", "[Surname] Foundation"). A family foundation named after you, with you on its board,
is a near-pure marker of inherited or accumulated wealth. This is a governance / wealth FACT, so
it is on by default; it is not an origin proxy.

The US analog to the UK ``charity_trustee`` signal (Charity Commission), and weighted the same. As
with it, the match is on NAME ALONE against a public register (IRS 990-PF filings), so it is a
deliberately CORROBORATION-ONLY signal (in SUPPORTING_SIGNALS in the combiner and in the ``name``
group): it never surfaces a customer on its own, it only adds weight when a stronger signal has
also fired. The two-factor "surname is in the foundation name" filter is applied at BUILD time,
which keeps the table small and collisions low without changing the O(1) runtime match.

The reference table (reference_data/charities/us_foundation_trustees.csv) ships INERT (fictional
examples only). Regenerate it to real coverage from the free IRS 990-PF filings with
scripts/build_us_foundation_trustees.py; the real table lands git-ignored at
us_foundation_trustees.local.csv.

Data: IRS Tax Exempt Organization filings (Form 990-PF), public domain.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import US_FOUNDATION_TRUSTEES_FILE, US_FOUNDATION_TRUSTEES_LOCAL_FILE

FLAG_COL = "us_foundation"
REASON_COL = "us_foundation_reason"


def _default_path() -> Path:
    """Prefer the operator's git-ignored real table when it exists, else the committed seed."""
    local = Path(US_FOUNDATION_TRUSTEES_LOCAL_FILE)
    return local if local.exists() else Path(US_FOUNDATION_TRUSTEES_FILE)


def _normalize(value: object) -> str:
    """Upper-case, strip non-alphanumerics to single spaces (same shape as charity_trustee)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_trustees(path: Path | str | None = None) -> dict[str, str]:
    """Read {normalized_trustee_name: display_reason} from name[,foundation] rows.

    Blank/comment/header rows are skipped. The optional ``foundation`` column names the eponymous
    foundation in the human reason. Exact normalized-name key keeps matching O(1) on a large table.
    """
    path = Path(path) if path is not None else _default_path()
    if not path.exists():
        raise FileNotFoundError(f"US foundation-trustees reference not found: {path}")
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
            foundation = row[1].strip() if len(row) > 1 and row[1].strip() else ""
            reason = (f"{name} — trustee of {foundation} (IRS 990-PF)" if foundation
                      else f"{name} — private-foundation trustee (IRS 990-PF)")
            table.setdefault(norm, reason)
    return table


def match_name(name: object, table: dict[str, str]) -> tuple[bool, str | None]:
    """Exact (normalized) match of a customer name against the foundation-trustee table."""
    norm = _normalize(name)
    if not norm:
        return False, None
    reason = table.get(norm)
    return (reason is not None), reason


def flag_us_foundation(df: pd.DataFrame, table=None, name_col: str = "Name") -> pd.DataFrame:
    """Add us_foundation flag + reason columns to a copy of ``df``."""
    if table is None:
        table = load_trustees()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: match_name(n, table))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
