"""scripts/build_designer_prospects.py — curated modern-feminine womenswear prospects."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_designer_prospects", Path(__file__).resolve().parents[1] / "scripts" / "build_designer_prospects.py")
bp = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(bp)


def test_indie_core_lane_is_p1():
    r = bp.build([("Toteme", "minimal", "indie", "x")])[0]
    assert r["priority"] == "P1"


def test_group_owned_demoted():
    assert bp.build([("Chloe", "romantic", "group", "x")])[0]["priority"] == "P3"
    assert bp.build([("Ganni", "contemporary", "large", "x")])[0]["priority"] == "P2"


def test_adjacent_lane_indie_is_p2():
    assert bp.build([("Aje", "resort", "indie", "x")])[0]["priority"] == "P2"


def test_dedup_case_and_whitespace():
    rows = bp.build([("Ulla Johnson", "romantic", "indie", "a"), ("ulla johnson ", "romantic", "indie", "b")])
    assert len([r for r in rows if r["brand"].strip().lower() == "ulla johnson"]) == 1


def test_default_set_is_curated_and_p1_heavy():
    rows = bp.build()
    assert len(rows) > 40
    assert sum(1 for r in rows if r["priority"] == "P1") >= 25   # the sweet spot dominates
