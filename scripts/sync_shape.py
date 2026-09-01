"""Copy the house shaping rules into the Chrome extension.

`web/site/static/halia-shape.js` is the one copy. The Outlook task pane loads it from
/static/halia-shape.js, but a Manifest V3 content script may not load remote code, so the
extension needs the file on disk. This writes it there byte for byte.

Run: .venv/bin/python scripts/sync_shape.py
Guarded by tests/test_shape_sync.py, which fails if the two ever drift.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "web/site/static/halia-shape.js"
COPY = ROOT / "extension/content/shape.js"


def sync() -> bool:
    """Write the copy if it differs. True when something changed."""
    text = SOURCE.read_text(encoding="utf-8")
    if COPY.is_file() and COPY.read_text(encoding="utf-8") == text:
        return False
    COPY.write_text(text, encoding="utf-8")
    return True


if __name__ == "__main__":
    print(("wrote " if sync() else "already current: ") + str(COPY.relative_to(ROOT)))
