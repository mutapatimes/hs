"""Widen the delivery-venue aliases with Claude, offline.

reference_data/venues/signal_venues.csv already has an `aliases` column: the phrases to look for
inside a delivery address. Coverage there is the whole game, because an address is written a dozen
ways and only an exact phrase match counts:

    "The Lanesborough, Hyde Park Corner"   -> hits (LANESBOROUGH is listed)
    "Lanesborough Hotel"                   -> hits
    "Ritz-Carlton Residences"              -> misses if only "RITZ CARLTON" is listed

This script asks Claude for the additional ways each venue already in the file is really written,
validates every proposal, and merges the survivors back into that same column. It never adds a
venue: the row set is exactly what it was, only the aliases grow.

Same reasoning as scripts/build_employer_aliases.py — do it offline, not at scoring time:

* **No model runs during scoring.** Matching stays an exact phrase comparison, so a reason is
  still a bare fact about the address.
* **No customer data is involved.** The model only sees the names of well-known public venues that
  are already in our own reference list.
* **A human reviews it.** The output is the same CSV with a reviewable diff, comments and row
  order preserved.

Every proposal must pass delivery_venue.usable_alias — the same guard the loader applies at read
time — so an alias that would fire on an ordinary street cannot get in from either direction.

Stand-alone operator tool (NOT imported by the app or tests). Needs HALIA_LLM_API_KEY.

Usage
-----
    python scripts/build_venue_aliases.py --dry-run      # print the additions, change nothing
    python scripts/build_venue_aliases.py --limit 20     # a cheap first pass
    python scripts/build_venue_aliases.py                # merge into signal_venues.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SIGNAL_VENUES_FILE  # noqa: E402
from scoring.signals.delivery_venue import _normalize, usable_alias  # noqa: E402

_BATCH = 15

_SYSTEM = (
    "You are compiling the phrases that identify well-known luxury venues inside a shipping "
    "address. For each venue you are given, list the other ways that venue's name really appears "
    "when someone types an address: the form with and without 'The', the hotel-group form "
    "(Ritz-Carlton Residences), a widely used local shorthand, and the building or tower name if "
    "the venue is known by one.\n\n"
    "Exclude, without exception: the street or district the venue sits on (Park Lane, Knightsbridge, "
    "Mayfair) — those are addresses, not venues, and would fire on every neighbour; any phrase that "
    "could name a different venue in another city; generic descriptions (Grand Hotel, The Residence); "
    "and anything you are not confident about.\n\n"
    "An alias must identify this venue and nothing else. Returning an empty list is a correct and "
    "expected answer. Never introduce a venue that was not given to you."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "venues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "venue": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["venue", "aliases"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["venues"],
    "additionalProperties": False,
}


def _rows(path: Path) -> list[list[str]]:
    """Every line of the reference file, comments and blanks included, so a merge keeps them."""
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def _is_data(row: list[str]) -> bool:
    name = row[0].strip() if row else ""
    return bool(name) and not name.startswith("#") and name != "venue"


def _propose(llm, batch: list[tuple[str, str]]) -> dict[str, list[str]]:
    listed = "\n".join(f"- {name} (currently: {existing or 'none'})" for name, existing in batch)
    got = llm.structured(
        _SYSTEM,
        f"Venues:\n{listed}\n\nList the additional written forms of each.",
        _SCHEMA, max_tokens=3000)
    return {e.get("venue", ""): (e.get("aliases") or []) for e in ((got or {}).get("venues") or [])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="only the first N venues")
    ap.add_argument("--file", type=Path, default=SIGNAL_VENUES_FILE)
    ap.add_argument("--dry-run", action="store_true", help="print the additions, change nothing")
    args = ap.parse_args()

    from halia import llm
    if not llm.available():
        print("No LLM key configured. Set HALIA_LLM_API_KEY (or ANTHROPIC_API_KEY) and re-run.",
              file=sys.stderr)
        return 2

    rows = _rows(args.file)
    data_idx = [i for i, r in enumerate(rows) if _is_data(r)]
    if args.limit:
        data_idx = data_idx[:args.limit]

    # Every alias already claimed, so we never propose a phrase another venue owns.
    claimed: dict[str, str] = {}
    for i in (j for j, r in enumerate(rows) if _is_data(r)):
        for part in (rows[i][2] if len(rows[i]) > 2 else "").split(";"):
            norm = _normalize(part)
            if norm:
                claimed[norm] = rows[i][0].strip()

    print(f"{len(data_idx)} venues to widen.", file=sys.stderr)
    added: dict[int, list[str]] = {}
    rejected: list[str] = []

    for start in range(0, len(data_idx), _BATCH):
        chunk = data_idx[start:start + _BATCH]
        batch = [(rows[i][0].strip(), (rows[i][2] if len(rows[i]) > 2 else "")) for i in chunk]
        print(f"  {start + 1}-{start + len(chunk)} …", file=sys.stderr)
        proposals = _propose(llm, batch)
        for i in chunk:
            venue = rows[i][0].strip()
            for alias in proposals.get(venue, []):
                norm = _normalize(alias)
                if not norm:
                    continue
                if not usable_alias(norm):
                    rejected.append(f"too generic: {alias!r} ({venue})")
                    continue
                if norm in claimed:
                    if claimed[norm] != venue:
                        rejected.append(f"claimed by {claimed[norm]!r}: {alias!r} ({venue})")
                    continue                                   # already listed, or another's
                claimed[norm] = venue
                added.setdefault(i, []).append(norm)

    total = sum(len(v) for v in added.values())
    for note in rejected[:30]:
        print(f"  {note}", file=sys.stderr)
    if len(rejected) > 30:
        print(f"  … and {len(rejected) - 30} more rejections", file=sys.stderr)
    print(f"{total} aliases added across {len(added)} venues, {len(rejected)} rejected.",
          file=sys.stderr)

    if args.dry_run or not total:
        for i, aliases in sorted(added.items()):
            print(f"{rows[i][0].strip()}: {'; '.join(aliases)}")
        return 0

    for i, aliases in added.items():
        while len(rows[i]) < 3:
            rows[i].append("")
        existing = rows[i][2].strip()
        rows[i][2] = "; ".join([p for p in [existing] if p] + aliases)
    with args.file.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    print(f"Merged into {args.file} — review the diff before committing.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
