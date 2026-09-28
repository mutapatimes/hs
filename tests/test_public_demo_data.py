"""The public demo pages must be built from synthetic data, never from a retailer's export.

On 2026-09-28 the Store Concierge demo page was found to carry a real export's addresses and
numbers, live and committed. The synthetic generator writes addresses as first.last<digits>@ a
free-mail domain, so every address on a served demo page must match that shape; a real export
breaks it at the first row.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = re.compile(r"^[a-z]+\.[a-z]+\d+@(gmail|outlook|icloud|yahoo|hotmail)\.com$")
# The two pages generated from a data file. The hand-written demo pages carry a few fictional
# addresses typed by hand and are not built from any export.
PAGES = ["web/site/sc-demo.html", "web/site/campaign-demo.html"]


def _emails(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", text))


def test_every_address_on_a_public_demo_page_is_synthetic():
    for rel in PAGES:
        p = ROOT / rel
        if not p.exists():
            continue
        found = {e for e in _emails(p.read_text()) if not e.endswith(("haliascore.com", "example.com"))}
        bad = sorted(e for e in found if not SYNTHETIC.match(e))
        assert not bad, f"{rel} carries addresses that are not synthetic: {bad[:5]}"


def test_demo_builders_default_to_the_synthetic_file():
    for rel in ("scripts/build_sc_demo.py", "scripts/build_campaign_demo.py"):
        s = (ROOT / rel).read_text()
        assert "synthetic_100k.xlsx" in s and "SAMPLE3" not in s.split("def ")[-1], rel
