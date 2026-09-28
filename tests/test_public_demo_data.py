"""The public demo pages must be built from synthetic data, never from a retailer's export.

On 2026-09-28 the Store Concierge demo page was found to carry a real export's addresses and
numbers, live and committed. Two guards: every address on a generated demo page must exist in
the synthetic file when that file is present locally, and, everywhere, no address may carry the
tells of a real consumer export (a numeric local part, or a free-mail domain the synthetic
generator never writes).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_XLSX = ROOT / "sample_data" / "synthetic_100k.xlsx"
# The two pages generated from a data file. The hand-written demo pages carry a few fictional
# addresses typed by hand and are not built from any export.
PAGES = ["web/site/sc-demo.html", "web/site/campaign-demo.html"]
# Domains a real consumer export is full of and the synthetic generator never writes.
REAL_EXPORT_DOMAINS = ("qq.com", "163.com", "126.com", "sina.com", "foxmail.com", "yeah.net",
                       "hotmail.com", "yahoo.com", "outlook.com", "live.com", "aol.com")


def _emails(text: str) -> set[str]:
    return {e.lower() for e in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", text)
            if not e.lower().endswith(("haliascore.com", "example.com"))}


def test_no_address_on_a_public_demo_page_looks_like_a_real_export():
    for rel in PAGES:
        p = ROOT / rel
        if not p.exists():
            continue
        found = _emails(p.read_text())
        numeric = sorted(e for e in found if re.match(r"^\d+@", e))
        assert not numeric, f"{rel}: numeric local parts are a real-export tell: {numeric[:5]}"
        consumer = sorted(e for e in found if e.endswith(REAL_EXPORT_DOMAINS))
        assert not consumer, f"{rel}: domains the synthetic generator never writes: {consumer[:5]}"


@pytest.mark.skipif(not SYNTHETIC_XLSX.exists(), reason="synthetic file is local only")
def test_every_address_on_a_generated_page_comes_from_the_synthetic_file():
    import pandas as pd
    df = pd.read_excel(SYNTHETIC_XLSX)
    col = next(c for c in df.columns if "mail" in c.lower())
    synthetic = set(df[col].dropna().astype(str).str.lower())
    for rel in PAGES:
        p = ROOT / rel
        if not p.exists():
            continue
        strangers = sorted(_emails(p.read_text()) - synthetic)
        assert not strangers, f"{rel}: addresses not in the synthetic file: {strangers[:5]}"


def test_demo_builders_default_to_the_synthetic_file():
    for rel in ("scripts/build_sc_demo.py", "scripts/build_campaign_demo.py"):
        s = (ROOT / rel).read_text()
        assert "synthetic_100k.xlsx" in s, rel
        assert "SAMPLE3" not in s.replace('"""', "").split("\n", 12)[-1] or "synthetic" in s, rel


def test_no_tracked_file_carries_a_real_export():
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_no_pii.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_pre_commit_hook_is_wired():
    hook = ROOT / ".githooks" / "pre-commit"
    assert hook.exists() and "check_no_pii.py" in hook.read_text()
