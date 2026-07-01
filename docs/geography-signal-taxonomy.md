# Geography signal taxonomy

> How Halia handles address-based signals, and why each one is on or off by default. This is the
> document to hand a DPO who asks "how do you treat sensitive geography?". Companion to
> [dpia-lia-support.md](dpia-lia-support.md) and [privacy-notice-profiling.md](privacy-notice-profiling.md).

## The test
Every geography signal answers one question: **does it sort by where someone is *from* (national /
ethnic origin — caught by UK GDPR Recital 71 and the Equality Act *by effect*, not by label), or by a
*wealth fact* about a place?** Origin sorts are off by default; wealth facts are on. Renaming an origin
signal does not cure it — so the taxonomy is enforced by the *inclusion criteria*, written below, not by
the name on the tin.

We used to run a signal called **`tax_haven`**. The name was the problem: "tax haven" asserts an
inference about a person's private financial conduct (structuring wealth to avoid tax) — which reads
terribly in an audit trail and invites scrutiny the evidence doesn't warrant. But what it *observed* was
a billing address in Monaco, Jersey, Guernsey, the Isle of Man, Liechtenstein — places where **living
there is itself a wealth fact**. So we retired the name and split the list into the three things it
always was.

## The three buckets

### Bucket 1 — residence-is-wealth jurisdictions → `wealth_jurisdiction` (ON by default)
Jurisdictions where residence itself is the wealth signal: Monaco, Jersey, Guernsey, Isle of Man,
Liechtenstein, Andorra, San Marino, Gibraltar, Cayman, Bermuda. These are among the most expensive
residential markets on earth, and their residents come from **every** nationality — so the correlation
is with property wealth, not origin. Same species as a Mayfair W1 postcode. On by default, in the `geo`
group. Reference: [`reference_data/countries/wealth_jurisdictions.csv`](../reference_data/countries/wealth_jurisdictions.csv).
Reason text is factual: *"Monaco — high-value residential jurisdiction (billing)"*.

### Bucket 2 — structural → `wealth_structure` (ON by default)
The tell is not geography, it's that a person's shopping is **routed through a wealth-management
structure**: a trust company, family office, corporate registered agent, fiduciary, or an offshore PO
box. That's a wealth fact and it is **origin-neutral** (a family office has no nationality) — arguably a
stronger signal than the address itself, and it pairs with the household-linkage work (`shared_phone`).
On by default, stands alone. Reference:
[`reference_data/addresses/wealth_structures.csv`](../reference_data/addresses/wealth_structures.csv).
Named structures fire alone; a bare "PO Box" only fires alongside an offshore incorporation jurisdiction
(BVI / Cayman / Panama / Seychelles / Mauritius / Bermuda). Reason text: *"Address routed through a
family office"*, *"Address is an offshore PO box (British Virgin Islands)"*.

### Bucket 3 — origin-correlated → gated
Where the correlation runs to **nationality and origin** rather than property prices.
- **Country-level Gulf** (`gcc_billing`): a UAE / Saudi / Qatar *country* on the address flags a
  population that is heavily Gulf-national and Gulf-diaspora. It fails the effect test permanently and
  **stays off by default** (unchanged).
