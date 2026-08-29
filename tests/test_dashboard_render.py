"""Headless render smoke test for the dashboard template.

A `new Function()` syntax check can't catch a *runtime* error, and one such error (a const used
before its declaration — a temporal dead zone) once aborted the whole dashboard init and left every
view blank while the static stats still showed. This test renders the dashboard and runs its script
in jsdom (Node), failing if the script throws or the Overview/Clients don't render.

It auto-skips where Node + jsdom aren't installed, so it never breaks CI. To enable locally:
    cd tests/js && npm install
"""
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from build_mvp import render_payload

_JS_DIR = Path(__file__).parent / "js"
_HARNESS = _JS_DIR / "dashboard_smoke.js"


def _enabled() -> bool:
    return bool(shutil.which("node")) and (_JS_DIR / "node_modules" / "jsdom").is_dir()


pytestmark = pytest.mark.skipif(
    not _enabled(),
    reason="Node + jsdom not installed — dashboard smoke test skipped (enable: cd tests/js && npm install)",
)


def _client(i: int, grade: str, tier: str) -> dict:
    recent = int(time.time()) - 2 * 86400   # 2 days ago -> inside the default 30-day window
    return {
        "id": f"C-{i:04d}", "cid": f"c{i}", "init": "JD", "name": f"Client {i}",
        "email": f"c{i}@example.com", "phone": "", "loc": "London", "city": "London",
        "outward": "SW1", "area": "London", "tier": tier, "grade": grade, "score": 90 - i,
        "spend": 4000, "latent": 40000, "count": 2, "confidence": 2, "ordersCount": 3,
        "aov": 1333, "last": "recent", "lastSort": recent, "orders": [], "cart": None,
        "shopifyUrl": "", "reco": {"line": "Reach out personally.", "action": "Email"},
        "signals": [{"seg": "work", "d": "Work email: example", "w": 1.0}],
    }


def _payload() -> dict:
    return {
        "segments": {"work": {"label": "Work email"}},
        "data": [_client(1, "A*", "A1"), _client(2, "A", "A"), _client(3, "B", "B")],
        "orders": [{"orderId": "1001", "date": "2026-07-08", "amount": 3000, "status": "Unfulfilled",
                    "statusCat": "new", "items": 2, "name": "Client 1", "first": "Client",
                    "email": "c1@example.com", "phone": "", "grade": "A*", "tier": "A1", "score": 89}],
        "stat_scored": "3", "stat_latent": "£120k", "stat_count": "3", "stat_avgspend": "£4k",
        "stat_toptier": "2", "full_history": True,
    }


def test_dashboard_script_runs_and_renders(tmp_path):
    f = tmp_path / "dash.html"
    f.write_text(render_payload(_payload()), encoding="utf-8")
    out = subprocess.run(["node", str(_HARNESS), str(f)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:2000]
    res = json.loads(out.stdout.strip().splitlines()[-1])
    # 1) no runtime error during init (this is what the TDZ regression violated)
    assert res["errors"] == [], "\n".join(res["errors"])[:2000]
    # 2) the Overview and Clients views actually rendered content
    assert res["ovDonut"] > 0, "Overview grade-mix donut did not render"
    assert res["rows"] > 0, "Clients table did not render"


def test_dashboard_script_never_contains_html_comment_or_script_openers():
    """Inside a <script>, an HTML comment opener puts the tokenizer into its escaped state; a later
    <script> in any string then ends the element early and the rest of the app renders as text."""
    import re
    from pathlib import Path
    html = Path("web/template.html").read_text()
    for m in re.finditer(r"<script>(.*?)</script>", html, re.S):
        assert "<!--" not in m.group(1), "HTML comment inside a script block"
        assert "<script" not in m.group(1), "script opener inside a script block"


def test_injected_snippets_land_after_the_app_script(monkeypatch):
    """The chat widget and the admin nav are inserted before the document's LAST </body>, never
    at a "</body>" that appears inside the app's own script text (which split the script in two
    and rendered the rest of the app as page text)."""
    from halia.api.content import _before_body
    page = "<html><body><script>var s = '</body>';</script><p>x</p></body></html>"
    out = _before_body(page, "<script>w()</script>")
    assert out.index("w()") > out.index("<p>x</p>")
    html = render_payload(_payload(), body_extra="<ui-nav-menu></ui-nav-menu>")
    assert html.rindex("<ui-nav-menu>") > html.rindex("</script>") - 200 and "</body>" not in html.split("<ui-nav-menu>")[0].split("\n<script>\n",1)[1].split("</script>")[0]


def test_hosted_page_with_chat_widget_never_leaks_script_as_text(monkeypatch):
    import html5lib
    monkeypatch.setenv("HALIA_CHAT_WIDGET_ID", "abc")
    from halia.api.content import with_chat_widget
    h = with_chat_widget(render_payload(_payload()))
    doc = html5lib.parse(h, namespaceHTMLElements=False)
    leaked = []
    def walk(el):
        if el.tag in ("script", "style"):
            return
        if el.text and "getElementById" in el.text:
            leaked.append(el.text[:60])
        for c in el:
            walk(c)
            if c.tail and "getElementById" in c.tail:
                leaked.append(c.tail[:60])
    walk(doc.find("body"))
    assert leaked == []
