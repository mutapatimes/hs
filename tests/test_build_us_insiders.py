"""scripts/build_us_insiders.py — SEC Form 3/4/5 data -> the us_insider reference table + signal."""
import csv
import importlib.util
from pathlib import Path

import pandas as pd

_SPEC = importlib.util.spec_from_file_location(
    "build_us_insiders", Path(__file__).resolve().parents[1] / "scripts" / "build_us_insiders.py")
bui = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bui)

from scoring.signals.us_insider import flag_us_insider, load_insiders, name_key


def _make_quarter(tmp_path):
    """Write a minimal SUBMISSION.tsv + REPORTINGOWNER.tsv (SEC surname-first names)."""
    folder = tmp_path / "2026q1_form345"
    folder.mkdir()
    with (folder / "SUBMISSION.tsv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["ACCESSION_NUMBER", "ISSUERNAME"])
        w.writerow(["0001-24-001", "Tesla Inc"])
        w.writerow(["0001-24-002", "Acme Holdings Inc"])
        w.writerow(["0001-24-003", "Common Co"])
    with (folder / "REPORTINGOWNER.tsv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["ACCESSION_NUMBER", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP",
                    "ISDIRECTOR", "ISOFFICER", "ISTENPERCENTOWNER"])
        w.writerow(["0001-24-001", "Musk Elon", "Director, Officer", "1", "1", "0"])
        w.writerow(["0001-24-002", "Vanderbilt Cornelius", "TenPercentOwner", "0", "0", "1"])
        w.writerow(["0001-24-003", "Smith John", "Director", "1", "0", "0"])   # common surname -> dropped
        w.writerow(["0001-24-002", "Baron Capital Group LLC", "TenPercentOwner", "0", "0", "1"])  # entity -> dropped
    return folder


def test_build_tiers_and_drops_common_surnames(tmp_path):
    rows = bui.build_from_dir(_make_quarter(tmp_path))
    keys = {v[0]: v for v in rows.values()}
    assert "Elon Musk" in keys and keys["Elon Musk"][1] == "insider"      # director/officer
    assert "Cornelius Vanderbilt" in keys and keys["Cornelius Vanderbilt"][1] == "owner"   # 10%
    assert keys["Cornelius Vanderbilt"][2] == "Acme Holdings Inc"         # issuer joined in
    assert not any("Smith" in n for n in keys)                           # common surname dropped
    assert not any("Baron" in n for n in keys)                           # institutional owner dropped
    assert bui._is_person("Musk Elon") and not bui._is_person("Baron Capital Group LLC")


def test_key_is_order_independent():
    assert name_key("Musk Elon") == name_key("Elon Musk")                # surname-first vs first-first
    assert name_key("Timothy D Cook") == name_key("Cook Timothy")        # middle name ignored
    assert name_key("Solo") is None                                      # single token -> no key


def test_write_round_trips_through_the_signal(tmp_path):
    rows = bui.build_from_dir(_make_quarter(tmp_path))
    out = tmp_path / "us_insiders.csv"
    bui.write_table(out, rows)
    table = load_insiders(out)                                           # the live signal reads it back

    df = pd.DataFrame([{"Name": "Elon Musk"}, {"Name": "Cornelius Vanderbilt"}, {"Name": "Jane Doe"}])
    res = flag_us_insider(df, table)
    assert bool(res["us_insider"][0]) and res["us_insider_tier"][0] == "insider"
    assert "SEC filing" in res["us_insider_reason"][0]
    assert bool(res["us_insider"][1]) and res["us_insider_tier"][1] == "owner"
    assert "Acme Holdings Inc" in res["us_insider_reason"][1]
    assert not bool(res["us_insider"][2])                                # unknown name -> no match


def test_merge_keeps_strongest_tier(tmp_path):
    out = tmp_path / "us_insiders.csv"
    bui.write_table(out, {name_key("Elon Musk"): ("Elon Musk", "insider", "Tesla Inc")})
    existing = bui.load_existing(out)
    bui.merge(existing, {name_key("Elon Musk"): ("Elon Musk", "owner", "SpaceX")})
    assert existing[name_key("Elon Musk")][1] == "owner"                 # owner beats insider
