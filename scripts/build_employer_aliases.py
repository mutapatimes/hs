"""Build the employer-alias reference table with Claude, offline.

The work-email signal also reads the order's COMPANY_NAME, matching it against the employer names
derived from reference_data/domains/wealth_employer_domains.csv. That match is exact (on a
normalised, punctuation-stripped form), which is what keeps the reason a bare fact — and which also
means the same employer misses whenever it is typed the way people actually type it:

    "J.P. Morgan"                normalises to  J P MORGAN     vs canonical  JPMORGAN     -> miss
    "Goldman Sachs International"                               contains     GOLDMAN SACHS -> hit
    "Goldmann Sachs"             (misspelling)                                             -> miss
    "PwC"                        vs "PricewaterhouseCoopers"                               -> miss

This script asks Claude for the ways each canonical employer is really written, validates every
proposal hard, and writes the survivors to reference_data/domains/employer_aliases.csv.

The point of doing it here rather than at scoring time:

* **No model runs during scoring.** The output is a CSV; matching stays deterministic, free, and
  identical for every tenant, so a reason still cites the reference table and not a guess.
* **No customer data is involved.** The model only ever sees the names of large employers that are
  already public in our own reference list. Nothing about any customer leaves anywhere.
* **A human reviews it.** The output is a sorted CSV committed to git, so every added alias shows
  up as a reviewable diff before it can affect a single score.

Validation is deliberately harsher than the prompt. A proposal is dropped unless it maps to an
employer already in the domain list, is distinctive enough not to over-match free text, and is
claimed by exactly one employer. The loader (scoring.signals.work_email.load_aliases) re-applies
the same rules at read time, so even a hand-edited row cannot introduce an employer.

Stand-alone operator tool (NOT imported by the app or tests). Needs HALIA_LLM_API_KEY.

Usage
-----
    python scripts/build_employer_aliases.py                  # all employers, write the table
    python scripts/build_employer_aliases.py --limit 40       # a cheap first pass
    python scripts/build_employer_aliases.py --dry-run        # print, write nothing
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import EMPLOYER_ALIASES_FILE, WEALTH_DOMAINS_FILE  # noqa: E402
from scoring.signals.work_email import (_alias_ok, _norm_name, employer_names,  # noqa: E402
                                        load_domains)

_BATCH = 20          # employers per call: enough context to be consistent, small enough to verify

_SYSTEM = (
    "You are compiling a reference table of how large, well-known employers are actually written "
    "in a retailer's 'company name' order field. For each employer you are given, list the forms a "
    "real person or billing system would type.\n\n"
    "Include: registered legal-entity forms (Goldman Sachs International, Rothschild & Co), "
    "spacing and punctuation variants (J.P. Morgan for JPMorgan), widely used short forms that are "
    "still unmistakable (PwC for PricewaterhouseCoopers), and misspellings common enough to matter "
    "(Goldmann Sachs).\n\n"
    "Exclude, without exception: any form that could name a DIFFERENT organisation; generic words "
    "(Capital, Partners, Group, Bank, Global); a single short or common word; ticker symbols; "
    "parent, subsidiary or sister companies, which are different employers; and anything you are "
    "not confident about. An alias must be unmistakably this employer and no one else.\n\n"
    "Returning an empty list for an employer is a correct and expected answer. Never invent an "
    "organisation, and never map an alias to an employer that was not given to you."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "employers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "canonical": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["canonical", "aliases"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["employers"],
    "additionalProperties": False,
}


def _canonical_employers(limit: int | None) -> list[str]:
    """The employer labels already in the domain table, longest first (aliases excluded)."""
    names = employer_names(load_domains(WEALTH_DOMAINS_FILE), aliases_path=None)
    labels = sorted({org for _norm, org in names})
    return labels[:limit] if limit else labels


def _propose(llm, batch: list[str]) -> list[dict]:
    listed = "\n".join(f"- {name}" for name in batch)
    got = llm.structured(
        _SYSTEM,
        f"Employers:\n{listed}\n\nList the real-world written forms of each.",
        _SCHEMA, max_tokens=3000)
    return (got or {}).get("employers") or []


def _accept(proposals: list[dict], canonical: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Keep only aliases that pass every rule. Returns (alias_norm -> label, rejection notes)."""
    kept: dict[str, str] = {}
    ambiguous: set[str] = set()
    notes: list[str] = []
    for entry in proposals:
        canon_norm = _norm_name(entry.get("canonical"))
        if canon_norm not in canonical:
            notes.append(f"unknown employer, dropped: {entry.get('canonical')!r}")
            continue
        label = canonical[canon_norm]
        for alias in entry.get("aliases") or []:
            norm = _norm_name(alias)
            if not norm:
                continue
            if norm in canonical:
                continue                                   # already a canonical name
            if not _alias_ok(norm):
                notes.append(f"too generic, dropped: {alias!r} ({label})")
                continue
            if norm in kept and kept[norm] != label:
                notes.append(f"claimed by two employers, dropped: {alias!r}")
                ambiguous.add(norm)
                continue
            kept[norm] = label
    for norm in ambiguous:
        kept.pop(norm, None)
    return kept, notes


def _write(rows: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write("# How each employer is actually written in a company-name field.\n")
        fh.write("# Generated by scripts/build_employer_aliases.py and reviewed as a git diff.\n")
        fh.write("# Read deterministically at match time: no model runs during scoring.\n")
        fh.write("# An alias whose canonical is not in wealth_employer_domains.csv is ignored.\n")
        w = csv.writer(fh)
        w.writerow(["alias", "canonical"])
        for alias, canon in sorted(rows.items()):
            w.writerow([alias, canon])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="only the first N employers")
    ap.add_argument("--out", type=Path, default=EMPLOYER_ALIASES_FILE)
    ap.add_argument("--dry-run", action="store_true", help="print the table, write nothing")
    args = ap.parse_args()

    from halia import llm
    if not llm.available():
        print("No LLM key configured. Set HALIA_LLM_API_KEY (or ANTHROPIC_API_KEY) and re-run.",
              file=sys.stderr)
        return 2

    labels = _canonical_employers(args.limit)
    canonical = {_norm_name(label): label for label in labels}
    print(f"{len(labels)} employers in the reference list.", file=sys.stderr)

    kept: dict[str, str] = {}
    notes: list[str] = []
    for i in range(0, len(labels), _BATCH):
        batch = labels[i:i + _BATCH]
        print(f"  {i + 1}-{i + len(batch)} …", file=sys.stderr)
        got, why = _accept(_propose(llm, batch), canonical)
        for norm, label in got.items():
            if norm in kept and kept[norm] != label:
                notes.append(f"claimed by two employers across batches, dropped: {norm!r}")
                kept.pop(norm, None)
                continue
            kept.setdefault(norm, label)
        notes.extend(why)

    for note in notes[:40]:
        print(f"  {note}", file=sys.stderr)
    if len(notes) > 40:
        print(f"  … and {len(notes) - 40} more rejections", file=sys.stderr)
    print(f"{len(kept)} aliases accepted, {len(notes)} rejected.", file=sys.stderr)

    if args.dry_run:
        for alias, canon in sorted(kept.items()):
            print(f"{alias},{canon}")
        return 0
    _write(kept, args.out)
    print(f"Wrote {args.out} — review the diff before committing.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
