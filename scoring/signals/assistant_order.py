"""Assistant / PA order signal — an order placed by an executive/personal
assistant on behalf of a wealthy principal (a proxy for a UHNW client).

Detects the administrative-purchase markers EAs/PAs leave in an order:
  - "c/o", "care of", "FAO", "Attn" in an address line;
  - a PA / EA / "on behalf of" marker in the customer name;
  - a role-based email LOCAL-PART segment (pa, ea, assistant, exec, office, ...),
    matched by segment so "paul@"/"sean@" don't false-fire.

These are NOISY alone (a small shop's admin@, or an ordinary "c/o" forward), so
this is a SUPPORTING signal (see SUPPORTING_SIGNALS in combine.py): it counts
only when a stronger wealth signal has also fired — i.e. exactly when it means
"an assistant is buying for a wealthy principal" (a wealth-firm email domain, a
Mayfair HQ address, a prime postcode, etc.).
"""
from __future__ import annotations

import re

import pandas as pd

from scoring.signals.delivery_venue import ALL_ADDRESS_COLS, _combine_rows

FLAG_COL = "assistant_order"
REASON_COL = "assistant_order_reason"

# "c/o" / "care of" / "FAO" / "Attn" anywhere in the (raw) address.
_ADDR_MARKER = re.compile(r"\bc\s*/\s*o\b|\bcare\s+of\b|\bf\.?\s?a\.?\s?o\.?\b|\battn\.?\b", re.I)
# PA / EA / "on behalf of" / "personal|executive assistant" in the name.
_NAME_MARKER = re.compile(
    r"\bon behalf of\b|\b(?:personal|executive)\s+assistant\b|\bassistant\b"
    r"|\b[pe]\.?\s?a\.?\s+to\b|\(\s*[pe]\.?\s?a\.?\s*\)",
    re.I,
)
# Role segments in the email local-part (matched as whole segments).
_ROLE_SEGMENTS = {
    "pa", "ea", "assistant", "asst", "exec", "execoffice", "office", "admin",
    "secretary", "concierge", "guestservices", "guestrelations", "butler",
    "frontoffice", "reservations",
}


def _email_local(email: object) -> str:
    if email is None or (isinstance(email, float) and pd.isna(email)):
        return ""
    text = str(email).strip().lower()
    return text.split("@", 1)[0] if "@" in text else ""


def detect(name: object, email: object, address: object) -> tuple[bool, str | None]:
    """Return (is_assistant_order, reason)."""
    if name and _NAME_MARKER.search(str(name)):
        return True, f"name marker: {str(name).strip()}"
    local = _email_local(email)
    if local and any(seg in _ROLE_SEGMENTS for seg in re.split(r"[._\-]+", local)):
        return True, f"role email: {local}"
    if address:
        m = _ADDR_MARKER.search(str(address))
        if m:
            return True, f"c/o address: {m.group(0).strip()}"
    return False, None


def flag_assistant_order(
    df: pd.DataFrame,
    name_col: str = "Name",
    email_col: str = "EMAIL_ADDR",
    address_cols=None,
) -> pd.DataFrame:
    """Add assistant-order flag + reason columns to a copy of ``df``."""
    out = df.copy()
    cols = [c for c in (address_cols or ALL_ADDRESS_COLS) if c in out.columns]
    addr = _combine_rows(out, cols) if cols else pd.Series([""] * len(out), index=out.index)
    names = out[name_col] if name_col in out.columns else pd.Series([None] * len(out), index=out.index)
    emails = out[email_col] if email_col in out.columns else pd.Series([None] * len(out), index=out.index)
    results = [
        detect(n, e, a)
        for n, e, a in zip(names.tolist(), emails.tolist(), addr.tolist())
    ]
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
