"""build_company_controllers.py: keep/tier rules, exercised through the real CLI.

Scripts are stand-alone operator tools (never imported by the app or tests), so this runs the
script as a subprocess against small synthetic PSC + Basic Company Data fixtures and asserts on
the CSV it writes — the same invocation the operator uses.
"""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

_PSC_LINES = [
    # eponymous + large + wealth SIC -> prime
    '{"company_number":"10000001","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Jane","surname":"Marandi"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # NON-eponymous but large + wealth SIC -> kept, high
    '{"company_number":"10000002","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Nadia","surname":"Okonkwo"},'
    '"natures_of_control":["voting-rights-75-to-100-percent"]}}',
    # same person in two companies: small generic (match) + large wealth (prime) -> prime wins
    '{"company_number":"10000003","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Rex","surname":"Hollingsworth"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    '{"company_number":"10000004","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Rex","surname":"Hollingsworth"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # common surname -> dropped in pass 1
    '{"company_number":"10000005","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Derek","surname":"Smith"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # control band below 75% -> dropped in pass 1
    '{"company_number":"10000006","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Priya","surname":"Aldingham"},'
    '"natures_of_control":["ownership-of-shares-25-to-50-percent"]}}',
    # non-eponymous, large but NOT a wealth industry -> dropped in pass 2
    '{"company_number":"10000007","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Leo","surname":"Farrington"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # micro-entity family vehicle: eponymous + wealth SIC -> kept at match (the exception)
    '{"company_number":"10000008","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Tessa","surname":"Winterbourne"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # micro-entity, eponymous but generic industry -> still a shell, dropped
    '{"company_number":"10000009","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Hugo","surname":"Brantfield"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # dormant -> always dropped, wealth SIC or not
    '{"company_number":"10000010","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Zara","surname":"Quillon"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # corporate PSC -> never a person, ignored
    '{"company_number":"10000001","data":{"kind":"corporate-entity-person-with-significant-control",'
    '"name":"BigCo Nominees Ltd","natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # non-eponymous + wealth SIC but "TOTAL EXEMPTION FULL" accounts = a SMALL company: its
    # category contains the word FULL, which a substring size test wrongly read as large -> dropped
    '{"company_number":"10000011","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Mira","surname":"Castellane"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # same trap for "UNAUDITED ABRIDGED" (contains AUDITED; abridged = small regime) -> dropped
    '{"company_number":"10000012","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Omar","surname":"Vanterpool"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    # TWO DISTINCT PEOPLE (different birth month/year) share the name "Oliver Hartwell"; the name
    # is ambiguous, so a bare name match is never certain. The one WITH a service address is kept
    # as an ADDRESS-GATED row (district GL54); the one without a usable address is dropped.
    # (Rex above appears twice with the SAME dob key: one person, many companies — kept, ungated.)
    '{"company_number":"10000013","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Oliver","surname":"Hartwell"},'
    '"date_of_birth":{"month":3,"year":1970},'
    '"address":{"postal_code":"GL54 1AB"},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
    '{"company_number":"10000014","data":{"kind":"individual-person-with-significant-control",'
    '"name_elements":{"forename":"Oliver","surname":"Hartwell"},'
    '"date_of_birth":{"month":11,"year":1985},'
    '"natures_of_control":["ownership-of-shares-75-to-100-percent"]}}',
]

# Basic Company Data ships header names with a leading space on most columns; mirror that.
_COMPANIES_CSV = """CompanyName, CompanyNumber,CompanyStatus,CompanyCategory, Accounts.AccountCategory, SICCode.SicText_1
MARANDI INVESTMENTS LTD,10000001,Active,Private Limited Company,FULL,68209 - Other letting and operating of own or leased real estate
BELGRAVIA PRIME ESTATES LTD,10000002,Active,Private Limited Company,FULL,68100 - Buying and selling of own real estate
HOLLINGSWORTH TRADING LTD,10000003,Active,Private Limited Company,SMALL,47710 - Retail sale of clothing
HOLLINGSWORTH ESTATES LTD,10000004,Active,Private Limited Company,FULL,68100 - Buying and selling of own real estate
SMITH HOLDINGS LTD,10000005,Active,Private Limited Company,FULL,70100 - Activities of head offices
ALDINGHAM ESTATES LTD,10000006,Active,Private Limited Company,FULL,68100 - Buying and selling of own real estate
NORTHERN STEEL FABRICATION LTD,10000007,Active,Private Limited Company,FULL,25110 - Manufacture of metal structures
WINTERBOURNE INVESTMENTS LTD,10000008,Active,Private Limited Company,MICRO ENTITY,64209 - Activities of other holding companies
BRANTFIELD JOINERY LTD,10000009,Active,Private Limited Company,MICRO ENTITY,43320 - Joinery installation
QUILLON INVESTMENTS LTD,10000010,Active,Private Limited Company,DORMANT,64209 - Activities of other holding companies
RIVERSIDE PROPERTY HOLDINGS LTD,10000011,Active,Private Limited Company,TOTAL EXEMPTION FULL,68100 - Buying and selling of own real estate
CITYVIEW LETTINGS LTD,10000012,Active,Private Limited Company,UNAUDITED ABRIDGED,68209 - Other letting and operating of own or leased real estate
HARTWELL ESTATES LTD,10000013,Active,Private Limited Company,FULL,68100 - Buying and selling of own real estate
HARTWELL INVESTMENTS LTD,10000014,Active,Private Limited Company,FULL,64209 - Activities of other holding companies
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Run the script once against the fixtures; return {name: [(tier, company, industry, district)]}."""
    tmp = tmp_path_factory.mktemp("chbuild")
    psc = tmp / "psc.txt"
    psc.write_text("\n".join(_PSC_LINES) + "\n", encoding="utf-8")
    companies = tmp / "companies.csv"
    companies.write_text(_COMPANIES_CSV, encoding="utf-8")
    out = tmp / "out.csv"
    proc = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "build_company_controllers.py"),
         "--psc", str(psc), "--companies", str(companies), "--replace", "--out", str(out)],
        cwd=_REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    rows = {}
    with out.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row or row[0].startswith("#") or row[0].strip().lower() == "name":
                continue
            rows.setdefault(row[0], []).append((row[1], row[2], row[3], row[4]))
    return rows


