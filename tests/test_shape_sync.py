"""The house shaping rules exist once. This is what stops a second copy drifting.

`web/site/static/halia-shape.js` is served to the Outlook task pane; MV3 forbids a content script
from loading remote code, so `scripts/sync_shape.py` writes an identical copy into the Chrome
extension. Two surfaces that shape the same template differently send different messages, which is
exactly the bug this file exists to prevent.
"""
import re

from scripts.sync_shape import COPY, SOURCE


def test_the_extension_copy_matches_the_served_one():
    assert COPY.is_file(), "run .venv/bin/python scripts/sync_shape.py"
    assert COPY.read_text(encoding="utf-8") == SOURCE.read_text(encoding="utf-8"), (
        "extension/content/shape.js has drifted from web/site/static/halia-shape.js. "
        "Edit the one in web/site/static, then run scripts/sync_shape.py.")


def test_nothing_else_still_carries_its_own_copy():
    # The regexes used to be pasted into badge.js and compose.js as well. If either grows its own
    # again, two surfaces will disagree about what "no sign-off" means.
    root = SOURCE.parent.parent.parent.parent
    for name in ("extension/ui/badge.js", "extension/content/compose.js"):
        text = (root / name).read_text(encoding="utf-8")
        assert "GREET_RE" not in text, f"{name} should use window.HaliaShape, not its own copy"
        assert "SIGN_LINE" not in text, f"{name} should use window.HaliaShape, not its own copy"


def test_every_surface_that_shapes_loads_the_module_first():
    # A content script that calls window.HaliaShape before shape.js has run is a blank panel.
    root = SOURCE.parent.parent.parent.parent
    manifest = (root / "extension/manifest.json").read_text(encoding="utf-8")
    for block in re.findall(r'"js"\s*:\s*\[(.*?)\]', manifest, re.S):
        files = re.findall(r'"([^"]+)"', block)
        if "ui/badge.js" in files:
            assert files.index("content/shape.js") < files.index("ui/badge.js"), files
    worker = (root / "extension/background.js").read_text(encoding="utf-8")
    for block in re.findall(r'js:\s*\[(.*?)\]', worker, re.S):
        files = re.findall(r'"([^"]+)"', block)
        if "ui/badge.js" in files or "content/compose.js" in files:
            assert files[0] == "content/shape.js", files
