"""Headless test for the extension's thread reader (`Halia.readMessages` in content/core.js).

The brief is only as good as what it reads off the page, and the helpdesk / DM surfaces render
messages in obfuscated markup: nested wrappers that all match a loose selector, and a which-side
hint that usually sits on an ancestor row rather than on the text node. Both of those produced real
bugs (duplicated messages; the associate's own replies attributed to the client), so the reader's
logic is exercised here against jsdom fixtures shaped like that markup.

Auto-skips where Node + jsdom aren't installed, so it never breaks CI. To enable locally:
    cd tests/js && npm install
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_JS_DIR = Path(__file__).parent / "js"
_HARNESS = _JS_DIR / "thread_reader_smoke.js"
_WA_HARNESS = _JS_DIR / "whatsapp_reader_smoke.js"
_SHAPE_HARNESS = _JS_DIR / "shape_smoke.js"


def _enabled() -> bool:
    return bool(shutil.which("node")) and (_JS_DIR / "node_modules" / "jsdom").is_dir()


pytestmark = pytest.mark.skipif(
    not _enabled(),
    reason="Node + jsdom not installed — extension JS test skipped (enable: cd tests/js && npm install)",
)


def _run(harness: Path) -> dict:
    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def read() -> dict:
    return _run(_HARNESS)


@pytest.fixture(scope="module")
def wa() -> dict:
    return _run(_WA_HARNESS)


def test_nested_matches_collapse_to_one_message_each(read):
    """A loose [class*="message"] selector matches the wrapper AND the body; only the innermost
    node should become a message, or every message is read twice."""
    assert [m["text"] for m in read["nested"]] == ["Is the coat back?", "Let me check."]


def test_side_hint_is_read_from_the_ancestor_row(read):
    """The 'outgoing' hint sits on the parent row, not on the text node. Losing it attributes the
    associate's own replies to the client, which poisons the brief."""
    assert [m["from"] for m in read["nested"]] == ["them", "me"]


def test_side_attribution_reads_class_aria_label_and_test_ids(read):
    sides = read["sides"]
    assert [m["from"] for m in sides] == ["me", "them", "me"]
    assert sides[1]["text"] == "Do you have it in a 38?"    # unknown side defaults to the client


def test_empty_nodes_dropped_and_tail_kept(read):
    assert [m["text"] for m in read["limit"]] == ["three", "four"]


def test_no_matches_is_an_empty_list(read):
    assert read["none"] == []


# ── WhatsApp reader: it churns class names, so the brief broke there while Gmail kept working ──────
def test_whatsapp_reads_bubbles_and_sides(wa):
    """The stable copyable-text anchor: text and direction both come through, timestamp excluded."""
    assert wa["stable"] == [
        {"from": "them", "text": "Is the trench back in a 38?"},
        {"from": "me", "text": "Let me hold one for you."},
    ]


def test_whatsapp_survives_class_churn(wa):
    """When the .message-in/-out classes vanish, the reader still reads the text off the anchor
    (direction degrades to the client, the safe default) instead of going silent — this is the bug."""
    assert [m["text"] for m in wa["churned"]] == ["Are you open Sunday?"]
    assert wa["churned"][0]["from"] == "them"


def test_whatsapp_legacy_rows_still_work(wa):
    """No copyable-text anchor at all: fall back to the old .message-in/.message-out rows."""
    assert wa["legacy"] == [
        {"from": "them", "text": "Do you deliver to Paris?"},
        {"from": "me", "text": "We do, next-day."},
    ]


def test_whatsapp_no_open_chat_is_empty(wa):
    assert wa["empty"] == []


def test_the_house_shaping_rules_behave(  # noqa: D103
):
    """web/site/static/halia-shape.js — what every surface runs on a template before it is sent.

    Until now this had no test in any language, which is how three clients ended up with three
    algorithms. See tests/js/shape_smoke.js for the cases.
    """
    out = _run(_SHAPE_HARNESS)
    assert out["total"] >= 15
    assert out["failed"] == [], out["failed"]
