"""Charity Commission trustee signal (UK, from the open register of charities).

Flags customers whose name matches a trustee of a UK registered charity in the compact,
HIGH-PRECISION subset Halia keeps: **eponymous-foundation** trustees, i.e. people whose own
surname appears in their charity's name ("The [Surname] Foundation", "[Surname] Charitable
Trust"). A family foundation named after you, with you on its board, is a near-pure marker of
inherited or accumulated wealth. Being a charity trustee is a governance / wealth FACT, so this
signal is ON by default; it is not an origin proxy.

Like `companies_house`, the match is on NAME ALONE against a public statutory register, so it is
a deliberately WEAK, CORROBORATION-ONLY signal (in SUPPORTING_SIGNALS in the combiner and in the
`name` group): it never surfaces a customer on its own, it only adds weight when a stronger signal
has also fired. The two-factor "surname is in the charity name" filter is applied at BUILD time,
which is what keeps the table small and the collisions low without changing the O(1) runtime match.

The reference table (reference_data/charities/uk_charity_trustees.csv) ships INERT (a fictional
example only). Regenerate it to real coverage from the free daily Charity Commission extract with
scripts/build_charity_trustees.py. Naming private trustees in the repo is exactly the sensitivity
Halia is careful about, so real people only enter the table on the operator's own machine.

Data: Charity Commission for England and Wales, Open Government Licence v3.0 (attribution).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import UK_CHARITY_TRUSTEES_FILE, UK_CHARITY_TRUSTEES_LOCAL_FILE

FLAG_COL = "charity_trustee"
REASON_COL = "charity_trustee_reason"


def _default_path() -> Path:
    """Prefer the operator's git-ignored real table when it exists, else the committed seed."""
    local = Path(UK_CHARITY_TRUSTEES_LOCAL_FILE)
    return local if local.exists() else Path(UK_CHARITY_TRUSTEES_FILE)


def _normalize(value: object) -> str:
    """Upper-case, strip non-alphanumerics to single spaces (same shape as companies_house)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_trustees(path: Path | str | None = None) -> dict[str, str]:
    """Read {normalized_trustee_name: display_reason}.

    CSV columns: name[, charity]. Blank/comment/header rows are skipped. The optional
    ``charity`` column names the (eponymous) charity in the human reason. A dict with an
    exact normalized-name key is used deliberately: the regenerated table can be large, so
    matching must be O(1), and exact-name equality is more precise than substring matching.
    """
    path = Path(path) if path is not None else _default_path()
    if not path.exists():
        raise FileNotFoundError(f"Charity-trustees reference not found: {path}")
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
            charity = row[1].strip() if len(row) > 1 and row[1].strip() else ""
            reason = (f"{name} — trustee of {charity} (Charity Commission)" if charity
                      else f"{name} — charity trustee (Charity Commission)")
            table.setdefault(norm, reason)
    return table


def match_name(name: object, table: dict[str, str]) -> tuple[bool, str | None]:
    """Exact (normalized) match of a customer name against the trustee table."""
    norm = _normalize(name)
    if not norm:
        return False, None
    reason = table.get(norm)
    return (reason is not None), reason


def flag_charity_trustee(df: pd.DataFrame, table=None, name_col: str = "Name") -> pd.DataFrame:
    """Add charity_trustee flag + reason columns to a copy of ``df``."""
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
