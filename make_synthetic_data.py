"""Generate a 100k-record synthetic Shopify dataset (with payment info) whose
hidden-VIC grade mix is engineered to a target distribution.

What it produces
----------------
1. output/synthetic_shopify_orders.ndjson — native Shopify *order* objects (one
   JSON per line) including billing/shipping addresses, browser_ip, currency and
   a transactions list carrying payment_details.credit_card_bin / company.
2. sample_data/synthetic_100k.xlsx (sheet "Export") — the same customers flattened
   to the engine schema (via the REAL scoring.shopify adapter), ready to drop in
   as config.DATA_FILE and run `python build_mvp.py`.

The signals fired per customer are drawn from the live reference_data CSVs and
composed across independent "channels" (email / name / address-geo / company /
phone). We mirror combine.py's exact weight + group-decay maths to pick recipes
that land each customer in the intended grade band, then VERIFY by scoring the
generated data through the real engine and printing the achieved distribution.

    python make_synthetic_data.py            # 100k, seed 42
    python make_synthetic_data.py 20000 7    # N, seed

Grades come from scoring.grading: A* (raw>=5.0), A (>=3.5), B (>=1.75), C (>0).
A customer with NO signals never surfaces as a hidden VIC (count==0).
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config import (
    ELITE_ALUMNI_FILE, ELITE_FINANCE_KEYWORDS_FILE, HERITAGE_SURNAMES_FILE,
    HIGH_EARNING_KEYWORDS_FILE, HNWI_POSTCODES_FILE, HNW_AREAS_FILE,
    HONORIFICS_FILE, HOTEL_DOMAINS_FILE, INTL_HNWI_POSTCODES_FILE,
    NOBILIARY_PARTICLES_FILE, OUTPUT_DIR, POST_NOMINALS_FILE, PHONE_CODES_FILE,
    PREMIUM_BINS_FILE, PREMIUM_EMAIL_FILE, PRIME_RESIDENCES_FILE, RICH_LIST_FILE,
    ROOT, SIGNAL_VENUES_FILE, STYLING_SERVICES_FILE, US_HNWI_ZIPS_FILE,
    WEALTH_DOMAINS_FILE, WEALTH_OFFICES_FILE,
)
from config import COMPANY_KEYWORDS_FILE, GCC_COUNTRIES_FILE, TAX_HAVENS_FILE
from scoring.combine import (
    DELIVERY_TYPE_WEIGHTS, DOMAIN_KEYWORD_TYPE_WEIGHTS, GROUP_DECAY,
    HIDDEN_COL, SCORE_COL, SIGNAL_GROUP, SIGNAL_WEIGHTS, SUPPORTING_SIGNALS,
    active_signals, score_customers,
)
from scoring.grading import GRADE_LABEL, tier_for, to_score100
from scoring.shopify import orders_to_customers

# ── reference loaders ────────────────────────────────────────────────────────
def _rows(path: Path, skip_header=True) -> list[list[str]]:
    out = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.reader(fh)):
            if not row or row[0].strip().startswith("#"):
                continue
            if skip_header and i == 0:
                continue
            out.append([c.strip() for c in row])
    return out


def _col0(path) -> list[str]:
    return [r[0] for r in _rows(path) if r and r[0]]


REF = {
    "wealth_domains": _col0(WEALTH_DOMAINS_FILE),
    "premium_email": _col0(PREMIUM_EMAIL_FILE),
    "alumni": _col0(ELITE_ALUMNI_FILE),
    "hotel": _col0(HOTEL_DOMAINS_FILE),
    "styling": _col0(STYLING_SERVICES_FILE),
    "kw_elite": [k for k in _col0(ELITE_FINANCE_KEYWORDS_FILE) if len(k) >= 6],
    "kw_general": [k for k in _col0(HIGH_EARNING_KEYWORDS_FILE) if len(k) >= 6],
    "hnwi_pc": _col0(HNWI_POSTCODES_FILE),
    "us_zip": _col0(US_HNWI_ZIPS_FILE),
    "honorifics": [r[0] for r in _rows(HONORIFICS_FILE)
                   if r[0] in {"SIR", "DAME", "LADY", "BARONESS", "VISCOUNT",
                               "COUNTESS", "DUCHESS", "MARQUESS", "HRH", "HSH"}],
    "post_nominals": _col0(POST_NOMINALS_FILE),
    "heritage": _col0(HERITAGE_SURNAMES_FILE),
    "rich": [r[0] for r in _rows(RICH_LIST_FILE) if r and r[0]],
    "particles_single": [r[0] for r in _rows(NOBILIARY_PARTICLES_FILE)
                         if r and r[0] and " " not in r[0]],
    "premium_bins": [(r[0], r[2] if len(r) > 2 else "") for r in _rows(PREMIUM_BINS_FILE)],
    "phone_codes": [r[0] for r in _rows(PHONE_CODES_FILE) if r and r[0].startswith("+")],
}
# intl postcodes: (country, prefix)
REF["intl_pc"] = [(r[0], r[1]) for r in _rows(INTL_HNWI_POSTCODES_FILE) if len(r) > 1 and r[1]]
# venues: (alias, signal_type)
_sv = [(r[2].split(";")[0] if len(r) > 2 and r[2] else r[0], r[1]) for r in _rows(SIGNAL_VENUES_FILE) if len(r) > 1]
REF["venue_fbo"] = [a for a, t in _sv if t in DELIVERY_TYPE_WEIGHTS]
REF["venue_other"] = [a for a, t in _sv if t not in DELIVERY_TYPE_WEIGHTS]
# wealth_office is CITY-GUARDED: keep (building-alias, city) so we set both.
REF["wealth_office"] = [
    (r[3].split(";")[0], r[2].split(";")[0])
    for r in _rows(WEALTH_OFFICES_FILE) if len(r) > 3 and r[3] and r[2]
]
REF["prime"] = [(r[2].split(";")[0] if len(r) > 2 and r[2] else r[0]) for r in _rows(PRIME_RESIDENCES_FILE)]
# hnw areas: (alias, country signal_type)
REF["hnw_area"] = [(r[2].split(";")[0] if len(r) > 2 and r[2] else r[0], r[1]) for r in _rows(HNW_AREAS_FILE) if len(r) > 1]
REF["gcc"] = [r[0] for r in _rows(GCC_COUNTRIES_FILE) if r and r[0]]
REF["tax_haven"] = [r[0] for r in _rows(TAX_HAVENS_FILE) if r and r[0]]
REF["company_kw"] = [r[0] for r in _rows(COMPANY_KEYWORDS_FILE) if r and r[0]]

# Deliberately multinational name pools (English is a minority) so the customer
# base looks like a global luxury clientele, not a UK-only one.
FIRST = (
    # English / Western European
    "James Olivia William Sophia Henry Amelia Edward Charlotte Arthur Florence "
    # French
    "Camille Étienne Léa Mathieu Margaux Thibault Adèle Florian "
    # Italian
    "Lorenzo Giulia Matteo Francesca Alessandro Chiara Riccardo Bianca "
    # Spanish / Portuguese / Latin American
    "Mateo Valentina Santiago Lucía Diego Camila Rafael Beatriz João Sofía "
    # German / Nordic
    "Lukas Annika Maximilian Greta Henrik Ingrid Soren Freya "
    # Arabic / Middle Eastern
    "Rashid Aisha Hassan Leila Omar Fatima Khalid Noor Yusuf Zara "
    # Persian / Turkish
    "Darius Roxana Cyrus Yasmin Emre Defne Kerem Elif "
    # South Asian
    "Arjun Priya Rohan Ananya Vikram Meera Kabir Diya Aditya Saanvi "
    # East Asian (Chinese / Japanese / Korean)
    "Wei Mei Hao Lin Jing Yuki Kenji Haruto Sakura Ren Minjun Seoyeon Jiho Haeun "
    # Southeast Asian
    "Nguyen Linh Arif Putri Chayanne Achara "
    # Russian / Slavic / Greek
    "Dmitri Anya Nikolai Katya Aleksandr Sofiya Stavros Eleni "
    # African
    "Kwame Amara Chidi Zola Tendai Folasade Kofi Nia"
).split()
LAST = (
    "Pemberton Whitmore Sinclair Fairfax Caldwell Thornton "          # English
    "Moreau Lefèvre Girard Lemaire Fontaine Beaulieu "               # French
    "Conti Greco Ricci Marchetti Lombardi Bellini "                  # Italian
    "García Romero Navarro Iglesias Vargas Cordeiro Pereira Fonseca "  # Spanish/Portuguese
    "Schneider Hoffmann Vogel Lindqvist Bergström Nilsson "          # German/Nordic
    "Al-Farsi Haddad Nasser Khoury Mansour Rahimi Shirazi "          # Arabic/Persian
    "Yılmaz Demir Kaya Aydın "                                       # Turkish
    "Sharma Iyer Kapoor Reddy Banerjee Chowdhury Nair "             # South Asian
    "Chen Wang Zhao Tanaka Watanabe Nakamura Kim Park Choi Jeong "   # East Asian
    "Tran Pham Wijaya Suharto Srisai "                               # Southeast Asian
    "Volkov Petrov Sokolov Novak Papadopoulos Nikolaidis "          # Slavic/Greek
    "Okafor Mensah Dlamini Adeyemi Mwangi"                          # African
).split()
PLACES = ("Hartwell Ashby Croft Marsh Vale Bourne Holt Ridley Quincey Mercer "
          "Aldgate Meridian Sterling Bramley Avelon Cassel Drummond").split()
CITY = ("Manchester Bristol Leeds Sheffield Nottingham Cardiff Newcastle "
        "Coventry Hull Derby Plymouth Stoke").split()
SAFE_OUTWARD = ("LS M B NG S CF NE HD BD PL DE HU CV ST").split()
# Generic hotel role mailboxes (never a personal name) for concierge buying.
HOTEL_ROLE_LOCALS = ("concierge reception frontdesk front.desk frontoffice bookings "
                     "reservations guestservices guest.services guestrelations butler "
                     "lifestyle vip.desk").split()

# Scrub random name pools so an unsignalled customer can never accidentally fire a
# name signal (heritage / rich-list). measure-and-select handles the rest.
_avoid_last = ({re.sub(r"[^A-Z]", "", x.upper()) for x in REF["heritage"]}
               | {re.sub(r"[^A-Z]", "", w.upper()) for n in REF["rich"] for w in n.split()})
LAST = [l for l in LAST if l.upper() not in _avoid_last]

# Keep each geo fragment to exactly ONE geo signal: drop HNW areas / intl postcodes
# whose country is itself a tax haven or GCC state (which would co-fire a 2nd geo).
_drop_country = ({c.lower() for c in REF["tax_haven"]} | {c.lower() for c in REF["gcc"]}
                 | {"monaco", "uae", "u a e"})
REF["hnw_area"] = [(a, c) for a, c in REF["hnw_area"]
                   if c and c.lower() not in _drop_country]
REF["intl_pc"] = [(c, p) for c, p in REF["intl_pc"] if c.lower() not in _drop_country]


def rint(rng, lo, hi):
    return rng.randint(lo, hi)


def safe_zip(rng):
    return f"{rng.choice(SAFE_OUTWARD)}{rint(rng,1,30)} {rint(rng,1,9)}{rng.choice('ABDEFGHJ')}{rng.choice('ABDEFGHJ')}"


def complete_postcode(prefix, rng):
    """Turn an HNWI reference prefix (district/sector/unit) into a full postcode
    that the prefix actually matches — district 'SW10' -> 'SW10 9AB', unit kept."""
    p = re.sub(r"\s+", " ", str(prefix).strip().upper())
    out, _, inward = p.partition(" ")
    while len(inward) < 3:
        inward += rng.choice("0123456789") if not inward else rng.choice("ABDEFGHJLNPRSTUWXYZ")
    return f"{out} {inward[:3]}"


# ── per-signal fragments: mutate the identity record `r`, return effective weight ─
def f_email(r, rng, kind):
    user = (r["_first"] + "." + r["_last"]).lower()
    if kind == "work_email":
        r["EMAIL_ADDR"] = f"{user}@{rng.choice(REF['wealth_domains'])}"
    elif kind == "premium_email":
        r["EMAIL_ADDR"] = f"{user}@{rng.choice(REF['premium_email'])}"
    elif kind == "elite_alumni":
        r["EMAIL_ADDR"] = f"{user}@{rng.choice(REF['alumni'])}"
    elif kind == "hotel_concierge":
        # A hotel buys for guests from a generic ROLE mailbox, never a personal
        # name. (These role locals also legitimately co-fire assistant_order.)
        r["EMAIL_ADDR"] = f"{rng.choice(HOTEL_ROLE_LOCALS)}@{rng.choice(REF['hotel'])}".lower()
    elif kind == "styling_service":
        r["EMAIL_ADDR"] = f"buyer@{rng.choice(REF['styling'])}"
    elif kind == "domain_keyword_elite":
        r["EMAIL_ADDR"] = f"{user}@{rng.choice(PLACES).lower()}{rng.choice(REF['kw_elite'])}.com"
    elif kind == "domain_keyword_general":
        r["EMAIL_ADDR"] = f"{user}@{rng.choice(PLACES).lower()}{rng.choice(REF['kw_general'])}.com"
    elif kind == "custom_email":
        r["EMAIL_ADDR"] = f"{user}@{rng.choice(PLACES).lower()}{rng.choice(PLACES).lower()}.com"


def f_geo(r, rng, kind):
    if kind == "hnwi_postcode":
        r["zip"], r["country"] = complete_postcode(rng.choice(REF["hnwi_pc"]), rng), "United Kingdom"
    elif kind == "us_hnwi_zip":
        r["zip"], r["country"], r["city"] = rng.choice(REF["us_zip"]), "United States", "New York"
    elif kind == "intl_postcode":
        c, p = rng.choice(REF["intl_pc"])
        r["zip"], r["country"] = p, c
    elif kind == "hnw_area":
        alias, country = rng.choice(REF["hnw_area"])
        r["city"] = alias.title()
        r["country"] = country if country and country.lower() not in {"uk", "uae", "usa"} else \
            {"uk": "United Kingdom", "uae": "United Arab Emirates", "usa": "United States"}.get(country.lower(), "")
    elif kind == "gcc_billing":
        r["country"] = rng.choice(REF["gcc"])
    elif kind == "tax_haven":
        r["country"] = rng.choice(REF["tax_haven"])


def f_addr1(r, rng, kind):
    if kind == "delivery_fbo":
        r["address1"] = rng.choice(REF["venue_fbo"])
    elif kind == "delivery_other":
        r["address1"] = rng.choice(REF["venue_other"])
    elif kind == "wealth_office":
        alias, city = rng.choice(REF["wealth_office"])
        r["address1"], r["city"] = alias, city.title()
    elif kind == "prime_residence":
        r["address1"] = rng.choice(REF["prime"])


def build_name(r, rng, surname_kind, honorific, post_nominal):
    first = rng.choice(FIRST)
    if surname_kind == "rich_list":
        name = rng.choice(REF["rich"])
        first, last = name.split()[0], name.split()[-1]
        core = name
    else:
        last = rng.choice(LAST)
        if surname_kind == "heritage":
            last = rng.choice(REF["heritage"])
        elif surname_kind == "hyphen":
            second = rng.choice([x for x in LAST if x != last])
            last = f"{last}-{second}"
        core = f"{first} {last}"
        if surname_kind == "nobiliary":
            core = f"{first} {rng.choice(REF['particles_single'])} {last}"
    if honorific:
        core = f"{rng.choice(REF['honorifics']).title()} {core}"
    if post_nominal:
        core = f"{core} {rng.choice(REF['post_nominals'])}"
    r["_first"], r["_last"] = first, last.replace("-", "")
    r["Name"] = core


# ── recipe assembly: pick a combo and return (fired-weights dict, channel choices) ─
EMAIL_OPTS = {
    "work_email": ("work_email", SIGNAL_WEIGHTS["work_email"]),
    "premium_email": ("premium_email", SIGNAL_WEIGHTS["premium_email"]),
    "elite_alumni": ("elite_alumni", SIGNAL_WEIGHTS["elite_alumni"]),
    "hotel_concierge": ("hotel_concierge", SIGNAL_WEIGHTS["hotel_concierge"]),
    "styling_service": ("styling_service", SIGNAL_WEIGHTS["styling_service"]),
    "domain_keyword_elite": None,   # special: fires domain_keyword(elite)+custom_email
    "domain_keyword_general": None,
    "custom_email": ("custom_email", SIGNAL_WEIGHTS["custom_email"]),
}
GEO_OPTS = ["hnwi_postcode", "us_hnwi_zip", "intl_postcode", "hnw_area", "gcc_billing", "tax_haven"]
ADDR1_OPTS = ["delivery_fbo", "delivery_other", "wealth_office", "prime_residence"]


def sample_recipe(rng):
    """Randomly choose channel options -> dict {signal_key: effective_weight}."""
    fired: dict[str, float] = {}
    choices: dict = {}

    # EMAIL channel (<=1 domain type)
    if rng.random() < 0.7:
        ek = rng.choice(list(EMAIL_OPTS))
        choices["email"] = ek
        if ek == "domain_keyword_elite":
            fired["domain_keyword"] = DOMAIN_KEYWORD_TYPE_WEIGHTS["elite"]
            fired["custom_email"] = SIGNAL_WEIGHTS["custom_email"]
        elif ek == "domain_keyword_general":
            fired["domain_keyword"] = DOMAIN_KEYWORD_TYPE_WEIGHTS["general"]
            fired["custom_email"] = SIGNAL_WEIGHTS["custom_email"]
        else:
            key, w = EMAIL_OPTS[ek]
            fired[key] = w

    # NAME channel — name/surname signals are kept RARE (dynasty surnames,
    # titles and honours are distinctive, not common). Budgeted so the whole
    # 100k set carries only ~200 name-derived triggers across all six signals.
    surname_kind = rng.choices(
        ["plain", "heritage", "rich_list", "hyphen", "nobiliary"],
        weights=[988, 3, 2, 4, 3])[0]
    honorific = rng.random() < 0.0025
    post_nominal = rng.random() < 0.0025
    choices["surname"], choices["honorific"], choices["post_nominal"] = surname_kind, honorific, post_nominal
    if surname_kind == "heritage":
        fired["heritage_surname"] = SIGNAL_WEIGHTS["heritage_surname"]
    if surname_kind == "rich_list":
        fired["rich_list"] = SIGNAL_WEIGHTS["rich_list"]
    if surname_kind == "hyphen":
        fired["name_structure"] = SIGNAL_WEIGHTS["name_structure"]
    if surname_kind == "nobiliary":
        fired["nobiliary_particle"] = SIGNAL_WEIGHTS["nobiliary_particle"]
    if honorific:
        fired["honorific"] = SIGNAL_WEIGHTS["honorific"]
    if post_nominal:
        fired["post_nominal"] = SIGNAL_WEIGHTS["post_nominal"]

    # ADDRESS / GEO channel
    geo = rng.choice(GEO_OPTS) if rng.random() < 0.5 else None
    addr1 = rng.choice(ADDR1_OPTS) if rng.random() < 0.4 else None
    if addr1 == "prime_residence" and geo in ("us_hnwi_zip", "intl_postcode", "gcc_billing"):
        addr1 = "wealth_office"  # keep country coherent for the geo guard
    choices["geo"], choices["addr1"] = geo, addr1
    if geo:
        fired[geo] = SIGNAL_WEIGHTS[geo]
    if addr1 == "delivery_fbo":
        fired["delivery_venue"] = DELIVERY_TYPE_WEIGHTS["private_jet_fbo"]
    elif addr1 == "delivery_other":
        fired["delivery_venue"] = SIGNAL_WEIGHTS["delivery_venue"]
    elif addr1 == "wealth_office":
        fired["wealth_office"] = SIGNAL_WEIGHTS["wealth_office"]
    elif addr1 == "prime_residence":
        fired["prime_residence"] = SIGNAL_WEIGHTS["prime_residence"]

    # COMPANY channel
    if rng.random() < 0.25:
        fired["company_keyword"] = SIGNAL_WEIGHTS["company_keyword"]
        choices["company"] = True

    # PHONE channel (geo group)
    if rng.random() < 0.2:
        fired["phone_country"] = SIGNAL_WEIGHTS["phone_country"]
        choices["phone"] = True

    # ASSISTANT-ORDER channel (supporting; c/o address marker)
    if rng.random() < 0.08:
        fired["assistant_order"] = SIGNAL_WEIGHTS["assistant_order"]
        choices["assistant"] = True

    return fired, choices


def predict_raw(fired: dict[str, float]) -> float:
    """Mirror combine.score_customers: supporting gate + per-group decay."""
    core = any(k not in SUPPORTING_SIGNALS for k in fired)
    eff = {k: w for k, w in fired.items() if core or k not in SUPPORTING_SIGNALS}
    groups: dict[str, list[float]] = {}
    for k, w in eff.items():
        groups.setdefault(SIGNAL_GROUP.get(k, k), []).append(float(w))
    raw = 0.0
    for ws in groups.values():
        for rank, w in enumerate(sorted(ws, reverse=True)):
            raw += w * (GROUP_DECAY ** rank)
    return round(raw, 2)


def grade_of(raw: float) -> str:
    return tier_for(to_score100(raw))


BANDS = {"A1": (5.0, 99), "A": (3.5, 5.0), "B": (1.75, 3.5), "C": (0.01, 1.75)}


def recipe_for_grade(rng, target: str):
    """Rejection-sample a recipe whose predicted grade == target."""
    lo, hi = BANDS[target]
    for _ in range(400):
        fired, choices = sample_recipe(rng)
        raw = predict_raw(fired)
        if lo <= raw < hi and grade_of(raw) == target:
            return fired, choices
    return fired, choices  # best effort


# ── record + order emission ──────────────────────────────────────────────────
PREMIUM_BRANDS = ["American Express", "Diners Club"]
COMMON_BRANDS = ["Visa", "Mastercard", "Visa", "Mastercard", "Maestro"]


def make_identity(rng, idx, target_grade):
    r = {"_id": idx, "address1": f"{rint(rng,1,200)} {rng.choice(PLACES)} {rng.choice(['Road','Street','Gardens','Square','Mews'])}",
         "address2": "", "city": rng.choice(CITY), "country": "United Kingdom",
         "zip": safe_zip(rng), "company": "", "EMAIL_ADDR": "",
         "PHONE": f"+44 7{rint(rng,100,999)} {rint(rng,100000,999999)}"}

    if target_grade is None:
        first, last = rng.choice(FIRST), rng.choice(LAST)
        r["_first"], r["_last"], r["Name"] = first, last, f"{first} {last}"
        r["EMAIL_ADDR"] = f"{first}.{last}{idx}@gmail.com".lower()
        choices = {}
    else:
        fired, choices = recipe_for_grade(rng, target_grade)
        build_name(r, rng, choices.get("surname", "plain"),
                   choices.get("honorific", False), choices.get("post_nominal", False))
        ek = choices.get("email")
        if ek:
            f_email(r, rng, ek)
        else:
            r["EMAIL_ADDR"] = f"{r['_first']}.{r['_last']}{idx}@gmail.com".lower()
        if choices.get("geo"):
            f_geo(r, rng, choices["geo"])
        if choices.get("addr1"):
            f_addr1(r, rng, choices["addr1"])
        if choices.get("company"):
            r["company"] = f"{rng.choice(PLACES)} {rng.choice(REF['company_kw']).title()}"
        if choices.get("phone"):
            r["PHONE"] = f"{rng.choice(REF['phone_codes'])} {rint(rng,100000,9999999)}"
        if choices.get("assistant"):
            r["address2"] = f"c/o {r['Name']}"

    # spend: graded must be < VIC threshold (5k) to surface; non-signal spread wide
    if target_grade is None:
        r["_spend"] = rng.choice([rint(rng, 0, 4000), rint(rng, 0, 4000), rint(rng, 5000, 80000)])
    else:
        r["_spend"] = rint(rng, 150, 4800)
    r["_orders"] = rng.choices([1, 2, 3], weights=[60, 28, 12])[0]
    r["_last_shopped"] = (_T0 + timedelta(days=rint(rng, 0, 720))).strftime("%Y-%m-%d")

    # payment: premium card skewed to higher grades (parked in scoring, included for realism)
    prem = {"A1": 0.85, "A": 0.6, "B": 0.35, "C": 0.2, None: 0.05}[target_grade]
    if rng.random() < prem:
        r["bin"], _tier = rng.choice(REF["premium_bins"])
        r["card_company"] = rng.choice(PREMIUM_BRANDS)
    else:
        r["bin"] = str(rint(rng, 400000, 559999))
        r["card_company"] = rng.choice(COMMON_BRANDS)
    r["currency"] = "GBP"
    r["target_grade"] = target_grade
    return r


_T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)


def identity_to_row(r):
    """Map an identity dict to the engine's per-customer column schema."""
    return {
        "CUST_ID": r["_id"], "Name": r["Name"], "EMAIL_ADDR": r["EMAIL_ADDR"],
        "PHONE": r["PHONE"], "COMPANY_NAME": r["company"] or None,
        "LATEST_BILLING_ADDRESS1": r["address1"], "LATEST_BILLING_ADDRESS2": r["address2"] or None,
        "LATEST_BILLING_ADDRESS3": r["city"], "LATEST_BILLING_ADDRESS4": r["country"] or None,
        "LATEST_BILLING_ZIP": r["zip"],
        "LATEST_SHIPPING_ADDRESS1": r["address1"], "LATEST_SHIPPING_ADDRESS2": r["address2"] or None,
        "LATEST_SHIPPING_ADDRESS3": r["city"], "LATEST_SHIPPING_ADDRESS4": r["country"] or None,
        "LATEST_SHIPPING_ZIP": r["zip"],
        "credit_card_bin": r["bin"], "credit_card_company": r["card_company"],
        "Spent": r["_spend"], "Count of CUST_ID": r["_orders"],
        "Last Shopped": r["_last_shopped"], "SEGMENT": "Final Client",
    }


