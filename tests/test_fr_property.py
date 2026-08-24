"""France home-value signal (DVF): table load, the country gate, and the ingest script."""
import csv
import subprocess
import sys
from pathlib import Path

import pandas as pd

from scoring.signals import fr_property


def _table():
    return {
        "75006": {"tier": "ultra", "area": "Paris 6e"},
        "06400": {"tier": "prime", "area": "Cannes"},
        "33000": {"tier": "high", "area": "Bordeaux"},
    }


def test_seed_table_loads_and_is_valid():
    table = fr_property.load_values()
    assert "75006" in table and table["75006"]["tier"] == "ultra"
    assert "06230" in table            # leading zero survived (Saint-Jean-Cap-Ferrat)
    assert all(v["tier"] in {"ultra", "prime", "high"} for v in table.values())


def test_country_gate_is_positive_only():
    """75001 is central Paris AND Addison, Texas: a match needs the country to SAY France."""
    t = _table()
    assert fr_property.match_cp("75006", "France", t)[0] is True
    assert fr_property.match_cp("75006", "FR", t)[0] is True
    assert fr_property.match_cp("75006", "Français ", t)[0] is False   # not a country name we accept
    assert fr_property.match_cp("75006", "United States", t)[0] is False
    assert fr_property.match_cp("75006", None, t)[0] is False          # no country -> never fires
    assert fr_property.match_cp("75006", "", t)[0] is False


def test_reason_is_a_grade_never_a_price():
    hit, tier, reason = fr_property.match_cp("06400", "france", _table())
    assert hit and tier == "prime" and reason == "Prime (Cannes)"
    assert "€" not in reason and not any(ch.isdigit() for ch in reason)


def test_flag_pairs_each_postcode_with_its_own_country():
    df = pd.DataFrame({
        "LATEST_BILLING_ZIP": ["75006", "75006", None, "33000"],
        "LATEST_BILLING_ADDRESS4": ["France", "United States", None, "france"],
        "LATEST_SHIPPING_ZIP": [None, "06400", "06400", "75006"],
        "LATEST_SHIPPING_ADDRESS4": [None, "France", "Italy", "United Kingdom"],
    })
    out = fr_property.flag_fr_property(df, table=_table())
    # row 0: billing France -> ultra. row 1: billing gated out, shipping France -> prime.
    # row 2: shipping Italy -> nothing. row 3: billing france high; UK shipping gated out.
    assert list(out[fr_property.FLAG_COL]) == [True, True, False, True]
    assert list(out[fr_property.TIER_COL]) == ["ultra", "prime", None, "high"]


def test_build_script_aggregates_dvf(tmp_path):
    """The ingest turns synthetic DVF rows into tiered €/m² medians, merging curated rows."""
    src = tmp_path / "dvf.csv"
    fields = ["nature_mutation", "type_local", "code_postal", "valeur_fonciere",
              "surface_reelle_bati", "nom_commune"]
    with src.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for _ in range(30):   # 30 flats at 16,000 €/m² -> ultra
            w.writerow({"nature_mutation": "Vente", "type_local": "Appartement",
                        "code_postal": "75007", "valeur_fonciere": "800000",
                        "surface_reelle_bati": "50", "nom_commune": "Paris 7e"})
        for _ in range(30):   # 30 houses at 2,000 €/m² -> below every band, dropped
            w.writerow({"nature_mutation": "Vente", "type_local": "Maison",
                        "code_postal": "45000", "valeur_fonciere": "200000",
                        "surface_reelle_bati": "100", "nom_commune": "Orléans"})
        for _ in range(10):   # too few sales -> dropped despite the price
            w.writerow({"nature_mutation": "Vente", "type_local": "Appartement",
                        "code_postal": "06230", "valeur_fonciere": "1500000",
                        "surface_reelle_bati": "100", "nom_commune": "Saint-Jean-Cap-Ferrat"})
        w.writerow({"nature_mutation": "Echange", "type_local": "Appartement",   # not a sale
                    "code_postal": "75007", "valeur_fonciere": "1", "surface_reelle_bati": "50",
                    "nom_commune": "Paris 7e"})
    out = tmp_path / "fr.csv"
    out.write_text("code_postal,area,median_eur_m2,tier\n68000,Colmar,6500,high\n")  # curated, non-DVF
    r = subprocess.run([sys.executable, "scripts/build_fr_property.py",
                        "--files", str(src), "--out", str(out)],
                       capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0, r.stderr
    rows = {row[0]: row for row in csv.reader(out.open())
            if row and not row[0].startswith("#") and row[0] != "code_postal"}
    assert rows["75007"][3] == "ultra" and rows["75007"][1] == "Paris 7e"
    assert "45000" not in rows and "06230" not in rows
    assert rows["68000"][3] == "high"     # curated Alsace row survived the merge
