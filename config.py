"""Central configuration: filesystem paths used across the project.

Keeping paths in one place means the scoring code, tests, and the main
script all agree on where data and reference lists live.
"""
from pathlib import Path

# Project root = the folder this file sits in.
ROOT = Path(__file__).resolve().parent

# Local-only customer data (git-ignored — never committed).
DATA_DIR = ROOT / "sample_data"
DATA_FILE = DATA_DIR / "synthetic_100k.xlsx"
DATA_SHEET = "Export"

# Curated reference lists (tracked in git).
REFERENCE_DIR = ROOT / "reference_data"
POSTCODES_DIR = REFERENCE_DIR / "postcodes"
HNWI_POSTCODES_FILE = POSTCODES_DIR / "hnwi_postcodes.csv"
US_HNWI_ZIPS_FILE = POSTCODES_DIR / "us_hnwi_zips.csv"
INTL_HNWI_POSTCODES_FILE = POSTCODES_DIR / "intl_hnwi_postcodes.csv"
VENUES_DIR = REFERENCE_DIR / "venues"
SIGNAL_VENUES_FILE = VENUES_DIR / "signal_venues.csv"
WEALTH_OFFICES_FILE = VENUES_DIR / "wealth_offices.csv"
DOMAINS_DIR = REFERENCE_DIR / "domains"
WEALTH_DOMAINS_FILE = DOMAINS_DIR / "wealth_employer_domains.csv"
PREMIUM_EMAIL_FILE = DOMAINS_DIR / "premium_email_domains.csv"
FREE_EMAIL_FILE = DOMAINS_DIR / "free_email_providers.csv"
ELITE_ALUMNI_FILE = DOMAINS_DIR / "elite_alumni_domains.csv"
HOTEL_DOMAINS_FILE = DOMAINS_DIR / "hotel_domains.csv"
HIGH_EARNING_KEYWORDS_FILE = DOMAINS_DIR / "high_earning_keywords.csv"
ELITE_FINANCE_KEYWORDS_FILE = DOMAINS_DIR / "elite_finance_keywords.csv"
STYLING_SERVICES_FILE = DOMAINS_DIR / "styling_services.csv"
HOTEL_CHAIN_DOMAINS_FILE = DOMAINS_DIR / "hotel_chain_domains.csv"
COUNTRIES_DIR = REFERENCE_DIR / "countries"
GCC_COUNTRIES_FILE = COUNTRIES_DIR / "gcc_countries.csv"
TAX_HAVENS_FILE = COUNTRIES_DIR / "tax_havens.csv"
ADDRESSES_DIR = REFERENCE_DIR / "addresses"
PRIME_RESIDENCES_FILE = ADDRESSES_DIR / "prime_residences.csv"
NAMES_DIR = REFERENCE_DIR / "names"
HONORIFICS_FILE = NAMES_DIR / "honorifics.csv"
RICH_LIST_FILE = NAMES_DIR / "rich_list.csv"
HERITAGE_SURNAMES_FILE = NAMES_DIR / "heritage_surnames.csv"
NOBILIARY_PARTICLES_FILE = NAMES_DIR / "nobiliary_particles.csv"
POST_NOMINALS_FILE = NAMES_DIR / "post_nominals.csv"
PHONE_DIR = REFERENCE_DIR / "phone"
PHONE_CODES_FILE = PHONE_DIR / "hnw_dialing_codes.csv"
COMPANIES_DIR = REFERENCE_DIR / "companies"
COMPANY_KEYWORDS_FILE = COMPANIES_DIR / "company_keywords.csv"
CARDS_DIR = REFERENCE_DIR / "cards"
PREMIUM_BINS_FILE = CARDS_DIR / "premium_bins.csv"
LOCATIONS_DIR = REFERENCE_DIR / "locations"
HNW_LOCATIONS_FILE = LOCATIONS_DIR / "hnw_locations.csv"
HNW_AREAS_FILE = LOCATIONS_DIR / "hnw_areas.csv"

# Optional MaxMind GeoIP database for IP -> location (not committed; see README).
GEOIP_DIR = ROOT / "geoip"
GEOIP_DB_FILE = GEOIP_DIR / "GeoLite2-City.mmdb"

# Scoring source package and tests.
SCORING_DIR = ROOT / "scoring"
TESTS_DIR = ROOT / "tests"

# Generated output (contains customer PII -> git-ignored, stays local).
OUTPUT_DIR = ROOT / "output"
EXPORT_FILE = OUTPUT_DIR / "hidden_vics.xlsx"
