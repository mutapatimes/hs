"""scripts/build_prospects.py — split store name from city, assign country + priority."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_prospects", Path(__file__).resolve().parents[1] / "scripts" / "build_prospects.py")
bp = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(bp)


def test_splits_name_from_multiword_city():
    r = bp.parse_line("* Bergdorf Goodman New York")
    assert r["name"] == "Bergdorf Goodman" and r["city"] == "New York" and r["priority"] == 1


def test_store_named_after_its_city():
    r = bp.parse_line("* Dover Street Market London London")
    assert r["name"] == "Dover Street Market London" and r["city"] == "London"


def test_priority_by_region():
    assert bp.parse_line("* Browns London")["priority"] == 1          # UK
    assert bp.parse_line("* Antonioli Milan")["priority"] == 2        # EU
    assert bp.parse_line("* Restir Tokyo")["priority"] == 3           # rest (Japan)
    assert bp.parse_line("* Restir Tokyo")["country"] == "Japan"


def test_longest_city_wins():
    r = bp.parse_line("* A Ma Manière Washington DC")
    assert r["city"] == "Washington DC" and r["priority"] == 1


def test_dedup_and_sort():
    rows = bp.build(["* Browns London", "* Browns London", "* Antonioli Milan"])
    assert len(rows) == 2 and rows[0]["priority"] <= rows[1]["priority"]
