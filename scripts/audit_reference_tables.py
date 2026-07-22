"""Audit the reference tables for rows that would quietly produce a wrong reason.

A signal is only as good as the list behind it. One bad row is worse than a missing one: a
too-generic entry fires on ordinary customers in every tenant's book at once, and the reason it
prints looks exactly as authoritative as a correct one. Nothing checks these lists today beyond
review at the time of writing.

Two passes, in that order:

1. **Deterministic.** Exact duplicates, entries that fail their own table's guard, near-duplicates
   that differ only by punctuation or a legal suffix, suspiciously short entries, and rows whose
   shape does not match the table's columns. These are certain, cost nothing, and run without a
   key.

2. **Judgement.** Whatever survives goes to Claude with the table's purpose, asking which entries
   would match something other than what the table claims — a firm name that is also an ordinary
   word, a "hotel" that is really a street, a domain that belongs to a different organisation.

Both passes only ever **report**. This script never edits a reference file: it prints a review list
for a human to act on, because deleting a row silently narrows every tenant's coverage and that
should be a decision, not a side effect.

Stand-alone operator tool (NOT imported by the app or tests). Pass 1 needs nothing; pass 2 needs
HALIA_LLM_API_KEY.

Usage
-----
    python scripts/audit_reference_tables.py --list                  # what can be audited
    python scripts/audit_reference_tables.py employers              # one table, both passes
    python scripts/audit_reference_tables.py venues --plain         # deterministic pass only
    python scripts/audit_reference_tables.py --all
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (HNW_AREAS_FILE, SIGNAL_VENUES_FILE, WEALTH_DOMAINS_FILE)  # noqa: E402

_SUFFIXES = re.compile(
    r"\b(LTD|LIMITED|PLC|LLP|LLC|INC|CORP|CORPORATION|CO|GROUP|HOLDINGS|INTERNATIONAL|SA|AG|NV|BV)\b")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", str(text or "").upper())).strip()


def _bare(text: str) -> str:
    """Normalised and stripped of legal suffixes, so "Acme Ltd" and "Acme Limited" collide."""
    return re.sub(r"\s+", " ", _SUFFIXES.sub(" ", _norm(text))).strip()


# Each table: the column that holds the thing being matched, what the list is FOR (given to the
# model), and an optional guard the entries are supposed to satisfy.
def _venue_guard(value: str) -> bool:
    from scoring.signals.delivery_venue import _normalize, usable_alias
    return all(usable_alias(_normalize(p)) for p in str(value).split(";") if _normalize(p))


TABLES = {
    "employers": {
        "path": WEALTH_DOMAINS_FILE, "col": 0, "label_col": 1,
        "purpose": "Domains of employers whose staff are likely to be wealthy: banks, private "
                   "equity, hedge funds, wealth managers, family offices, elite law firms. A "
                   "customer's e-mail domain is matched against this list.",
        "guard": None,
    },
    "venues": {
        "path": SIGNAL_VENUES_FILE, "col": 0, "label_col": 2,
        "purpose": "Named venues whose appearance in a DELIVERY ADDRESS is a wealth signal: "
                   "luxury hotels, private members' clubs, private terminals, marinas. The "
                   "aliases column holds the phrases searched for inside a full street address.",
        "guard": _venue_guard,
    },
    "areas": {
        "path": HNW_AREAS_FILE, "col": 0, "label_col": 2,
        "purpose": "Districts and towns whose appearance in an address is a wealth signal.",
        "guard": None,
    },
}


def _rows(path: Path) -> list[tuple[int, list[str]]]:
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for n, row in enumerate(csv.reader(fh), 1):
            if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            if n == 1 and row[0].strip().lower() in ("venue", "domain", "area", "name"):
                continue
            out.append((n, row))
    return out


def _deterministic(rows: list[tuple[int, list[str]]], spec: dict) -> list[str]:
    """Certain problems, found without a model."""
    findings: list[str] = []
    seen: dict[str, int] = {}
    bare: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for line, row in rows:
        key = row[spec["col"]].strip()
        norm = _norm(key)
        if not norm:
            findings.append(f"line {line}: empty entry")
            continue
        if norm in seen:
            findings.append(f"line {line}: duplicate of line {seen[norm]} ({key!r})")
        else:
            seen[norm] = line
        bare[_bare(key)].append((line, key))
        if len(norm) <= 2:
            findings.append(f"line {line}: suspiciously short ({key!r})")
        guard = spec.get("guard")
        if guard is not None:
            checked = row[spec["label_col"]] if spec["label_col"] < len(row) else ""
            if checked.strip() and not guard(checked):
                findings.append(f"line {line}: fails this table's own alias guard ({key!r})")
    for group in bare.values():
        if len(group) > 1:
            where = ", ".join(f"line {ln} {k!r}" for ln, k in group)
            findings.append(f"near-duplicates differing only by punctuation or suffix: {where}")
    return findings


_SYSTEM = (
    "You are auditing one reference list used by a wealth-signal engine. You are given the list's "
    "purpose and a batch of its entries. Report only entries that would match something OTHER than "
    "what the list is for.\n\n"
    "Look for: an entry that is also an ordinary word or a common place name and would fire on "
    "unrelated customers; an entry that names a street or district rather than the thing the list "
    "collects; an entry that plainly belongs to a different kind of organisation than the list "
    "describes; and an entry that looks like a typo of another.\n\n"
    "Do not report an entry merely because you have not heard of it: these lists are deliberately "
    "long-tail, and a real but obscure firm is exactly what they are for. Reporting nothing is a "
    "correct and expected answer. You are producing a list for a human to review; you are not "
    "deciding anything."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entry": {"type": "string"},
                    "problem": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["entry", "problem", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


def _judgement(llm, rows: list[tuple[int, list[str]]], spec: dict, batch: int = 60) -> list[str]:
    line_of = {_norm(r[spec["col"]]): ln for ln, r in rows}
    out: list[str] = []
    entries = [r[spec["col"]].strip() for _ln, r in rows]
    for i in range(0, len(entries), batch):
        chunk = entries[i:i + batch]
        print(f"  reviewing {i + 1}-{i + len(chunk)} …", file=sys.stderr)
        got = llm.structured(
            _SYSTEM,
            f"Purpose of this list:\n{spec['purpose']}\n\nEntries:\n"
            + "\n".join(f"- {e}" for e in chunk) + "\n\nReport only the problems.",
            _SCHEMA, max_tokens=2000)
        for f in (got or {}).get("findings") or []:
            ln = line_of.get(_norm(f.get("entry")))
            where = f"line {ln}" if ln else "entry"
            out.append(f"{where}: {f.get('entry')!r} — {f.get('problem')} "
                       f"[{f.get('confidence')} confidence]")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("table", nargs="?", choices=sorted(TABLES), help="which list to audit")
    ap.add_argument("--all", action="store_true", help="audit every table")
    ap.add_argument("--list", action="store_true", help="show the tables that can be audited")
    ap.add_argument("--plain", action="store_true", help="deterministic pass only, no model")
    args = ap.parse_args()

    if args.list or not (args.table or args.all):
        for name, spec in sorted(TABLES.items()):
            print(f"{name:12} {spec['path']}")
        return 0

    names = sorted(TABLES) if args.all else [args.table]
    llm = None
    if not args.plain:
        from halia import llm as _llm
        if _llm.available():
            llm = _llm
        else:
            print("No LLM key configured: running the deterministic pass only.", file=sys.stderr)

    total = 0
    for name in names:
        spec = TABLES[name]
        rows = _rows(Path(spec["path"]))
        print(f"\n=== {name} · {len(rows)} entries · {spec['path']} ===")
        findings = _deterministic(rows, spec)
        for f in findings:
            print(f"  [certain]  {f}")
        if llm is not None:
            for f in _judgement(llm, rows, spec):
                print(f"  [review]   {f}")
                findings.append(f)
        if not findings:
            print("  nothing to review.")
        total += len(findings)

    print(f"\n{total} thing(s) to review. Nothing was changed: edit the files yourself.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
