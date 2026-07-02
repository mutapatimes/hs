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
Jurisdictions where residence itself is the wealth signal — the *whole* jurisdiction is ultra-prime
with an internationally-mixed resident base, so the correlation is with property wealth, not origin
(same species as a Mayfair W1 postcode): **Monaco, Jersey, Guernsey, Isle of Man, Liechtenstein,
Cayman, Bermuda.** On by default, in the `geo` group.
[`reference_data/countries/wealth_jurisdictions.csv`](../reference_data/countries/wealth_jurisdictions.csv).
Reason text is factual: *"Monaco — high-value residential jurisdiction (billing)"*.

> **This list is audited against its own criterion.** The document's sharpest claim is that the
> taxonomy is enforced by inclusion criteria, not names — so the list must survive its own test.
> **San Marino, Andorra and Gibraltar were struck (2026-07):** ordinary small jurisdictions with
> modest/mixed housing where most residents are not wealthy — they only ever belonged on the old
> OECD-flavoured "tax haven" list, which is exactly the trap this document warns against. A row
> stays only if residential property cost & exclusivity justify it (evidenced in the CSV header).

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
- **Origin-adjacent prime districts** (`origin_adjacent_district`, gated): districts that are
  genuinely among the most expensive residential markets on earth — Palm Jumeirah's residents, for
  instance, really are international — but whose flagged population *in a typical UK retailer's book*
  skews to a single national origin. So a district-level match, though a real property-wealth tell,
  would in effect sort by origin, and it is held **off by default** in the opt-in tier. Current members:
  the Gulf (Emirates Hills, Palm Jumeirah, Downtown Dubai, the Riyadh Diplomatic Quarter — the case
  degrades from Dubai outward) and **Lebanon** (Achrafieh, Solidere, …). These were **moved out** of
  the on-by-default `hnw_area` / `intl_postcode` lists into this gated signal. A tenant with a genuine,
  documented clientele from a region switches it on (`include_origin=True`); everyone else's default
  stays clean.
  [`origin_adjacent_districts.csv`](../reference_data/locations/origin_adjacent_districts.csv) +
  [`origin_adjacent_postcodes.csv`](../reference_data/locations/origin_adjacent_postcodes.csv).

**The general review rule (this is the operating rule, not a set of regional verdicts).** Any prime
district in any location list is reviewed against one question: **does the flagged population, as it
appears in a typical UK merchant's book, skew to a single national origin?** If yes, it moves to the
gated `origin_adjacent_district` tier regardless of how expensive the real estate is; if no (Monaco,
Gstaad, Mayfair), it stays on by default. Gulf and Lebanon are the current members; prime Lagos,
Mumbai, Moscow and the like go through the *same written test* as they arise — so the answer to "what
about region X?" is "it goes through the rule", not a fresh debate each time. The location CSVs
(`hnw_areas.csv`, `intl_hnwi_postcodes.csv`) are **audited against this rule periodically**, and any
newly-added district must be classified by it.

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
`origin_adjacent_district.py`, `gcc_billing.py`, `geo_confirmation.py`. Keep
[dpia-lia-support.md](dpia-lia-support.md) §6 in step.
