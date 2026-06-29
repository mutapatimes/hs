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
    company_keyword,
    custom_email,
    domain_keyword,
    delivery_venue,
    elite_alumni,
    foreign_currency,
    gcc_billing,
    hnw_area,
    fashion_stylist,
    stylist_directory,
    heritage_surname,
    hnwi_postcode,
    honorific,
    hotel_concierge,
    intl_postcode,
    ip_location,
    name_structure,
    nobiliary_particle,
    phone_country,
    post_nominal,
    premium_email,
    styling_service,
    prime_residence,
    rich_list,
    tax_haven,
    us_zip,
    wealth_office,
    work_email,
)

# Editable. Higher = stronger signal. Low (1) = supporting "flag all, rank low".
SIGNAL_WEIGHTS: dict[str, int] = {
    "work_email": 3,
    "hnwi_postcode": 3,
    "us_hnwi_zip": 3,
    "intl_postcode": 3,
    "hnw_area": 3,
    "hotel_concierge": 3,
    "delivery_venue": 3,
    "styling_service": 3,  # B2B trade account — buys for many UHNW clients
    "prime_residence": 3,
    "premium_card": 3,
    "gcc_billing": 2,
    "honorific": 2,
    "company_keyword": 2,
    "tax_haven": 1,  # billing in a tax-haven COUNTRY is a soft, broad tell (esp.
                     # populous ones like Switzerland) — a corroborator, not primary
    "premium_email": 2,
    "wealth_office": 2,
    "elite_alumni": 2,
    "assistant_order": 2,
    "post_nominal": 2,
    "phone_country": 1,
    "foreign_currency": 1,
    "card_brand": 1,
    "rich_list": 1,
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

# "Supporting" signals are too weak/sensitive to ever flag a customer on their
# own: they contribute to the score and count ONLY when at least one stronger
# (non-supporting) signal has also fired. This enforces "never a sole basis".
SUPPORTING_SIGNALS = {"name_structure", "nobiliary_particle", "assistant_order",
                      "stylist_directory",
                      # A bare custom (non-free) email domain is far too common to be a
                      # VIC on its own — half a store's buyers can have one. It corroborates
                      # (e.g. alongside a premium provider, company billing, or prime
                      # postcode) but never surfaces a customer by itself.
                      "custom_email"}

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
    "prime_residence": "geo",
    "gcc_billing": "geo",
    "tax_haven": "geo",
    "phone_country": "geo",
    "ip_location": "geo",
    "foreign_currency": "geo",  # currency largely echoes location
    # Name-based tells are correlated ("their name signals status") — group them
    # so a rich-list + dynasty-surname + name-structure pile-up doesn't stack.
    "rich_list": "name",
    "fashion_stylist": "name",
    "stylist_directory": "name",
    "heritage_surname": "name",
    "name_structure": "name",
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
REASONS_COL = "reasons"
HIDDEN_COL = "hidden_vic"


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
    ("wealth_office", "Wealth office", wealth_office.flag_wealth_office,
     wealth_office.MATCH_COL, lambda r: r[wealth_office.OFFICE_COL]),
    ("delivery_venue", "Delivery", delivery_venue.flag_delivery_venue,
     delivery_venue.MATCH_COL, _reason_delivery),
    ("prime_residence", "Prime residence", prime_residence.flag_prime_residence,
     prime_residence.MATCH_COL, lambda r: r[prime_residence.RESIDENCE_COL]),
    ("gcc_billing", "GCC billing", gcc_billing.flag_gcc_billing,
     gcc_billing.FLAG_COL, lambda r: r[gcc_billing.COUNTRY_COL]),
    ("tax_haven", "Tax haven", tax_haven.flag_tax_haven,
     tax_haven.FLAG_COL, lambda r: r[tax_haven.REASON_COL]),
    ("honorific", "Honorific", honorific.flag_honorific,
     honorific.FLAG_COL, lambda r: r[honorific.REASON_COL]),
    ("company_keyword", "Company", company_keyword.flag_company_keyword,
     company_keyword.FLAG_COL, lambda r: r[company_keyword.REASON_COL]),
    ("phone_country", "Phone", phone_country.flag_phone_country,
     phone_country.FLAG_COL, lambda r: r[phone_country.REASON_COL]),
    ("rich_list", "Rich list", rich_list.flag_rich_list,
     rich_list.FLAG_COL, lambda r: r[rich_list.REASON_COL]),
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
    ("post_nominal", "Post-nominal", post_nominal.flag_post_nominal,
     post_nominal.FLAG_COL, lambda r: r[post_nominal.REASON_COL]),
    ("foreign_currency", "Foreign currency", foreign_currency.flag_foreign_currency,
     foreign_currency.FLAG_COL, lambda r: r[foreign_currency.REASON_COL]),
    ("card_brand", "Premium card brand", card_brand.flag_card_brand,
     card_brand.FLAG_COL, lambda r: r[card_brand.REASON_COL]),
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
PARKED_SIGNALS = {"card_brand", "foreign_currency"}


def active_signals() -> list:
    """Signals in scope: everything except parked transaction signals."""
    if CORE_DATA_ONLY:
        return [s for s in SIGNALS if s[0] not in PARKED_SIGNALS]
    return list(SIGNALS)


def run_all_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Apply every in-scope signal, returning a copy with their columns added."""
    out = df
    for _key, _label, apply_fn, _flag, _reason in active_signals():
        out = apply_fn(out)
    return out


def score_customers(
    df: pd.DataFrame,
    weights: dict[str, int] | None = None,
    vic_threshold: float = VIC_SPEND_THRESHOLD,
) -> pd.DataFrame:
    """Add signal_score, signal_count, reasons, and hidden_vic columns."""
    weights = weights or SIGNAL_WEIGHTS
    out = run_all_signals(df)
    active = active_signals()

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

    out[SCORE_COL] = score
    out[COUNT_COL] = count
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
