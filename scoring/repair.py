"""Repair obvious damage in a customer record before scoring, and rate the record's own quality.

Signals match customer fields against reference tables by exact, normalised comparison. That is
what keeps a reason a bare fact ("Work email: Goldman Sachs" because the domain is in the table),
but it also means a single mistyped character silently costs a match: `SW1A lAA` never meets the
HNWI postcode list, `@gmial.com` never meets the consumer-domain list, and the client is scored as
though the evidence were absent. Most of that damage is mechanical, so most of it can be undone
without guessing.

Two things happen here, and the split matters:

1. **Repair** — deterministic, conservative, and auditable. A repair is applied only when the
   result is provably well-formed and the original provably was not, so it can turn "no match"
   into "possible match" but can never rewrite a value that was already good. Every change is
   recorded in ``REPAIRS_COL`` so a merchant can see exactly what was read and why.

2. **Quality** — a 0-100 score of how much the record can be trusted, plus the flags behind it
   (``QUALITY_COL`` / ``FLAGS_COL``). Placeholder names, unusable addresses and missing contact
   details are worth surfacing in their own right: a low-quality record is not a low-value client,
   it is a client the store cannot act on.

Nothing here infers *meaning*. Guessing what a mangled value was meant to be is a separate,
optional AI pass (`halia/repair_ai.py`), and even there the guess only ever becomes a proposal that
this module's deterministic matchers must accept.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

QUALITY_COL = "data_quality"
FLAGS_COL = "data_flags"
REPAIRS_COL = "data_repairs"

# A full UK postcode, spacing-insensitive. Used as the accept test for a repair: we only keep a
# repaired postcode that satisfies this and an original that did not.
_UK_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# Glyphs people and OCR confuse in both directions. Applied only at positions where the UK format
# leaves no ambiguity about whether a digit or a letter belongs there.
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6"}
_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B"}

# Consumer domains typed wrong often enough to be worth a bounded correction.
_COMMON_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com",
    "yahoo.com", "yahoo.co.uk", "icloud.com", "me.com", "mac.com", "aol.com", "msn.com",
    "protonmail.com", "proton.me", "gmx.com", "btinternet.com", "sky.com", "virginmedia.com",
})

# Values people type to get past a required field. Not names, not addresses.
_PLACEHOLDERS = frozenset({
    "test", "testing", "tester", "asdf", "asdfasdf", "qwerty", "abc", "abcd", "xxx", "xx", "x",
    "na", "n/a", "none", "null", "nil", "unknown", "no name", "noname", "customer", "guest",
    "-", "--", ".", "..", "0", "1", "1234", "12345", "aaa", "sample", "demo", "delete",
})


def _s(value) -> str:
    """A trimmed string for any cell, including NaN and None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _is_placeholder(text: str) -> bool:
    t = re.sub(r"[^a-z0-9/ .-]+", "", text.lower()).strip()
    return bool(t) and t in _PLACEHOLDERS


# ── postcode ─────────────────────────────────────────────────────────────────────────
def repair_postcode(value) -> tuple[Optional[str], Optional[str]]:
    """Return (repaired postcode, rule) or (None, None) when nothing safe can be done.

    Only three positions are unambiguous across every UK postcode form: the first character is a
    letter, and the inward code is always digit-letter-letter. Those are the only characters we
    coerce, and the result is kept only if it becomes a valid postcode when the original was not.
    """
    raw = _s(value).upper()
    if not raw:
        return None, None
    if _UK_POSTCODE.match(raw):
        return None, None                      # already good: never touch it
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    if not 5 <= len(compact) <= 7:
        return None, None
    head, inward = list(compact[:-3]), list(compact[-3:])
    head[0] = _TO_LETTER.get(head[0], head[0])          # outward always starts with a letter
    inward[0] = _TO_DIGIT.get(inward[0], inward[0])     # inward is digit, letter, letter
    inward[1] = _TO_LETTER.get(inward[1], inward[1])
    inward[2] = _TO_LETTER.get(inward[2], inward[2])
    fixed = f"{''.join(head)} {''.join(inward)}"
    if not _UK_POSTCODE.match(fixed):
        return None, None
    rule = "spacing" if re.sub(r"[^A-Z0-9]", "", fixed) == compact else "glyph"
    return fixed, rule