def grade_series(scored):
    """(tier-code Series, surfaced-bool Series) for a scored frame."""
    tiers = scored[SCORE_COL].map(lambda raw: tier_for(to_score100(float(raw))))
    return tiers, scored[HIDDEN_COL]


def emit_orders(r, rng, order_seq):
    """Yield Shopify order dicts + (order_id -> transactions) for one customer."""
    n = r["_orders"]
    per = round(r["_spend"] / n, 2)
    addr = {"name": r["Name"], "company": r["company"] or None,
            "address1": r["address1"], "address2": r["address2"] or None,
            "city": r["city"], "country": r["country"] or None, "zip": r["zip"],
            "phone": r["PHONE"]}
    orders, txns = [], {}
    for k in range(n):
        oid = order_seq + k
        created = _T0 + timedelta(days=rint(rng, 0, 720), hours=rint(rng, 0, 23))
        txn = [{"id": oid * 10, "kind": "sale", "status": "success", "gateway": "shopify_payments",
                "amount": f"{per:.2f}", "currency": r["currency"],
                "payment_details": {"credit_card_bin": r["bin"],
                                    "credit_card_company": r["card_company"],
                                    "credit_card_number": "•••• •••• •••• " + str(rint(rng, 1000, 9999))}}]
        orders.append({
            "id": oid, "email": r["EMAIL_ADDR"], "phone": r["PHONE"],
            "created_at": created.isoformat(), "currency": r["currency"],
            "total_price": per, "financial_status": "paid",
            "browser_ip": f"{rint(rng,2,223)}.{rint(rng,0,255)}.{rint(rng,0,255)}.{rint(rng,1,254)}",
            "tags": "", "line_items": [{"quantity": rint(rng, 1, 4)}],
            "customer": {"id": r["_id"], "first_name": r["Name"], "last_name": "",
                         "email": r["EMAIL_ADDR"], "phone": r["PHONE"], "tags": ""},
            "billing_address": dict(addr), "shipping_address": dict(addr),
            "transactions": txn,  # payment info embedded (BIN + brand) on the record
        })
        txns[oid] = txn
    return orders, txns


