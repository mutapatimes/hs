"""Combine the individual signals into one score per customer.

Runs every signal over the data, sums their weights into a ``signal_score``,
collects the human-readable ``reasons``, and flags ``hidden_vic`` — a customer
that one or more signals fired on but who still spends below the VIC threshold
(i.e. a top-client tell, on someone you have not yet recognised as one).

Weights live in SIGNAL_WEIGHTS and are meant to be tuned. A low weight makes a
signal a weak "supporting" tell rather than a strong one (that's how the future
athlete name-match signal will slot in: flag all, rank low).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scoring.signals import (
    assistant_order,
    card_bin,
    card_brand,
    companies_house,
    company_keyword,
    custom_email,
    domain_keyword,
    delivery_venue,
    elite_alumni,
    foreign_currency,
    gcc_billing,
    geo_confirmation,
    hnw_area,
    fashion_stylist,
    stylist_directory,
    heritage_surname,
    hnwi_postcode,
    honorific,
    hotel_concierge,
    intl_postcode,
    ip_location,
    landline,
    name_mismatch,
    name_structure,
    nobiliary_particle,
    origin_adjacent_district,
    phone_country,
    phone_mismatch,
    post_nominal,
    premium_email,
    property_value,
    styling_service,
    prime_residence,
    rich_list,
    shared_phone,
    us_zip,
    wealth_jurisdiction,
    wealth_office,
    wealth_structure,
    work_email,
)

# Editable. Higher = stronger signal. Low (1) = supporting "flag all, rank low".
SIGNAL_WEIGHTS: dict[str, int] = {
    "work_email": 3,
    "hnwi_postcode": 3,
    "us_hnwi_zip": 3,
    "intl_postcode": 3,
    "hnw_area": 3,
    "property_value": 2,  # base; the tier (ultra/prime/high) overrides, see PROPERTY_TIER_WEIGHTS
    "hotel_concierge": 3,
    "delivery_venue": 3,
    "styling_service": 3,  # B2B trade account — buys for many UHNW clients
    "prime_residence": 3,
    "premium_card": 3,
    "gcc_billing": 2,
    "honorific": 2,
    "company_keyword": 2,
    "wealth_jurisdiction": 2,  # billing/shipping in a high-value residential jurisdiction
                               # (Monaco, Jersey…) — a wealth fact, on by default
    "wealth_structure": 3,     # address routed through a trust co / family office / registered
                               # agent — origin-neutral, arguably stronger than the address
    "origin_adjacent_district": 2,  # prime district whose flagged pop skews to one origin — GATED
    "geo_confirmation": 1,      # phone/email jurisdiction AGREES with a high-value address —
                               # corroboration only (supporting; never originates a score)
    "premium_email": 2,
    "wealth_office": 2,
    "elite_alumni": 2,
    "assistant_order": 2,
    "name_mismatch": 2,  # buyer-name ≠ email-name — corroboration-only (see SUPPORTING_SIGNALS)
    "post_nominal": 2,
    "phone_country": 1,
    "phone_mismatch": 2,  # phone jurisdiction != address country — a cleaner mobility tell
    "shared_phone": 2,    # same number on 2+ records — household / assistant linkage
    "landline": 1,        # a fixed line — soft tell of an established household / office
    "foreign_currency": 1,
    "card_brand": 1,
    "rich_list": 1,
    "companies_house": 1,  # PSC/director name match — very broad, corroboration-only (see SUPPORTING_SIGNALS)
    "fashion_stylist": 2,  # celebrity stylist / personal shopper — high-value, name-match (verify)
    "stylist_directory": 1,  # broad stylist directory — corroboration-only (see SUPPORTING_SIGNALS)
    "ip_location": 1,
    "domain_keyword": 2,  # finance/high-earning keyword in a custom domain
    "custom_email": 1,
    "heritage_surname": 1,  # surnames are shared -> low; only rare dynasties listed
    "name_structure": 1,  # floor; a single knob — set to 0 to switch this signal off
    "nobiliary_particle": 1,  # floor; aristocratic particle (de/von) — corroboration-only
}

# Within delivery_venue, some venue TYPES are far stronger wealth tells than
# others: shipping to a private-jet FBO or a superyacht marina is huge. These
# override the signal's base weight; unlisted types fall back to it.
DELIVERY_TYPE_WEIGHTS = {
    "private_jet_fbo": 5,
    "marina": 5,
}

# Within domain_keyword, an ELITE-finance domain (private equity / hedge fund /
# family office) outweighs a general high-earning one — weight 3 vs the base 2.
DOMAIN_KEYWORD_TYPE_WEIGHTS = {
    "elite": 3,
    "general": 2,
}

# Within property_value, the area's value TIER grades the tell: an ultra-prime area
# median outweighs a merely high-value one. Overrides the signal's base weight.
PROPERTY_TIER_WEIGHTS = {
    "ultra": 4,
    "prime": 3,
    "high": 2,
}

# "Supporting" signals are too weak/sensitive to ever flag a customer on their
# own: they contribute to the score and count ONLY when at least one stronger
# (non-supporting) signal has also fired. This enforces "never a sole basis".
SUPPORTING_SIGNALS = {"name_structure", "nobiliary_particle", "assistant_order", "name_mismatch",
                      "stylist_directory", "landline",  # a fixed line is common — corroborates,
                      # never surfaces a customer on its own

                      # A bare custom (non-free) email domain is far too common to be a
                      # VIC on its own — half a store's buyers can have one. It corroborates
                      # (e.g. alongside a premium provider, company billing, or prime
                      # postcode) but never surfaces a customer by itself.
                      "custom_email",

                      # A Companies House PSC/director name match is drawn from a register of
                      # millions, so name-alone collisions are common. Unlike the curated
                      # rich_list, it must never be a sole basis — it only corroborates.
                      "companies_house",

                      # geo_confirmation is agreement-as-confidence: a phone/email jurisdiction
                      # AGREEING with a high-value address. It requires a wealth-geo signal to
                      # have fired, so it can never originate a score — pure corroboration.
                      "geo_confirmation",

                      # NAME-MATCH BRIGHT LINE: no name-only match surfaces a customer alone.
                      # A name matched against a list (rich_list, a celebrity stylist) is a
                      # namesake-collision risk, so — like companies_house — it only corroborates.
                      # (heritage_surname / name_structure / nobiliary_particle are gated origin
                      # proxies; post_nominal is a name-borne credential — all held to the same line.)
                      "rich_list", "fashion_stylist", "post_nominal"}

# Some signals are CORRELATED — they encode the same underlying fact from
# different fields. Three "this person is in the UAE" tells (billing country,
# phone dialling code, postcode) are largely ONE piece of evidence, not three.
# Signals sharing a group get DIMINISHING RETURNS: within a group the strongest
# fired signal counts in full, each additional one counts at GROUP_DECAY ** rank.
# Signals with no group entry stand alone (full weight). Different groups still
# add fully — independent evidence is rewarded, redundant evidence is not.
GROUP_DECAY = 0.5
SIGNAL_GROUP: dict[str, str] = {
    # Geography / "where they are" — all correlated location tells.
    "hnwi_postcode": "geo",
    "us_hnwi_zip": "geo",
    "intl_postcode": "geo",
    "hnw_area": "geo",
    "property_value": "geo",  # area property value echoes the same location
    "prime_residence": "geo",
    "gcc_billing": "geo",
    "wealth_jurisdiction": "geo",  # high-value residential jurisdiction (was tax_haven)
    "origin_adjacent_district": "geo",  # gated prime district — same location species
    "geo_confirmation": "geo",     # phone/email agreeing with an address — decays as a nudge
    "phone_country": "geo",
    "phone_mismatch": "geo",
    "ip_location": "geo",
    "foreign_currency": "geo",  # currency largely echoes location
    # Name-based tells are correlated ("their name signals status") — group them
    # so a rich-list + dynasty-surname + name-structure pile-up doesn't stack.
    "rich_list": "name",
    "companies_house": "name",  # a name-based control tell — correlated with other name tells
    "fashion_stylist": "name",
    "stylist_directory": "name",
    "heritage_surname": "name",
    "name_structure": "name",
    "name_mismatch": "name",
    "nobiliary_particle": "name",
    "post_nominal": "name",
    # Payment tells (gated; mostly dormant) — don't let BIN + brand double-count.
    "premium_card": "payment",
    "card_brand": "payment",
    # Email-domain tells — a finance-keyword domain IS also a custom domain, so
    # group them: the stronger (domain_keyword) counts in full, custom_email at decay.
    "custom_email": "email",
    "domain_keyword": "email",
}

# A customer already spending at/above this is a known top client, so a signal
# hit on them isn't "hidden". PLACEHOLDER — set to the merchant's VIC spend cutoff.
# (The old VIP/VIC SEGMENT tag was a manual Power BI artifact and doesn't exist in
# the Shopify data; SEGMENT is now display-only and no longer gates hidden_vic.)
VIC_SPEND_THRESHOLD = 5000.0

SCORE_COL = "signal_score"
COUNT_COL = "signal_count"
CONFIDENCE_COL = "signal_confidence"   # breadth of INDEPENDENT evidence (distinct groups fired)
REASONS_COL = "reasons"
HIDDEN_COL = "hidden_vic"

# Engine identity for audit: every scored payload can carry a version + a fingerprint of the
# active weights/gates, so "why did this customer score this way in March" has an exact answer.
ENGINE_VERSION = "1.1"


def _reason_delivery(row: pd.Series) -> str:
    return f"{row[delivery_venue.VENUE_COL]} ({row[delivery_venue.TYPE_COL]})"


# (key, label, apply_fn, flag_col, reason_fn)
SIGNALS = [
    ("work_email", "Work email", work_email.flag_work_email,
     work_email.FLAG_COL, lambda r: r[work_email.REASON_COL]),
    ("premium_email", "Premium email", premium_email.flag_premium_email,
     premium_email.FLAG_COL, lambda r: r[premium_email.REASON_COL]),
    ("elite_alumni", "Ivy alumni", elite_alumni.flag_elite_alumni,
     elite_alumni.FLAG_COL, lambda r: r[elite_alumni.REASON_COL]),
    ("hotel_concierge", "Hotel concierge", hotel_concierge.flag_hotel_concierge,
     hotel_concierge.FLAG_COL, lambda r: r[hotel_concierge.REASON_COL]),
    ("styling_service", "Styling service (B2B)", styling_service.flag_styling_service,
     styling_service.FLAG_COL, lambda r: r[styling_service.REASON_COL]),
    ("custom_email", "Custom domain", custom_email.flag_custom_email,
     custom_email.FLAG_COL, lambda r: r[custom_email.REASON_COL]),
    ("domain_keyword", "High-earning domain", domain_keyword.flag_domain_keyword,
     domain_keyword.FLAG_COL, lambda r: r[domain_keyword.REASON_COL]),
    ("hnwi_postcode", "HNWI postcode", hnwi_postcode.flag_hnwi_postcode,
     hnwi_postcode.FLAG_COL, lambda r: r[hnwi_postcode.REASON_COL]),
    ("us_hnwi_zip", "US prime ZIP", us_zip.flag_us_zip,
     us_zip.FLAG_COL, lambda r: r[us_zip.REASON_COL]),
    ("intl_postcode", "Intl prime postcode", intl_postcode.flag_intl_postcode,
     intl_postcode.FLAG_COL, lambda r: r[intl_postcode.REASON_COL]),
    ("hnw_area", "HNW area", hnw_area.flag_hnw_area,
     hnw_area.MATCH_COL, lambda r: f"{r[hnw_area.AREA_COL]} ({r[hnw_area.TYPE_COL]})"),
    ("property_value", "Prime area", property_value.flag_property_value,
     property_value.FLAG_COL, lambda r: r[property_value.REASON_COL]),
    ("wealth_office", "Wealth office", wealth_office.flag_wealth_office,
     wealth_office.MATCH_COL, lambda r: r[wealth_office.OFFICE_COL]),
    ("wealth_structure", "Wealth structure", wealth_structure.flag_wealth_structure,
     wealth_structure.FLAG_COL, lambda r: r[wealth_structure.REASON_COL]),
    ("delivery_venue", "Delivery", delivery_venue.flag_delivery_venue,
     delivery_venue.MATCH_COL, _reason_delivery),
    ("prime_residence", "Prime residence", prime_residence.flag_prime_residence,
     prime_residence.MATCH_COL, lambda r: r[prime_residence.RESIDENCE_COL]),
    ("gcc_billing", "GCC billing", gcc_billing.flag_gcc_billing,
     gcc_billing.FLAG_COL, lambda r: r[gcc_billing.COUNTRY_COL]),
    ("wealth_jurisdiction", "High-value area", wealth_jurisdiction.flag_wealth_jurisdiction,
     wealth_jurisdiction.FLAG_COL, lambda r: r[wealth_jurisdiction.REASON_COL]),
    ("origin_adjacent_district", "Prime residential district", origin_adjacent_district.flag_origin_adjacent_district,
     origin_adjacent_district.FLAG_COL, lambda r: r[origin_adjacent_district.REASON_COL]),
    ("honorific", "Honorific", honorific.flag_honorific,
     honorific.FLAG_COL, lambda r: r[honorific.REASON_COL]),
    ("company_keyword", "Company", company_keyword.flag_company_keyword,
     company_keyword.FLAG_COL, lambda r: r[company_keyword.REASON_COL]),
    ("phone_country", "Phone", phone_country.flag_phone_country,
     phone_country.FLAG_COL, lambda r: r[phone_country.REASON_COL]),
    ("phone_mismatch", "Phone ≠ address", phone_mismatch.flag_phone_mismatch,
     phone_mismatch.FLAG_COL, lambda r: r[phone_mismatch.REASON_COL]),
    ("shared_phone", "Shared phone", shared_phone.flag_shared_phone,
     shared_phone.FLAG_COL, lambda r: r[shared_phone.REASON_COL]),
    ("landline", "Landline", landline.flag_landline,
     landline.FLAG_COL, lambda r: r[landline.REASON_COL]),
    ("rich_list", "Rich list", rich_list.flag_rich_list,
     rich_list.FLAG_COL, lambda r: r[rich_list.REASON_COL]),
    ("companies_house", "Companies House", companies_house.flag_companies_house,
     companies_house.FLAG_COL, lambda r: r[companies_house.REASON_COL]),
    ("fashion_stylist", "Fashion stylist", fashion_stylist.flag_fashion_stylist,
     fashion_stylist.FLAG_COL, lambda r: r[fashion_stylist.REASON_COL]),
    ("stylist_directory", "Possible stylist", stylist_directory.flag_stylist_directory,
     stylist_directory.FLAG_COL, lambda r: r[stylist_directory.REASON_COL]),
    ("heritage_surname", "Heritage surname", heritage_surname.flag_heritage_surname,
     heritage_surname.FLAG_COL, lambda r: r[heritage_surname.REASON_COL]),
    ("premium_card", "Premium card", card_bin.flag_card_bin,
     card_bin.FLAG_COL, lambda r: r[card_bin.REASON_COL]),
    ("ip_location", "IP location", ip_location.flag_ip_location,
     ip_location.FLAG_COL, lambda r: r[ip_location.REASON_COL]),
    ("name_structure", "Name structure", name_structure.flag_name_structure,
     name_structure.FLAG_COL, lambda r: r[name_structure.REASON_COL]),
    ("nobiliary_particle", "Nobiliary particle", nobiliary_particle.flag_nobiliary_particle,
     nobiliary_particle.FLAG_COL, lambda r: r[nobiliary_particle.REASON_COL]),
    ("assistant_order", "Assistant order", assistant_order.flag_assistant_order,
     assistant_order.FLAG_COL, lambda r: r[assistant_order.REASON_COL]),
    ("name_mismatch", "Name mismatch", name_mismatch.flag_name_mismatch,
     name_mismatch.FLAG_COL, lambda r: r[name_mismatch.REASON_COL]),
    ("post_nominal", "Post-nominal", post_nominal.flag_post_nominal,
     post_nominal.FLAG_COL, lambda r: r[post_nominal.REASON_COL]),
    ("foreign_currency", "Foreign currency", foreign_currency.flag_foreign_currency,
     foreign_currency.FLAG_COL, lambda r: r[foreign_currency.REASON_COL]),
    ("card_brand", "Premium card brand", card_brand.flag_card_brand,
     card_brand.FLAG_COL, lambda r: r[card_brand.REASON_COL]),
    # MUST STAY LAST: geo_confirmation reads the wealth-geo flag columns added by the signals
    # above (agreement-as-confidence only fires when a wealth-geography signal already fired).
    ("geo_confirmation", "Geo confirmation", geo_confirmation.flag_geo_confirmation,
     geo_confirmation.FLAG_COL, lambda r: r[geo_confirmation.REASON_COL]),
]


# ── CORE PRODUCT SCOPE ───────────────────────────────────────────────────────
# The client picture is built from IDENTITY + LOCATION data only — name, phone,
# email, address, postcode, geo (plus order value for grading/latent). PAYMENT /
# transaction signals (card BIN, card brand, currency paid) are PARKED: they're a
# transaction attribute, not who-they-are, and we deliberately avoid behaviour
# data. Code + reference data stay; they just don't score. Set CORE_DATA_ONLY =
# False to bring them back.
CORE_DATA_ONLY = True
# premium_card (BIN -> issuer/tier) is ACTIVE: payment method as a signal + filter.
# card_brand (Amex/Diners) and foreign_currency remain parked.
# foreign_currency is DELIBERATELY in BOTH this set and ORIGIN_PROXY_SIGNALS: parked removes it
# now (transaction data we don't score), and the origin-proxy membership is belt-and-suspenders —
# if anyone ever un-parks it (CORE_DATA_ONLY=False), it still stays gated as origin-correlated.
PARKED_SIGNALS = {"card_brand", "foreign_currency"}

# Signals that sort by national / ethnic / name origin rather than by wealth facts.
# These are OFF BY DEFAULT so Halia is lawful-by-default: they never apply, score, or
# appear in `reasons` unless a caller explicitly opts in (include_origin=True) for a
# tenant that has documented a lawful basis. A UK origin-effect (Recital 71 / Equality
# Act) is caught by the effect, not the label, so the safe default is simply not to run
# them. See docs/dpia-lia-support.md for the rationale and the wealth-fact vs origin split.
# (intl_postcode / hnw_area / wealth_jurisdiction / wealth_structure stay ON: they match a
# SPECIFIC ultra-prime address, a high-value residential jurisdiction, or a wealth-management
# structure — property/wealth facts, not a sort by country-of-origin. See the three-bucket
# taxonomy in docs/geography-signal-taxonomy.md. The prime ORIGIN-ADJACENT DISTRICTS (Gulf, Lebanon, …) were split out of
# hnw_area/intl_postcode into the gated origin_adjacent_district signal: district-level Gulf still
# disproportionately touches Middle-Eastern clients in a UK book, so it is opt-in.)
# phone_mismatch (phone jurisdiction != address country) is a SOFTER origin proxy than raw
# phone_country — it reads mobility, not "where they're from" — but it is still derived from the
# phone country code, so it stays behind the same gate. Upward-only ("recognition, not
# deprioritisation") profiling defends the significant-effect / Art. 22 axis, not the
# discrimination axis (Recital 71 catches beneficial sorting too), so it is off by default.
ORIGIN_PROXY_SIGNALS = {"gcc_billing", "origin_adjacent_district", "phone_country", "phone_mismatch",
                        "foreign_currency", "nobiliary_particle", "name_structure",
                        "heritage_surname"}


def active_signals(include_origin: bool = False) -> list:
    """Signals in scope. Parked transaction signals are dropped (when CORE_DATA_ONLY),
    and the origin-proxy signals are dropped too unless ``include_origin`` is set."""
    excluded = set(PARKED_SIGNALS) if CORE_DATA_ONLY else set()
    if not include_origin:
        excluded |= ORIGIN_PROXY_SIGNALS
    return [s for s in SIGNALS if s[0] not in excluded]


def run_all_signals(df: pd.DataFrame, include_origin: bool = False) -> pd.DataFrame:
    """Apply every in-scope signal, returning a copy with their columns added."""
    out = df
    for _key, _label, apply_fn, _flag, _reason in active_signals(include_origin):
        out = apply_fn(out)
    return out


def score_customers(
    df: pd.DataFrame,
    weights: dict[str, int] | None = None,
    vic_threshold: float = VIC_SPEND_THRESHOLD,
    include_origin: bool = False,
) -> pd.DataFrame:
    """Add signal_score, signal_count, reasons, and hidden_vic columns.

    ``include_origin`` is OFF by default: origin-proxy signals (nationality / name /
    ethnicity tells, see ORIGIN_PROXY_SIGNALS) do not contribute or surface unless a
    caller opts in for a tenant with a documented lawful basis.
    """
    weights = weights or SIGNAL_WEIGHTS
    out = run_all_signals(df, include_origin)
    active = active_signals(include_origin)

    flag_of = {key: flag_col for key, _l, _a, flag_col, _r in active}
    grouped: dict[str, list[str]] = {}
    for key, _l, _a, _f, _r in active:
        grouped.setdefault(SIGNAL_GROUP.get(key, key), []).append(key)

    n = len(out)
    fired_of = {
        key: out[flag_of[key]].fillna(False).astype(bool).to_numpy() for key in flag_of
    }

    # Corroboration gate: a SUPPORTING signal counts only when a stronger
    # (non-supporting) signal has also fired — so it can never flag on its own.
    core = np.zeros(n, dtype=int)
    for key, arr in fired_of.items():
        if key not in SUPPORTING_SIGNALS:
            core = core + arr.astype(int)
    has_core = core > 0
    for key in SUPPORTING_SIGNALS:
        if key in fired_of:
            fired_of[key] = fired_of[key] & has_core
            out[flag_of[key]] = fired_of[key]  # keep reasons/display consistent

    score = np.zeros(n)
    count = np.zeros(n, dtype=int)
    for keys in grouped.values():
        cols = []
        for key in keys:
            fired = fired_of[key]
            count = count + fired.astype(int)
            base = int(weights.get(key, 0))
            type_spec = None
            if key == "delivery_venue":
                type_spec = (delivery_venue.TYPE_COL, DELIVERY_TYPE_WEIGHTS)
            elif key == "domain_keyword":
                type_spec = (domain_keyword.TYPE_COL, DOMAIN_KEYWORD_TYPE_WEIGHTS)
            elif key == "property_value":
                type_spec = (property_value.TIER_COL, PROPERTY_TIER_WEIGHTS)
            if type_spec and type_spec[0] in out.columns:
                type_col, type_weights = type_spec
                wv = out[type_col].map(
                    lambda t: type_weights.get(t, base)
                ).to_numpy(dtype=float)
                cols.append(fired * wv)
            else:
                cols.append(fired * float(base))
        # Per row, sort the group's fired weights high->low and decay each rank.
        mat = np.column_stack(cols)
        mat = np.sort(mat, axis=1)[:, ::-1]
        decays = GROUP_DECAY ** np.arange(mat.shape[1])
        score = score + (mat * decays).sum(axis=1)
    score = np.round(score, 2)

    def build_reasons(row: pd.Series) -> str:
        parts = []
        for _key, label, _apply, flag_col, reason_fn in active:
            if bool(row.get(flag_col)):
                parts.append(f"{label}: {reason_fn(row)}")
        return "; ".join(parts)

    # Confidence = breadth of INDEPENDENT evidence: how many distinct groups fired, counting
    # only CORE (non-supporting) signals and treating an ungrouped signal as its own group. A
    # one-group A* ("strong signal, single source") is a very different object from a four-group
    # A* ("strong signal, corroborated") — this turns the correlation-decay structure into a
    # user-facing trust cue without changing the score.
    group_fired: dict[str, np.ndarray] = {}
    for key, arr in fired_of.items():
        if key in SUPPORTING_SIGNALS:
            continue
        g = SIGNAL_GROUP.get(key, key)
        group_fired[g] = group_fired.get(g, np.zeros(n, dtype=bool)) | arr
    confidence = (np.sum([a.astype(int) for a in group_fired.values()], axis=0)
                  if group_fired else np.zeros(n, dtype=int))

    out[SCORE_COL] = score
    out[COUNT_COL] = count
    out[CONFIDENCE_COL] = confidence
    out[REASONS_COL] = out.apply(build_reasons, axis=1)

    if "Spent" in out.columns:
        spent = pd.to_numeric(out["Spent"], errors="coerce").fillna(0.0)
    else:
        spent = pd.Series(0.0, index=out.index)
    out[HIDDEN_COL] = (out[COUNT_COL] > 0) & (spent < vic_threshold)
    return out


def top_hidden_vics(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Return the highest-scoring hidden VICs (score, then spend)."""
    scored = df if SCORE_COL in df.columns else score_customers(df)
    hidden = scored[scored[HIDDEN_COL]]
    sort_cols = [SCORE_COL]
    if "Spent" in hidden.columns:
        sort_cols.append("Spent")
    return hidden.sort_values(sort_cols, ascending=False).head(n)


def config_fingerprint() -> dict:
    """Engine version + a short hash of the ACTIVE scoring config (weights, gates, groups, decay,
    threshold). Surfaced on the scored payload so 'why did this customer score this way in March'
    has an exact, checkable answer — the configuration that produced it. Turns 'explain every
    score' from a claim into an audit property."""
    import hashlib
    import json

    payload = {
        "weights": SIGNAL_WEIGHTS,
        "groups": SIGNAL_GROUP,
        "group_decay": GROUP_DECAY,
        "origin_proxies": sorted(ORIGIN_PROXY_SIGNALS),
        "supporting": sorted(SUPPORTING_SIGNALS),
        "parked": sorted(PARKED_SIGNALS),
        "core_data_only": CORE_DATA_ONLY,
        "vic_threshold": VIC_SPEND_THRESHOLD,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return {"version": ENGINE_VERSION, "hash": digest}