def test_eponymous_large_wealth_is_prime(built):
    tier, company, industry, district = built["Jane Marandi"][0]
    assert tier == "prime" and company == "Marandi Investments Ltd" and industry == "real estate"
    assert district == ""              # unique name: matches on name alone


def test_non_eponymous_large_wealth_kept_at_high(built):
    tier, company, industry, _ = built["Nadia Okonkwo"][0]
    assert tier == "high" and industry == "real estate"


def test_multi_company_owner_takes_highest_tier(built):
    # Rex's small trading company streams before his large estates company; prime must win.
    tier, company, _, district = built["Rex Hollingsworth"][0]
    assert tier == "prime" and company == "Hollingsworth Estates Ltd"
    assert district == ""              # one person (same dob key twice): no gate needed


def test_micro_family_vehicle_kept_at_match(built):
    # Eponymous + wealth-SIC micro-entity: the quiet family vehicle exception, dampened tier.
    tier, _, industry, _ = built["Tessa Winterbourne"][0]
    assert tier == "match" and industry == "holding"


def test_ambiguous_name_kept_only_with_address_gate(built):
    # Two people share "Oliver Hartwell": the one with a service address survives as a gated
    # row carrying their postcode district; the one without an address is dropped.
    entries = built["Oliver Hartwell"]
    assert len(entries) == 1
    tier, company, _, district = entries[0]
    assert district == "GL54" and company == "Hartwell Estates Ltd" and tier == "prime"


def test_dropped_candidates(built):
    for name in ("Derek Smith",        # common surname
                 "Priya Aldingham",    # below 75% control
                 "Leo Farrington",     # non-eponymous, large but not a wealth industry
                 "Hugo Brantfield",    # micro-entity, generic industry
                 "Zara Quillon",       # dormant
                 "Mira Castellane",    # TOTAL EXEMPTION FULL = small, not "FULL" (substring trap)
                 "Omar Vanterpool"):   # UNAUDITED ABRIDGED = small, not "AUDITED" (substring trap)
        assert name not in built
    assert len(built) == 5             # the 4 unconditional + the gated Hartwell


def test_output_loads_into_signal(built, tmp_path):
    # The written schema must round-trip through the signal loader: industry in the reason,
    # and the gated row keeping its district requirement.
    from scoring.signals import companies_house as ch
    out = tmp_path / "table.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "tier", "company", "industry", "district"])
        for name, entries in built.items():
            for tier, company, industry, district in entries:
                w.writerow([name, tier, company, industry, district])
    table = ch.load_controllers(out)
    reason, tier, district = table[ch._normalize("Jane Marandi")][0]
    assert tier == "prime" and district == ""
    assert reason == ("Jane Marandi — controls Marandi Investments Ltd, a real estate company "
                      "(Companies House)")
    # the gated Hartwell row round-trips and only matches with the agreeing postcode
    assert not ch.match_name("Oliver Hartwell", table)[0]
    assert ch.match_name("Oliver Hartwell", table, districts={"GL54"})[0]
