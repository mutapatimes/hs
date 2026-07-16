"""scripts/build_all_prospects.py — merge all segments into one deduplicated master sheet."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_all_prospects", Path(__file__).resolve().parents[1] / "scripts" / "build_all_prospects.py")
bap = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(bap)


def test_master_merges_three_segments():
    rows = bap.build()
    segs = {r["segment"] for r in rows}
    assert segs == {"womenswear", "menswear", "accessible-dtc"}
    assert len(rows) > 100


def test_no_duplicate_brands():
    rows = bap.build()
    names = [r["brand"].lower().rstrip() for r in rows]
    assert len(names) == len(set(names))


def test_schema_and_routing():
    r = bap.build()[0]
    assert set(r) >= {"segment", "priority", "brand", "detail", "ownership", "why_you", "note"}
    assert r["priority"] in ("P1", "P2", "P3")


def test_sorted_womenswear_p1_first():
    rows = bap.build()
    assert rows[0]["segment"] == "womenswear" and rows[0]["priority"] == "P1"