# ── email ────────────────────────────────────────────────────────────────────────────
def _edit_distance_1(a: str, b: str) -> bool:
    """Whether one edit (insert, delete or substitute) turns a into b. Cheap and bounded."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        # a single transposition reads as one slip to a human, and is the commonest typo of all
        return len(diff) == 2 and diff[1] == diff[0] + 1 and \
            a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    short, long_ = (a, b) if la < lb else (b, a)
    i = j = 0
    skipped = False
    while i < len(short) and j < len(long_):
        if short[i] != long_[j]:
            if skipped:
                return False
            skipped = True
            j += 1
            continue
        i += 1
        j += 1
    return True


def repair_email(value, known_domains: Optional[frozenset] = None) -> tuple[Optional[str], Optional[str]]:
    """Return (repaired address, rule) or (None, None).

    Fixes a domain that is one edit away from a domain we know is real, and only when the typed
    domain is not itself known. ``known_domains`` lets a caller widen the target set (the work-email
    table, say) so a mistyped employer domain can be recovered too.
    """
    raw = _s(value).lower().replace(" ", "")
    if not raw or "@" not in raw:
        return None, None
    local, _, domain = raw.rpartition("@")
    if not local or not domain:
        return None, None
    targets = _COMMON_DOMAINS | (known_domains or frozenset())
    if domain in targets:
        return None, None                      # already a domain we recognise
    hits = [d for d in targets if _edit_distance_1(domain, d)]
    if len(hits) != 1:
        return None, None                      # no candidate, or ambiguous: leave it alone
    return f"{local}@{hits[0]}", "domain"


# ── name ─────────────────────────────────────────────────────────────────────────────
_PARTICLES = {"de", "del", "della", "der", "di", "du", "la", "le", "van", "von", "bin", "ibn", "y"}


def repair_name(value) -> tuple[Optional[str], Optional[str]]:
    """Re-case a name typed entirely in one case, so the signals that read a name's shape can.

    Only touches a name that is wholly upper or wholly lower; a name with any existing mixed case
    is the customer's own and is left exactly as typed.
    """
    raw = _s(value)
    if not raw or len(raw) > 120:
        return None, None
    letters = [c for c in raw if c.isalpha()]
    if not letters or not (all(c.isupper() for c in letters) or all(c.islower() for c in letters)):
        return None, None

    def _word(w: str, first: bool) -> str:
        low = w.lower()
        if not first and low in _PARTICLES:
            return low                                       # "van der Berg", not "Van Der Berg"
        for pre in ("mc", "mac", "o'"):
            if low.startswith(pre) and len(low) > len(pre):
                return pre.capitalize() + low[len(pre):].capitalize()
        return "-".join(p.capitalize() for p in low.split("-"))

    words = raw.split()
    fixed = " ".join(_word(w, i == 0) for i, w in enumerate(words))
    return (fixed, "case") if fixed != raw else (None, None)


# ── quality ──────────────────────────────────────────────────────────────────────────
def quality_of(row) -> tuple[int, list[str]]:
    """Score how far this record can be trusted (0-100) and say what is wrong with it.

    A low score is a data problem, not a verdict on the client: it means the store cannot reliably
    reach or read this person, so both outreach and any signal drawn from these fields are shakier.
    """
    name, email = _s(row.get("Name")), _s(row.get("EMAIL_ADDR"))
    phone = _s(row.get("PHONE"))
    zips = [_s(row.get("LATEST_BILLING_ZIP")), _s(row.get("LATEST_SHIPPING_ZIP"))]
    flags: list[str] = []
    score = 100

    if not name:
        flags.append("no name")
        score -= 25
    elif _is_placeholder(name):
        flags.append("placeholder name")
        score -= 35
    elif len(re.sub(r"[^A-Za-z]", "", name)) < 2:
        flags.append("unusable name")
        score -= 25
    elif " " not in name.strip():
        flags.append("first name only")
        score -= 5

    if not email:
        flags.append("no email")
        score -= 25
    elif not _EMAIL.match(email):
        flags.append("malformed email")
        score -= 20
    elif _is_placeholder(email.split("@")[0]):
        flags.append("placeholder email")
        score -= 20

    if not any(zips):
        flags.append("no address")
        score -= 15
    else:
        best = next(z for z in zips if z)
        if not _UK_POSTCODE.match(best.upper()) and repair_postcode(best)[0] is None \
                and not re.search(r"\d", best):
            flags.append("unusable postcode")      # no digits anywhere: not a postcode at all
            score -= 10

    if not phone:
        flags.append("no phone")
        score -= 5

    if name and email and name.lower().replace(" ", "") == email.split("@")[0].lower():
        flags.append("name copied from email")
        score -= 5

    return max(0, min(100, score)), flags


# ── the pass over a whole book ───────────────────────────────────────────────────────
_ZIP_COLS = ("LATEST_BILLING_ZIP", "LATEST_SHIPPING_ZIP")


def repair_frame(df: pd.DataFrame, known_domains: Optional[frozenset] = None) -> pd.DataFrame:
    """Repair what is safely repairable and add the quality columns. Returns a new frame.

    Applied before the signals run, so a recovered postcode or domain gets its fair chance at the
    reference tables. Every change is listed per row in ``REPAIRS_COL`` and is reversible by
    reading it; nothing is written back to the merchant's store.
    """
    out = df.copy()
    if len(out) == 0:
        for col, dtype in ((QUALITY_COL, "int64"), (FLAGS_COL, "object"), (REPAIRS_COL, "object")):
            out[col] = pd.Series(dtype=dtype)
        return out

    repairs: list[list[str]] = [[] for _ in range(len(out))]

    def _apply(col: str, fn) -> None:
        if col not in out.columns:
            return
        values = out[col].tolist()
        changed = False
        for i, value in enumerate(values):
            fixed, rule = fn(value)
            if fixed is None:
                continue
            repairs[i].append(f"{col}: {_s(value)} -> {fixed} ({rule})")
            values[i] = fixed
            changed = True
        if changed:
            out[col] = values

    for zip_col in _ZIP_COLS:
        _apply(zip_col, repair_postcode)
    _apply("EMAIL_ADDR", lambda v: repair_email(v, known_domains))
    _apply("Name", repair_name)

    quality = out.apply(quality_of, axis=1)
    out[QUALITY_COL] = [q for q, _f in quality]
    out[FLAGS_COL] = [f for _q, f in quality]
    out[REPAIRS_COL] = repairs
    return out