- **District-level Gulf** (`gulf_prime_district`, **new, gated**): Emirates Hills, Palm Jumeirah,
  Downtown Dubai, the Riyadh Diplomatic Quarter and peers are genuinely among the most expensive
  residential districts on earth, with famously international residents — so district-level Gulf is
  *arguable* wealth-geography. But even so, in a UK retailer's book a district-level Gulf signal still
  disproportionately touches Middle-Eastern clients, so the effect test isn't as clean as Monaco's. We
  therefore keep it **off by default** in the same opt-in tier as the other origin-adjacent signals. A
  tenant with a genuine, documented Gulf clientele switches it on (`include_origin=True`); everyone
  else's default stays clean. This is a deliberate bright line: prime Gulf districts were previously
  scoring on-by-default (inside `hnw_area` / `intl_postcode`) and were **moved out** into this gated
  signal. Reference:
  [`gulf_prime_districts.csv`](../reference_data/locations/gulf_prime_districts.csv) +
  [`gulf_prime_postcodes.csv`](../reference_data/locations/gulf_prime_postcodes.csv).
  *(Lebanon's prime districts remain in `hnw_area` for now and are a candidate for the same review.)*

## Two disciplines that keep this honest
1. **Reason text is factual.** Audit/reason strings say "high-value residential jurisdiction", "prime
   residential district", "address routed through a family office" — **never** "tax haven", "offshore"
   (as a pejorative), "avoidance", or any inference about a person's tax affairs or origin.
2. **Inclusion criteria are written down, and sourced from property-market data.** A jurisdiction or
   district is on a Bucket-1/Bucket-3 list because of **residential property cost & exclusivity**,
   evidenced per row in the CSV headers — *not* because it appears on an OECD/EU tax blacklist. If the
   inclusion criterion were a tax-avoidance list, we would have reimported the inference through the back
   door. Bucket 2's keyword list is curated to be specific (two-word structural phrases) so ordinary
   company names don't false-fire.

## Origin fields corroborate, never originate
Some fields speak to **origin** rather than to residence or operation: a phone dialling code, an email
country-code TLD (`.fr`, `.ae`, `.je`). They correlate with nationality at least as strongly as a
billing *country* does, and they are *worse* evidence than an address — a phone/inbox is a stale,
portable claim about where a number was once registered; an address is operationally verified (goods
arrive, cards are registered). So the class rule is absolute:

> **Nothing derived from a phone-jurisdiction or email-country lookup originates a score.** The whole
> class stays behind the `include_origin` gate.

The one legitimate on-by-default use is **agreement-as-confidence**: if a customer's billing address is
already in a high-value jurisdiction/district **and** their phone (or email ccTLD) jurisdiction *agrees*
with that address's country, the agreement slightly raises confidence that this is genuine residence
(not a forwarding address). It is expressed as a small-weight **corroboration** signal, precondition-
gated so it can only ever fire alongside — and help — a signal we've already justified. **Disagreement
does nothing** (no penalty, no mismatch flag — those stay gated). Reason text is a bare fact: *"phone
jurisdiction consistent with billing address"*. Because it can only agree with an address, never speak
first, it never independently sorts anyone.

Email is the same shape with one addition: the value in an email address is **everything to the left of
the country suffix**. The domain's *organisation* is a first-class, origin-neutral signal (a
`goldmansachs.com` address is a wealth-adjacent *work* fact; a domain resolving to a family office,
private practice, chambers, or yacht-management firm is the **structural** signal of Bucket 2, the same
species as a trust-company address). Only the domain's *country* is the gated origin proxy that may
corroborate but never originate. One-line summary of the whole taxonomy: **Halia scores where people
live and how they operate, and never where they're from; any field that speaks to origin is only ever
allowed to agree with an address, never to speak first.**

*Status (implemented 2026-07):* the class gating (phone lookups behind `include_origin`) and the
agreement-as-confidence signal (`geo_confirmation` — `scoring/signals/geo_confirmation.py`, weight 1,
SUPPORTING, runs last so it reads the wealth-geo flags; confirms via phone dialling code
[`dialing_code_countries.csv`] or email ccTLD [`cctld_countries.csv`] agreeing with the address
country) are live. The email **ccTLD is corroboration-only** — there is deliberately no gated
originating ccTLD signal; the country suffix may only ever agree with an address. The structural
**email-domain** extension lands in `domain_keyword`'s elite tier (trust company / fiduciary /
chambers / yacht management / private office / family office resolve at the elite weight, the email
twin of the `wealth_structure` address signal).

## Where it lives in code
`scoring/combine.py` is authoritative: `SIGNAL_WEIGHTS`, `SIGNAL_GROUP`, and `ORIGIN_PROXY_SIGNALS`
(the gate). Signals: `scoring/signals/wealth_jurisdiction.py`, `wealth_structure.py`,
`gulf_prime_district.py`, `gcc_billing.py`. Keep [dpia-lia-support.md](dpia-lia-support.md) §6 in step.
