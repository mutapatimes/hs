"""scripts/build_us_foundation_trustees.py — IRS 990-PF XML -> eponymous-trustee table + signal."""
import importlib.util
from pathlib import Path

import pandas as pd

_SPEC = importlib.util.spec_from_file_location(
    "build_us_foundation_trustees",
    Path(__file__).resolve().parents[1] / "scripts" / "build_us_foundation_trustees.py")
bft = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bft)

from scoring.signals.us_foundation import flag_us_foundation, load_trustees, match_name

# A minimal 990-PF return: the Vanderbilt Family Foundation with two trustees, one eponymous,
# one not, plus a corporate co-trustee (a bank) that must be dropped.
PF_XML = """<?xml version="1.0"?>
<Return xmlns="http://www.irs.gov/efile">
 <ReturnHeader><Filer><BusinessName>
   <BusinessNameLine1Txt>Vanderbilt Family Foundation</BusinessNameLine1Txt>
 </BusinessName></Filer></ReturnHeader>
 <ReturnData>
  <IRS990PF>
   <OfficerDirTrstKeyEmplGrp><PersonNm>Cornelius Vanderbilt</PersonNm><TitleTxt>Trustee</TitleTxt></OfficerDirTrstKeyEmplGrp>
   <OfficerDirTrstKeyEmplGrp><PersonNm>Jane Adams</PersonNm><TitleTxt>Director</TitleTxt></OfficerDirTrstKeyEmplGrp>
   <OfficerDirTrstKeyEmplGrp><PersonNm>Wells Fargo Bank NA</PersonNm><TitleTxt>Co-Trustee</TitleTxt></OfficerDirTrstKeyEmplGrp>
  </IRS990PF>
 </ReturnData>
</Return>"""

# A 990 (not PF) return must be ignored entirely.
NON_PF_XML = """<?xml version="1.0"?>
<Return xmlns="http://www.irs.gov/efile">
 <ReturnHeader><ReturnTypeCd>990</ReturnTypeCd><Filer><BusinessName>
   <BusinessNameLine1Txt>Rockefeller Foundation</BusinessNameLine1Txt></BusinessName></Filer></ReturnHeader>
 <ReturnData><IRS990><OfficerDirTrstKeyEmplGrp><PersonNm>John Rockefeller</PersonNm></OfficerDirTrstKeyEmplGrp></IRS990></ReturnData>
</Return>"""


def _write(tmp_path, name, xml):
    p = tmp_path / name
    p.write_text(xml, encoding="utf-8")
    return p


def test_keeps_only_eponymous_people(tmp_path):
    _write(tmp_path, "pf.xml", PF_XML)
    rows = bft.build([tmp_path])
    names = {v[0] for v in rows.values()}
    assert "Cornelius Vanderbilt" in names          # surname Vanderbilt is in the foundation name
    assert "Jane Adams" not in names                # not eponymous
    assert not any("Wells Fargo" in n or "Bank" in n for n in names)   # corporate co-trustee dropped
    assert list(rows.values())[0][1] == "Vanderbilt Family Foundation"


def test_non_pf_return_ignored(tmp_path):
    _write(tmp_path, "n.xml", NON_PF_XML)
    assert bft.build([tmp_path]) == {}


def test_lastname_first_format(tmp_path):
    xml = PF_XML.replace("<PersonNm>Cornelius Vanderbilt</PersonNm>",
                         "<PersonNm>Vanderbilt, Cornelius</PersonNm>")
    _write(tmp_path, "pf.xml", xml)
    rows = bft.build([tmp_path])
    assert any(v[0] == "Cornelius Vanderbilt" for v in rows.values())


def test_round_trips_through_the_signal(tmp_path):
    _write(tmp_path, "pf.xml", PF_XML)
    out = tmp_path / "us_foundation_trustees.csv"
    bft.write_table(out, bft.build([tmp_path]))
    table = load_trustees(out)
    hit, reason = match_name("Cornelius Vanderbilt", table)
    assert hit and "Vanderbilt Family Foundation" in reason and "IRS 990-PF" in reason

    df = pd.DataFrame([{"Name": "Cornelius Vanderbilt"}, {"Name": "Someone Else"}])
    res = flag_us_foundation(df, table)
    assert bool(res["us_foundation"][0]) and not bool(res["us_foundation"][1])
