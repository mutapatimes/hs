#!/usr/bin/env python3
"""Refuse tracked text that carries the tells of a real customer export.

Run by the pre-commit hook over staged files, by CI and the tests over the tree, and by the app
at start-up over the public tree (halia.datavault.assert_public_tree_clean). The rules live in
halia/datavault.py.

Usage: check_no_pii.py [paths...]   (no paths = the whole tree)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from halia import datavault  # noqa: E402


def main(argv: list[str]) -> int:
    if argv:
        problems = [p for a in argv for p in datavault.scan_file(Path(a) if Path(a).is_absolute() else datavault.ROOT / a)]
    else:
        problems = datavault.scan_tree()
    for p in problems:
        print("PII CHECK:", p)
    if problems:
        print("\nRefusing: this looks like a real customer export. Public pages are built from "
              "sample_data/synthetic_*.xlsx only; real exports live in the vault "
              f"({datavault.vault_dir()}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