def _score_identities(identities):
    df = pd.DataFrame([identity_to_row(r) for r in identities])
    scored = score_customers(df)
    return grade_series(scored)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    rng = random.Random(seed)
    targets = {"A1": 0.002, "A": 0.01, "B": 0.05, "C": 0.07}
    want = {g: round(n * f) for g, f in targets.items()}
    print(f"Target {n:,}: A* {want['A1']} / A {want['A']} / B {want['B']} / C {want['C']} "
          f"/ none {n - sum(want.values())}  (seed={seed})")

    # ── PASS 1: over-generate graded candidates, score, bucket by ACHIEVED grade.
    # Generate aiming each band (with inflation); selection self-corrects co-fire drift.
    aim = {"A1": max(400, want["A1"] * 3), "A": max(1500, want["A"] * 2),
           "B": want["B"] * 2, "C": want["C"] * 2}
    buckets = {g: [] for g in targets}
    idc = 0
    rounds = 0
    while any(len(buckets[g]) < want[g] for g in targets) and rounds < 12:
        rounds += 1
        batch = []
        for g, k in aim.items():
            short = max(0, want[g] - len(buckets[g]))
            if short:
                batch += [(g, make_identity(rng, idc + j, g)) for j in range(k)]
                idc += k
        tiers, surfaced = _score_identities([r for _, r in batch])
        for (_aim, r), code, surf in zip(batch, tiers, surfaced):
            if surf and code in buckets and len(buckets[code]) < want[code]:
                buckets[code].append(r)
        print(f"  round {rounds}: " + " ".join(f"{GRADE_LABEL[g]}={len(buckets[g])}/{want[g]}" for g in targets))

    graded = [r for g in targets for r in buckets[g][:want[g]]]

    # ── none customers: must NOT surface. Generate, score, regenerate any surfacers.
    n_none = n - len(graded)
    none = [make_identity(rng, idc + j, None) for j in range(n_none)]
    idc += n_none
    for _ in range(6):
        tiers, surfaced = _score_identities(none)
        bad = [i for i, s in enumerate(surfaced) if s]
        if not bad:
            break
        for i in bad:
            none[i] = make_identity(rng, idc, None)
            idc += 1
        print(f"  none: regenerated {len(bad)} accidental surfacers")

    customers = graded + none
    rng.shuffle(customers)
    for newid, r in enumerate(customers):
        r["_id"] = newid

    # ── Emit native Shopify orders (+payment) and aggregate via the REAL adapter.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ndjson_path = OUTPUT_DIR / "synthetic_shopify_orders.ndjson"
    all_orders, all_txns = [], {}
    order_seq = 1_000_000
    with ndjson_path.open("w", encoding="utf-8") as fh:
        for r in customers:
            orders, txns = emit_orders(r, rng, order_seq)
            order_seq += len(orders)
            all_txns.update(txns)
            for o in orders:
                fh.write(json.dumps(o) + "\n")
            all_orders.extend(orders)
    print(f"\nWrote {len(all_orders):,} Shopify orders -> {ndjson_path}")

    print("Aggregating via scoring.shopify.orders_to_customers + scoring ...")
    cust = orders_to_customers(all_orders, all_txns, today=pd.Timestamp("2026-06-26", tz="UTC"))
    cust = cust.rename(columns={"orders_count": "Count of CUST_ID"})
    scored = score_customers(cust)
    tiers, surfaced = grade_series(scored)

    print("\n=== Achieved grade distribution (surfaced hidden VICs) ===")
    for code in ("A1", "A", "B", "C"):
        c = int((surfaced & (tiers == code)).sum())
        print(f"  {GRADE_LABEL[code]:>2} : {c:6,d}  ({c / len(scored):.3%})  target {want[code]:,}")
    print(f"  hidden VICs total : {int(surfaced.sum()):,} / {len(scored):,}")
    print(f"  no-signal (not surfaced) : {int((~surfaced).sum()):,}")

    print("\n=== Per-signal fire counts (active signals) ===")
    for key, label, _apply, flag_col, _r in active_signals():
        if flag_col in scored.columns:
            fired = int(scored[flag_col].fillna(False).astype(bool).sum())
            print(f"  {label:<24} {key:<20} {fired:7,d}")

    xlsx_path = ROOT / "sample_data" / "synthetic_100k.xlsx"
    drop = [c for c in ("tags", "Items", "Discounted", "ShipKey", "avg_order_value",
                        "full_price_ratio", "tenure_days", "days_since_last_order",
                        "single_order_then_silent", "distinct_shipping_addresses",
                        "first_order_at", "last_order_at") if c in cust.columns]
    export = cust.drop(columns=drop)
    for col in ("Last Shopped", "first_order_at", "last_order_at"):
        if col in export.columns and pd.api.types.is_datetime64_any_dtype(export[col]):
            export[col] = export[col].dt.tz_localize(None)
    print(f"\nWriting {xlsx_path} ({len(export):,} rows) ...")
    export.to_excel(xlsx_path, sheet_name="Export", index=False, engine="openpyxl")
    print("Done. To view in the MVP: point config.DATA_FILE at sample_data/synthetic_100k.xlsx, "
          "then run `python build_mvp.py`.")


if __name__ == "__main__":
    main()
