"""Name-mismatch signal — the email's implied owner is a different person from the account name.

The purest, keyword-free form of the staff/assistant pattern: one person orders (their name is in
the email) while another is the account holder. An email of sarah.jones@… on an order named
"David Rothschild" is someone buying on behalf of the principal — no role keyword needed, so it is
robust to naming conventions the role lists don't anticipate.

Conservative by design (to avoid false-firing on nicknames or a shared household email): it fires
only when the email local-part is a STRUCTURED personal name — two alphabetic tokens (first.last,
first_last) of 3+ letters each — that shares NO token with the account name, and is not a role or
generic mailbox (pa@, office@, info@, sales@ …). The billing-name ≠ shipping-name variant is even
stronger but needs both names in the frame; flatten_order collapses to one Name today, so that is a
later addition.

It is a SUPPORTING signal (see SUPPORTING_SIGNALS in combine.py): it counts only when a stronger
wealth signal has also fired, so a spouse or partner ordering never surfaces a customer on its own —
it registers exactly when it means "someone is buying for a wealthy principal". The reason text
states only the observed fact (two names differ), never an inference.
"""
from __future__ import annotations

import re

import pandas as pd

from scoring.signals.assistant_order import _ROLE_SEGMENTS, _ROLE_SUBSTRINGS

FLAG_COL = "name_mismatch"
REASON_COL = "name_mismatch_reason"

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "lady", "dame", "lord", "baron",
               "baroness", "hon", "rev", "the", "mx", "madam", "master"}
# Function mailboxes: a name here is a role, not a "different person".
_GENERIC = {"info", "hello", "contact", "mail", "email", "enquiries", "enquiry", "sales", "team",
            "service", "support", "account", "accounts", "orders", "order", "shop", "store",
            "noreply", "reply", "donotreply", "help", "billing", "finance", "marketing", "press"}


def _name_tokens(s: object) -> set:
    """Alphabetic name tokens of 3+ letters, lower-cased, honorifics dropped."""
    return {t for t in re.findall(r"[a-z]+", str(s or "").lower())
            if len(t) >= 3 and t not in _HONORIFICS}


def _email_local(email: object) -> str:
    if email is None or (isinstance(email, float) and pd.isna(email)):
        return ""
    text = str(email).strip().lower()
    return text.split("@", 1)[0] if "@" in text else ""


def _overlaps(a: set, b: set) -> bool:
    """Any shared identity between two token sets (equal, or one contained in the other)."""
    return any(x == y or x in y or y in x for x in a for y in b)


def detect(name: object, email: object) -> tuple[bool, str | None]:
    """Return (is_name_mismatch, reason)."""
    local = _email_local(email)
    if not local or name is None or (isinstance(name, float) and pd.isna(name)):
        return False, None
    segs = [t for t in re.split(r"[._\-0-9]+", local) if t]
    # Role / function mailboxes are assistant_order or non-personal, not a name mismatch.
    if (any(s in _ROLE_SEGMENTS or s in _GENERIC for s in segs)
            or any(sub in local for sub in _ROLE_SUBSTRINGS)):
        return False, None
    email_names = {t for t in segs if len(t) >= 3 and t not in _GENERIC}
    if len(email_names) < 2:                 # need a structured first+last to be confident
        return False, None
    account = _name_tokens(name)
    if not account or _overlaps(email_names, account):
        return False, None
    who = " ".join(sorted(email_names))
    return True, f"email name ({who}) differs from account ({str(name).strip()})"


def flag_name_mismatch(df: pd.DataFrame, name_col: str = "Name",
                       email_col: str = "EMAIL_ADDR") -> pd.DataFrame:
    """Add name-mismatch flag + bare-fact reason columns to a copy of ``df``."""
    out = df.copy()
    names = out[name_col] if name_col in out.columns else pd.Series([None] * len(out), index=out.index)
    emails = out[email_col] if email_col in out.columns else pd.Series([None] * len(out), index=out.index)
    results = [detect(n, e) for n, e in zip(names.tolist(), emails.tolist())]
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
