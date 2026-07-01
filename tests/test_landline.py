"""UK landline signal — line-type tell (01/02), not a mobile; origin-neutral, on by default."""
import pandas as pd

from scoring.combine import ORIGIN_PROXY_SIGNALS, active_signals
from scoring.signals.landline import FLAG_COL, flag_landline


def test_landline_vs_mobile_vs_foreign():
    df = pd.DataFrame({"PHONE": [
        "020 7946 0018",       # London landline   -> yes
        "+44 20 7946 0018",    # same, intl form   -> yes
        "01865 240000",        # Oxford landline   -> yes
        "07700 900123",        # UK mobile         -> no
        "+1 212 555 1212",     # US number         -> no
        "",                    # blank             -> no
    ]})
    out = flag_landline(df)
    assert out[FLAG_COL].tolist() == [True, True, True, False, False, False]


def test_dormant_without_phone_column():
    out = flag_landline(pd.DataFrame({"x": [1]}))
    assert out[FLAG_COL].tolist() == [False]


def test_on_by_default_not_origin_proxy():
    assert "landline" not in ORIGIN_PROXY_SIGNALS
    assert "landline" in {s[0] for s in active_signals()}
