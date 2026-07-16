"""scripts/build_brand_prospects.py — DTC brand list -> Halia-fit-prioritised prospects."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_brand_prospects", Path(__file__).resolve().parents[1] / "scripts" / "build_brand_prospects.py")
bp = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(bp)


def test_sweet_spot_is_p1():
    # low entry + high ceiling = widest hiding gap = P1
    assert bp.build(["Reformation\t40\t1000\tcult"])[0]["priority"] == "P1"


def test_retailers_demoted():
    assert bp.build(["Anthropologie\t20\t1000\tbroad"])[0]["priority"] == "P3"


def test_narrow_gap_is_p3():
    assert bp.build(["Posse\t120\t430\t"])[0]["priority"] == "P3"


def test_sorted_p1_first_then_by_ceiling():
    rows = bp.build(["Posse\t120\t430\t", "SIR.\t60\t1200\t", "Reformation\t40\t1000\t"])
    assert rows[0]["priority"] == "P1" and rows[0]["price_high"] >= rows[1]["price_high"]
    assert rows[-1]["name"] == "Posse"
