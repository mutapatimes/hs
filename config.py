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
UK_PROPERTY_VALUES_FILE = POSTCODES_DIR / "uk_property_values.csv"
US_PROPERTY_VALUES_FILE = POSTCODES_DIR / "us_property_values.csv"
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
TALENT_MGMT_KEYWORDS_FILE = DOMAINS_DIR / "talent_mgmt_keywords.csv"
STYLING_SERVICES_FILE = DOMAINS_DIR / "styling_services.csv"
HOTEL_CHAIN_DOMAINS_FILE = DOMAINS_DIR / "hotel_chain_domains.csv"
CCTLD_COUNTRIES_FILE = DOMAINS_DIR / "cctld_countries.csv"  # email ccTLD -> country (corroboration only)
COUNTRIES_DIR = REFERENCE_DIR / "countries"
GCC_COUNTRIES_FILE = COUNTRIES_DIR / "gcc_countries.csv"
# High-value residential jurisdictions (Bucket 1 of the geography taxonomy — a wealth fact,
# on by default). Formerly TAX_HAVENS_FILE / the "tax_haven" signal; see
# docs/geography-signal-taxonomy.md.
WEALTH_JURISDICTIONS_FILE = COUNTRIES_DIR / "wealth_jurisdictions.csv"
ADDRESSES_DIR = REFERENCE_DIR / "addresses"
PRIME_RESIDENCES_FILE = ADDRESSES_DIR / "prime_residences.csv"
# Wealth-management structures (Bucket 2 — address routed through a trust company / family
# office / registered agent / offshore PO box). Origin-neutral, on by default.
WEALTH_STRUCTURES_FILE = ADDRESSES_DIR / "wealth_structures.csv"
# Named-property words ("The Old Rectory", "Whitfield Manor", "Chalet …") — a street line that is
# a NAMED house instead of a numbered address. On by default (a wealth-address fact).
NAMED_HOUSE_KEYWORDS_FILE = ADDRESSES_DIR / "named_house_keywords.csv"
NAMES_DIR = REFERENCE_DIR / "names"
HONORIFICS_FILE = NAMES_DIR / "honorifics.csv"
RICH_LIST_FILE = NAMES_DIR / "rich_list.csv"
FASHION_STYLISTS_FILE = NAMES_DIR / "fashion_stylists.csv"
FASHION_STYLISTS_DIRECTORY_FILE = NAMES_DIR / "fashion_stylists_directory.csv"
HERITAGE_SURNAMES_FILE = NAMES_DIR / "heritage_surnames.csv"
NOBILIARY_PARTICLES_FILE = NAMES_DIR / "nobiliary_particles.csv"
POST_NOMINALS_FILE = NAMES_DIR / "post_nominals.csv"
PHONE_DIR = REFERENCE_DIR / "phone"
PHONE_CODES_FILE = PHONE_DIR / "hnw_dialing_codes.csv"
# Corroboration-only maps: a phone dialling code / email ccTLD -> the country it belongs to,
# used solely by geo_confirmation to check agreement with a high-value address (never originates
# a score). See docs/geography-signal-taxonomy.md.
DIALING_CODE_COUNTRIES_FILE = PHONE_DIR / "dialing_code_countries.csv"
COMPANIES_DIR = REFERENCE_DIR / "companies"
COMPANY_KEYWORDS_FILE = COMPANIES_DIR / "company_keywords.csv"
UK_COMPANY_CONTROLLERS_FILE = COMPANIES_DIR / "uk_company_controllers.csv"
# Operator-generated real table (from scripts/build_company_controllers.py). GIT-IGNORED, because it
# holds named private individuals. When present it is preferred over the committed inert seed.
UK_COMPANY_CONTROLLERS_LOCAL_FILE = COMPANIES_DIR / "uk_company_controllers.local.csv"
US_INSIDERS_FILE = COMPANIES_DIR / "us_insiders.csv"
# Operator-generated real table (from scripts/build_us_insiders.py). GIT-IGNORED, because it holds
# named private individuals. When present it is preferred over the committed inert seed.
US_INSIDERS_LOCAL_FILE = COMPANIES_DIR / "us_insiders.local.csv"
CHARITIES_DIR = REFERENCE_DIR / "charities"
UK_CHARITY_TRUSTEES_FILE = CHARITIES_DIR / "uk_charity_trustees.csv"
# Operator-generated real table (from scripts/build_charity_trustees.py). GIT-IGNORED, because it
# holds named private individuals. When present it is preferred over the committed inert seed.
UK_CHARITY_TRUSTEES_LOCAL_FILE = CHARITIES_DIR / "uk_charity_trustees.local.csv"
CARDS_DIR = REFERENCE_DIR / "cards"
PREMIUM_BINS_FILE = CARDS_DIR / "premium_bins.csv"
LOCATIONS_DIR = REFERENCE_DIR / "locations"
HNW_LOCATIONS_FILE = LOCATIONS_DIR / "hnw_locations.csv"
HNW_AREAS_FILE = LOCATIONS_DIR / "hnw_areas.csv"
# Origin-adjacent prime districts (Bucket 3 — arguable wealth-geography but the flagged
# population skews to one national origin in a UK book, so GATED off by default). Names matched
# like hnw_areas; postcodes like intl_hnwi_postcodes. See docs/geography-signal-taxonomy.md.
ORIGIN_ADJACENT_DISTRICTS_FILE = LOCATIONS_DIR / "origin_adjacent_districts.csv"
ORIGIN_ADJACENT_POSTCODES_FILE = LOCATIONS_DIR / "origin_adjacent_postcodes.csv"

# Optional MaxMind GeoIP database for IP -> location (not committed; see README).
GEOIP_DIR = ROOT / "geoip"
GEOIP_DB_FILE = GEOIP_DIR / "GeoLite2-City.mmdb"

# Scoring source package and tests.
SCORING_DIR = ROOT / "scoring"
TESTS_DIR = ROOT / "tests"

# Generated output (contains customer PII -> git-ignored, stays local).
OUTPUT_DIR = ROOT / "output"
EXPORT_FILE = OUTPUT_DIR / "hidden_vics.xlsx"
