"""Carry the operator's real .local reference tables to production — without ever putting named
individuals in git.

The high-precision reference tables (UK company controllers, UK charity trustees, US SEC insiders)
are generated on the operator's own machine from public bulk data and are git-ignored, because they
name private individuals. But a git -> Docker -> Render deploy only ships COMMITTED files, so on the
box those signals would silently fall back to their inert fictional seeds.

This bridges the gap using the key the box already has:
  * pack()   gathers the local tables into one gzip blob and Fernet-encrypts it with
             HALIA_ENCRYPTION_KEY (the same key that already encrypts stored secrets), producing
             reference_data/private_bundle.enc — CIPHERTEXT, safe to commit (unreadable without the
             key, which lives only in the operator's env / Render secrets, never in the repo).
  * unpack() runs at app startup and, when the key is present, decrypts the blob and writes any
             MISSING .local table into place, so the real signals load in production. It never
             overwrites an existing local table (in dev the operator's own copy always wins).

Operator flow:  regenerate the .local tables -> `python scripts/pack_reference_data.py` -> commit
reference_data/private_bundle.enc -> deploy. If HALIA_ENCRYPTION_KEY is unset on the box, unpack is
a no-op and the signals fall back to their seeds (logged once), so nothing breaks.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from halia.crypto import _fernet

_ROOT = Path(__file__).resolve().parents[1]              # repo root (halia/ is one level down)
BUNDLE_PATH = _ROOT / "reference_data" / "private_bundle.enc"

# The git-ignored real tables to carry. Relative paths so they unpack to the same tree on the box.
LOCAL_TABLES = [
    "reference_data/companies/uk_company_controllers.local.csv",
    "reference_data/companies/us_insiders.local.csv",
    "reference_data/charities/uk_charity_trustees.local.csv",
]


def pack(root: Path | None = None) -> tuple[bytes, list[str]]:
    """Gather the existing local tables -> (encrypted blob, list of packed relpaths).

    Raises if no key is configured (packing plaintext names would defeat the point).
    """
    root = root if root is not None else _ROOT
    f = _fernet()
    if f is None:
        raise RuntimeError(
            "HALIA_ENCRYPTION_KEY not set — cannot pack the private reference bundle. "
            "Set it (the same Fernet key used in production) and retry.")
    tables = {}
    for rel in LOCAL_TABLES:
        p = root / rel
        if p.exists():
            tables[rel] = p.read_text(encoding="utf-8")
    blob = gzip.compress(json.dumps({"_v": 1, "tables": tables}).encode("utf-8"), 9)
    return f.encrypt(blob), list(tables)


def write_bundle(root: Path | None = None) -> tuple[list[str], int]:
    """Pack and write reference_data/private_bundle.enc. -> (packed relpaths, byte size)."""
    root = root if root is not None else _ROOT
    token, packed = pack(root)
    BUNDLE_PATH.write_bytes(token)
    return packed, len(token)


def unpack(root: Path | None = None, overwrite: bool = False) -> list[str]:
    """Restore missing local tables from the committed bundle. -> list of relpaths written.

    No-op (returns []) when the bundle is absent or no key is configured — in that case the signals
    simply use their inert seeds. Never overwrites an existing table unless ``overwrite=True``.
    """
    root = root if root is not None else _ROOT
    if not BUNDLE_PATH.exists():
        return []
    f = _fernet()
    if f is None:
        print("WARNING: private_bundle.enc present but HALIA_ENCRYPTION_KEY not set — high-precision "
              "reference tables will fall back to their seeds.", file=sys.stderr)
        return []
    try:
        data = json.loads(gzip.decompress(f.decrypt(BUNDLE_PATH.read_bytes())))
    except Exception as exc:  # wrong key, truncated file, tampering — degrade to seeds, don't crash
        print(f"WARNING: could not read private_bundle.enc ({exc}); reference tables use their seeds.",
              file=sys.stderr)
        return []
    written = []
    for rel, text in data.get("tables", {}).items():
        dest = root / rel
        if dest.exists() and not overwrite:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        written.append(rel)
    return written
