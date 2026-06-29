"""Post-nominal honours signal (§4).

Flags customers whose NAME contains a recognised British honour / order —
OBE, KBE, QC/KC, FRS, etc. (reference_data/names/post_nominals.csv). A factual,
structural feature (membership of an order of chivalry or learned body), not a
judgement of how a name sounds. Matched case-insensitively as a STANDALONE token,
using only distinctive honours, so stray initials ("K. C. Jones" -> K, C, not KC)
do not false-fire.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import POST_NOMINALS_FILE

FLAG_COL = "post_nominal"
REASON_COL = "post_nominal_reason"


def load_honours(path: Path | str = POST_NOMINALS_FILE) -> dict[str, str]:
    """Read {HONOUR(upper): meaning}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Post-nominals reference not found: {path}")
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            honour = row[0].strip()
            if not honour or honour.startswith("#") or honour.lower() == "honour":
                continue
            out[honour.upper()] = row[1].strip() if len(row) > 1 else honour
    return out


def match_name(name: object, honours: dict[str, str]) -> tuple[bool, str | None]:
    """Return (matched, reason) if any name token is a known honour."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return False, None
    for token in re.findall(r"[A-Za-z]+", str(name)):
        key = token.upper()
        if key in honours:
            return True, f"{key} ({honours[key]})"
    return False, None


def flag_post_nominal(df: pd.DataFrame, honours=None, name_col: str = "Name"):
    """Add post-nominal honour flag + reason columns to a copy of ``df``."""
    if honours is None:
        honours = load_honours()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: match_name(n, honours))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
