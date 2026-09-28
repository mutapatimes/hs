#!/usr/bin/env python3
"""Refuse tracked text that carries the tells of a real customer export.

Run by the pre-commit hook over staged files and by tests over the whole tree. A real consumer
export shows itself in ways synthetic data never does: email addresses with purely numeric local
parts and free-mail domains the synthetic generator never writes.
Test fixtures may carry a handful of such addresses on purpose, so tests/ is exempt.

Usage: check_no_pii.py [paths...]   (no paths = every tracked text file under web/, docs/, halia/,
scripts/, extension/, ios/, wordpress/)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = {".html", ".htm", ".md", ".txt", ".csv", ".json", ".js", ".py", ".swift", ".xml", ".yml", ".yaml"}
EXEMPT = ("tests/", "sample_data/README.md")
REAL_DOMAINS = r"(qq|163|126|sina|foxmail|yeah)\.(com|net)"
NUMERIC_LOCAL = re.compile(r"(?<![\w.])\d{5,}@[A-Za-z0-9.-]+\.[a-z]{2,}")
CONSUMER_CN = re.compile(r"[A-Za-z0-9._%+-]+@" + REAL_DOMAINS)


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "web", "docs", "halia", "scripts", "extension", "ios", "wordpress"],
                         cwd=ROOT, capture_output=True, text=True).stdout.split()
    return [ROOT / p for p in out]


def check(path: Path) -> list[str]:
    rel = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
    if rel.startswith(EXEMPT) or path.suffix.lower() not in TEXT or not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    problems = []
    numeric = set(NUMERIC_LOCAL.findall(text))
    if numeric:
        problems.append(f"{rel}: {len(numeric)} email(s) with a numeric local part, e.g. {sorted(numeric)[0][:3]}***")
    cn = set(CONSUMER_CN.findall(text))
    if cn:
        problems.append(f"{rel}: {len(cn)} address(es) at a domain the synthetic data never uses")
    return problems


def main(argv: list[str]) -> int:
    paths = [Path(a) if Path(a).is_absolute() else ROOT / a for a in argv] or tracked_files()
    problems = [p for path in paths for p in check(path)]
    for p in problems:
        print("PII CHECK:", p)
    if problems:
        print("\nRefusing: this looks like a real customer export. Build public pages from "
              "sample_data/synthetic_100k.xlsx.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
