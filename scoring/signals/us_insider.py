"""US corporate-insider signal (from SEC EDGAR ownership filings, Forms 3/4/5).

Flags customers whose name matches a compact reference of people who sit on the board, run, or own
10%+ of a US public company (the "reporting owners" of SEC ownership filings). Being a director,
officer, or 10% holder of a listed company is a work / wealth FACT drawn from a public statutory
register, so this is on by default; it is not an origin proxy.

The US analog to ``companies_house`` (UK). Like it, this is a match on NAME against a large public
register, so it stays a deliberately CORROBORATION-ONLY signal (in SUPPORTING_SIGNALS in the
combiner and in the ``name`` group): it never surfaces a customer on its own, it only adds weight
when a stronger signal has also fired. Two role tiers, graded at BUILD time:
  - ``insider`` : a director or officer of a listed company            (base weight)
  - ``owner``   : a 10%+ beneficial owner (a large equity stake)        (lifted)

US NEXUS. Because this is a name match against a US register, it only fires when the customer is
independently pinned to the US (a US billing/shipping country, a +1 phone, or a US-format ZIP) via
_us_nexus.gate — a shared name held by a non-US customer must not surface them.

NAME MATCHING. SEC records reporting-owner names surname-first ("Musk Elon"), while a customer's
name is given first-first ("Elon Musk"). To match across both orders (and to shrug off middle
names / suffixes), the match key is the customer's FIRST and LAST name tokens, upper-cased and
order-independent. That is looser than the UK signal's exact match, which is why the precision lives
in the table (built only from directors / officers / 10% owners, with very common first+last name
keys dropped) and why the signal is corroboration-only.

The reference table (reference_data/companies/us_insiders.csv) ships INERT (fictional examples
only). Regenerate it to real coverage from the free SEC Insider Transactions Data Sets with
scripts/build_us_insiders.py; the real table lands git-ignored at us_insiders.local.csv.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import US_INSIDERS_FILE, US_INSIDERS_LOCAL_FILE
from scoring.signals._us_nexus import gate

FLAG_COL = "us_insider"
REASON_COL = "us_insider_reason"
TYPE_COL = "us_insider_tier"        # per-row role tier; the combiner maps it -> weight

_TIER_RANK = {"owner": 1, "insider": 0}
_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "PHD", "ESQ"}


def _default_path() -> Path:
    """Prefer the operator's git-ignored real table when it exists, else the committed seed."""
    local = Path(US_INSIDERS_LOCAL_FILE)
    return local if local.exists() else Path(US_INSIDERS_FILE)


def _tokens(value: object) -> list[str]:
    """Upper-case alphabetic name tokens, with trailing suffixes (Jr/III/MD) dropped."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    raw = re.sub(r"[^A-Z ]+", " ", str(value).upper())
    toks = [t for t in raw.split() if t]
    while len(toks) > 2 and toks[-1] in _SUFFIXES:
        toks.pop()
    return toks


def name_key(value: object) -> str | None:
    """Order-independent FIRST+LAST key so "Musk Elon" and "Elon Musk" collide. None if < 2 tokens."""
    toks = _tokens(value)
    if len(toks) < 2:
        return None
    return " ".join(sorted((toks[0], toks[-1])))


def load_insiders(path: Path | str | None = None) -> dict[str, tuple[str, str]]:
    """Read {name_key: (display_reason, tier)} from name[,tier[,company]] rows (strongest tier kept).

    Blank/comment/header rows are skipped. ``tier`` is insider/owner (defaults to "insider");
    ``company`` names the issuer in the human reason. A key seen twice keeps the stronger tier.
    """
    path = Path(path) if path is not None else _default_path()
    if not path.exists():
        raise FileNotFoundError(f"US insiders reference not found: {path}")
    table: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            name = row[0].strip()
            if not name or name.startswith("#") or name.lower() == "name":
                continue
            key = name_key(name)
            if not key:
                continue
            tier = row[1].strip().lower() if len(row) > 1 and row[1].strip() else "insider"
            if tier not in _TIER_RANK:
                tier = "insider"
            company = row[2].strip() if len(row) > 2 and row[2].strip() else ""
            reason = _reason(name, tier, company)
            prev = table.get(key)
            if prev is None or _TIER_RANK[tier] > _TIER_RANK[prev[1]]:
                table[key] = (reason, tier)
    return table


def _reason(name: str, tier: str, company: str) -> str:
    role = "owns 10%+ of" if tier == "owner" else "is an insider at"
    where = company or "a US public company"
    return f"{name} — {role} {where} (SEC filing)"


def match_name(name: object, table: dict[str, tuple[str, str]]) -> tuple[bool, str | None, str | None]:
    """Order-independent first+last match of a customer name against the insider table."""
    key = name_key(name)
    if key is None:
        return False, None, None
    hit = table.get(key)
    if hit is None:
        return False, None, None
    return True, hit[0], hit[1]


def flag_us_insider(df: pd.DataFrame, table=None, name_col: str = "Name") -> pd.DataFrame:
    """Add us_insider flag + reason + tier columns to a copy of ``df``.

    A name match only fires when the customer is independently pinned to the US (see _us_nexus):
    a US register name shared by a non-US customer must not surface them.
    """
    if table is None:
        table = load_insiders()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        out[TYPE_COL] = None
        return out
    results = [match_name(v, table) for v in out[name_col]]
    hits = [hit for hit, _, _ in results]
    gated = gate(out, hits)                       # AND the name match with the US-nexus mask
    out[FLAG_COL] = list(gated)
    out[REASON_COL] = [r if g else None for (_, r, _), g in zip(results, gated)]
    out[TYPE_COL] = [t if g else None for (_, _, t), g in zip(results, gated)]
    return out
