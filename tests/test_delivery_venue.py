"""Tests for the delivery-address venue signal.

Addresses are taken from the messiest real shipping addresses in
sample_data/sample.xlsx. Venue (commercial) addresses are kept verbatim;
house numbers on RESIDENTIAL near-misses are genericised, but the
venue-colliding text (Connaught, Bulgaria, Ritz, Four Seasons, etc.) is real —
that's the part the matcher has to get right.
"""
import pandas as pd

from scoring.signals.delivery_venue import (
    MATCH_COL,
    TYPE_COL,
    VENUE_COL,
    flag_delivery_venue,
    load_venues,
    match_address,
)

# (raw address as it appears across the shipping lines, expected venue, expected type)
SHOULD_MATCH = [
    ("The Lanesborough Hotel | Hyde Park Corner | London",
     "The Lanesborough", "luxury_hotel"),
    ("BERKLEY HOTEL - ROOM 304 | WILTON STREET",                 # typo + room + caps
     "The Berkeley", "luxury_hotel"),
    ("BULGARI APARTMENT | BULGARI HOTEL | 171 Knightsbridge",
     "Bulgari Hotel London", "luxury_hotel"),
    ("Old Barrack Yard | The Emory Hotel | London | United Kingdom",
     "The Emory", "luxury_hotel"),
    ("Royal Garden Hotel | 2-24 Kensington High st.",
     "Royal Garden Hotel", "luxury_hotel"),
    ("Reading Fc Training Ground | Bearwood Park | Sindlesham | United Kingdom",
     "Reading FC Training Ground", "football_training_ground"),
    ("c/o The Concierge | Claridge's | Brook Street | London",   # c/o is stripped
     "Claridge's", "luxury_hotel"),
    # US private-aviation FBOs
    ("Signature Flight Support | Teterboro Airport | NJ | United States",
     "Teterboro Airport", "private_jet_fbo"),
    ("Fort Lauderdale Executive Airport | 1625 NW 51st Pl | FL",
     "Fort Lauderdale Executive Airport", "private_jet_fbo"),
    ("Atlantic Aviation | Opa Locka Executive Airport | Miami | United States",
     "Miami-Opa Locka Executive Airport", "private_jet_fbo"),
    ("Henderson Executive Airport | 3500 Executive Terminal Dr | Las Vegas",
     "Henderson Executive Airport", "private_jet_fbo"),
    # Sports facilities (football / NBA / F1)
    ("Carrington Training Complex | Birch Road | Manchester | M31 4BH",
     "Manchester United (Carrington)", "football_training_ground"),
    ("HSS Training Center | 168 39th Street | Brooklyn | NY",
     "Brooklyn Nets (HSS Training Center)", "basketball_training_facility"),
    ("Silverstone Circuit | Dadford Road | Towcester | NN12 8TN",
     "Silverstone Circuit", "motorsport_circuit"),
]

# Near-misses: contain a venue word but are NOT the venue. Must NOT match.
SHOULD_NOT_MATCH = [
    "12 CONNAUGHT DRIVE | London | United Kingdom",             # Connaught Drive != The Connaught
    "15A Connaught House | Clifton Gardens | London",           # Connaught House
    "via CURTINS | 11 ST MORITZ",                               # Moritz != Ritz
    "#101 Sangji Ritzville | 116-10 Chungdam-dong | seoul | South Korea",  # Ritzville
    "3 Coleman St Peninsula Shopping Centre | #02-35 | Singapore",         # Peninsula Shopping Centre
    "10 Cuscaden Walk | Unit 06-04 Four Seasons Park | Singapore",         # Four Seasons Park (residential)
    "Rm611 6/F Block A mandarin | Plaza 14 Science Museum KLN",            # Mandarin Plaza
    "36 Knyaginya Maria Luiza blv. | Plovdiv | Bulgaria",                  # Bulgaria != Bulgari
    "601 Lairport St. | El Segundo | United States",                       # Lairport != airport
    "52 Whitehill Avenue | Luton | United Kingdom",                        # Luton town != Luton Airport
    "c/o Sarah Heard | KARORI 1 4TH FLOOR | Athens | Greece",             # c/o, no venue
    "742 Palm Beach Gardens | Palm Beach | FL | United States",           # Palm Beach (residential) != PBI airport
    "88 Henderson Road | Henderson | NV | United States",                 # Henderson city != Henderson Executive
    "12 Westchester Avenue | White Plains | NY | United States",          # Westchester (county/street) != the Airport
    "300 Opa Locka Blvd | Opa-locka | FL | United States",                # Opa-locka city != Opa Locka Executive
    "10 Cobham High Street | Cobham | Surrey | United Kingdom",           # Cobham town != Cobham Training
    "5 Silverstone Close | Towcester | United Kingdom",                   # Silverstone village != Silverstone Circuit
    "200 Chase Road | Southgate | London | United Kingdom",              # Chase Road != Chase Center
    "14 Monza Avenue | London | United Kingdom",                          # Monza street != Monza Circuit
]


def test_messy_real_addresses_match_correct_venue():
    venues = load_venues()
    for address, exp_venue, exp_type in SHOULD_MATCH:
        matched, venue, signal_type = match_address(address, venues)
        assert matched, f"expected a match for: {address}"
        assert venue == exp_venue, f"{address} -> {venue} (wanted {exp_venue})"
        assert signal_type == exp_type


def test_near_misses_do_not_match():
    venues = load_venues()
    for address in SHOULD_NOT_MATCH:
        matched, venue, _ = match_address(address, venues)
        assert not matched, f"FALSE POSITIVE on near-miss: {address} -> {venue}"


def test_dataframe_helper_splits_across_lines():
    """The venue can sit on any shipping line; the helper joins them."""
    venues = load_venues()
    df = pd.DataFrame(
        {
            "LATEST_SHIPPING_ADDRESS1": ["Old Barrack Yard", "12 Connaught Drive"],
            "LATEST_SHIPPING_ADDRESS2": ["The Emory Hotel", None],
            "LATEST_SHIPPING_ADDRESS3": ["London", "London"],
            "LATEST_SHIPPING_ADDRESS4": ["United Kingdom", "United Kingdom"],
        }
    )
    out = flag_delivery_venue(df, venues)
    assert out[MATCH_COL].tolist() == [True, False]
    assert out.loc[0, VENUE_COL] == "The Emory"
    assert out.loc[0, TYPE_COL] == "luxury_hotel"
    assert out.loc[1, VENUE_COL] is None


def test_facility_postcode_in_zip_column_matches():
    """A delivery whose only tell is the facility postcode (in the ZIP column)."""
    venues = load_venues()
    df = pd.DataFrame(
        {
            "LATEST_SHIPPING_ADDRESS1": ["Birch Road"],
            "LATEST_SHIPPING_ADDRESS3": ["Carrington"],   # town name alone won't match
            "LATEST_SHIPPING_ADDRESS4": ["United Kingdom"],
            "LATEST_SHIPPING_ZIP": ["M31 4BH"],            # ...but the postcode does
        }
    )
    out = flag_delivery_venue(df, venues)
    assert out[MATCH_COL].tolist() == [True]
    assert out.loc[0, VENUE_COL] == "Manchester United (Carrington)"
    assert out.loc[0, TYPE_COL] == "football_training_ground"


def test_blank_address_not_flagged():
    venues = load_venues()
    assert match_address(None, venues) == (False, None, None)
    assert match_address("", venues) == (False, None, None)
    assert match_address("   |  | ", venues) == (False, None, None)
