"""Pack the operator's real .local reference tables into the committable encrypted bundle.

Run this after (re)generating the local tables (build_company_controllers.py / build_us_insiders.py
/ build_charity_trustees.py). It writes reference_data/private_bundle.enc — CIPHERTEXT encrypted
with HALIA_ENCRYPTION_KEY (the same key production uses). Commit that file and deploy; the app
decrypts it at startup so the high-precision signals load on the box. The raw .local tables stay
git-ignored — only the encrypted bundle is ever committed.

    HALIA_ENCRYPTION_KEY=... python scripts/pack_reference_data.py

The key must match the one set on the Render service, or the box cannot decrypt the bundle.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from halia import reference_bundle as rb  # noqa: E402


def main() -> None:
    packed, size = rb.write_bundle()
    if not packed:
        print("No .local reference tables found to pack. Generate them first (build_*.py).")
        return
    print(f"Wrote {rb.BUNDLE_PATH} ({len(packed)} table(s), {size:,} bytes):")
    for rel in packed:
        print(f"  - {rel}")
    print("Commit reference_data/private_bundle.enc and deploy; it decrypts at startup.")


if __name__ == "__main__":
    main()
