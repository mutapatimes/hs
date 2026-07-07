# DPIA support & Legitimate Interests Assessment (template)

> **Template only. Review with a solicitor before use.** This supports a Merchant's own Data
> Protection Impact Assessment and Legitimate Interests Assessment. It is not legal advice and
> has not been reviewed by a qualified data-protection lawyer. A solicitor must confirm the LIA
> balancing and the Article 22 "significant effect" judgment before a paying client goes live.

Profiling customers can be high-risk processing, so a DPIA is prudent (and may be required). The
Merchant is the Controller and owns the DPIA; this document gives Halia's side of the facts and a
worked LIA the Merchant can adapt.

## 1. What the processing is

Halia reads a Merchant's customers, scores each in memory on a set of wealth, work, and address
signals, and presents a ranked shortlist of likely high-value clients ("hidden VICs") to the
Merchant's team. A human at the Merchant decides whether to reach out. Nothing is retained (see
`docs/compliance.md`). The output **elevates** attention; it never withholds a product, price, or
service.

## 2. Legitimate Interests Assessment

### 2.1 Purpose test
The Merchant has a legitimate interest in understanding which of its existing customers are most
valuable, so it can offer a relevant, personal, human-led service (clienteling). This is a normal,
expected commercial activity in retail and hospitality.

### 2.2 Necessity test
Profiling on commercial history and address facts is a reasonable and proportionate way to find
likely high-value clients from data the Merchant already holds. The alternative (manual review of
every customer, or untargeted outreach to everyone) is less effective and arguably more intrusive
in aggregate. The Service is data-minimising: it reads only the fields its active signals need and
retains nothing.

### 2.3 Balancing test
Weighing the interest against customers' rights and freedoms:

| Factor | Assessment |
|---|---|
| Reasonable expectations | A customer of a premium brand can reasonably expect to be recognised as a good customer and offered a more personal service. |
| Nature of the data | Commercial and address facts, not special-category data. Origin proxies are off by default. |
| Effect on the individual | Benign and one-directional: at most, more personal attention. No price, gate, or refusal is driven by the score. |
| Intrusiveness | Low: no new data is collected, nothing is retained, a human mediates every action. |
| Safeguards | Human-in-the-loop, zero-retention, right to object honoured, explainable per-score reasons, origin proxies off by default. |

**Provisional conclusion:** legitimate interests is an appropriate basis, provided the safeguards
above hold in practice and the Merchant honours objections. The Merchant's solicitor must confirm.

## 3. Disparate-impact assessment

The risk in any wealth-screening tool is that it sorts people by **national or ethnic origin**
rather than by wealth, which UK GDPR (Recital 71) and the Equality Act catch by **effect**, not by
label. Renaming a nationality signal does not cure it.

Halia's mitigation is structural: the signals that sort by national / ethnic / name origin are
**off by default** (`scoring.combine.ORIGIN_PROXY_SIGNALS`): billing-country-as-origin (GCC),
origin-adjacent prime districts, phone dialling code, phone/address mismatch, name structure, name origin,
heritage surname, and foreign currency. By default the score is built from **wealth facts** (spend,
order history), **work facts** (employer / professional email and company tells), and **specific
address / structure facts**.

### 3.1 Why the address & structure signals stay on (the geography taxonomy)
The active geography signals match a **property or wealth fact about a place or structure**, not a
sort by country-of-origin — the test being "does this signal sort by where someone is *from*, or by
a *wealth fact*?" A specific ultra-prime address (`prime_residence`, `intl_postcode`, `hnw_area`), a
**high-value residential jurisdiction** where residence itself is a wealth fact (`wealth_jurisdiction`
— Monaco, Jersey, Guernsey and peers, on internationally-mixed-resident grounds), and a
**wealth-management structure** (`wealth_structure` — a trust company, family office, registered
agent; origin-neutral) all pass the test and stay on. Country-of-origin proxies fail it and are off.
**Origin-adjacent prime districts** (`origin_adjacent_district` — Gulf, Lebanon) are a deliberate
middle case: arguable wealth-geography, but a district-level match whose flagged population skews to
one national origin in a UK book is gated with the origin proxies, by a written **general review
rule** (see the taxonomy doc). Fields that speak only to origin — phone
dialling code, email country-code TLD — never originate a score and may only *corroborate* an
address. The full taxonomy, with the property-market inclusion criteria, is
[geography-signal-taxonomy.md](geography-signal-taxonomy.md). The operator may re-enable origin
proxies for a single tenant only after that Merchant documents a lawful basis.

### 3.2 Why the effect is non-discriminatory
With origin proxies off, the model sorts on wealth and address facts. The effect on a customer is
to receive more personal attention, never to be denied anything. The combination of (a) wealth-
fact inputs, (b) a benign "elevate, never withhold" effect, and (c) a human deciding every
outreach keeps the processing away from prohibited discrimination and outside Article 22.

## 4. Article 22 (automated decisions)

Article 22 bites on a decision **based solely on automated processing** that produces a **legal or
similarly significant effect**. Halia is designed to fall outside it on **both** limbs:

- **Not solely automated:** a human at the Merchant reviews the shortlist and decides.
- **No significant effect:** the output is a suggestion to offer *more* attention; it does not set
  a price, gate an offer, or refuse a service.

If a Merchant ever wires a score directly into a price, an eligibility gate, or a refusal, both
limbs change and the Merchant must reassess (likely needing explicit consent and Article 22
safeguards). Keep the human and the "elevate-only" effect real.

## 5. Data minimisation

- Only the fields the active signals read are processed.
- Customer data is processed in memory and retained nowhere.
- Origin proxies, the most sensitive inputs, are excluded by default.
- Output is explainable: each score carries the specific reasons that produced it, so a customer
  query can be answered honestly.

## 6. Signal catalogue: wealth facts (on) vs origin proxies (off by default)

**On by default (wealth / work / specific-address / structure facts):**
work email, HNWI postcode, US HNWI ZIP, international prime postcode, prime neighbourhood (HNW
area, non-Gulf), high-value residential jurisdiction (Monaco/Jersey/… — was "tax haven"),
wealth-management structure (trust company / family office / registered agent), area property
value (median sale price of the postcode district, from HM Land Registry open data), hotel
concierge, delivery venue, styling service, prime residence, premium card, honorific, company
keyword, premium email, wealth office, elite alumni, assistant order, post-nominal, fashion
stylist, stylist directory, IP location, domain keyword, custom email, rich-list surname,
Companies House control, Charity Commission trusteeship.

*Companies House control (rebuilt 2026-07 for precision).* Sourced from two free Companies House
bulk products under the Open Government Licence v3.0: the People with Significant Control (PSC)
snapshot joined **offline** to Basic Company Data (there is no live per-name API call at scoring
time). It keeps only a high-precision subset: a person who owns or controls **75%+** of an **active** UK
company that is either **named after them** (their surname is a word in the company name, a
two-factor match, plus a common-surname dampener and removal of dormant / micro-entity shells —
except an eponymous wealth-industry micro-entity, the classic quiet family investment vehicle,
kept at the lowest tier) OR is **both large and in a wealth industry** (a strong-enough wealth
fact to stand without the name match). An **ambiguity gate** then drops any full name carried by
more than one distinct person on the register (compared by the public birth month/year): an
ambiguous name can never be a certain match, so it is excluded entirely rather than risked. Kept owners are tiered by company size (Full/Medium/Group
accounts, or a PLC) and by a wealth-industry SIC code (real estate, investment/holding,
architecture, design, art), which lifts the weight (2 → 4 → 6) and is named in the human reason
("controls Marandi Investments Ltd, a real estate company"). It is a factual entry on a statutory
**public** register, not inferred from any protected characteristic, and remains
**corroboration-only** in the combiner (never a sole basis, same name bright line as
`charity_trustee`). Controller names are personal data, so the committed seed ships inert and real
individuals only ever enter the git-ignored local table on the operator's own machine.

*Charity Commission trusteeship (added 2026-07).* Sourced from the free daily Charity Commission
for England & Wales register extract (Open Government Licence v3.0). It flags only the high-precision
**eponymous-foundation** subset: a person whose own surname is in their charity's name and who is a
listed trustee of it (a two-factor match applied when the reference table is built, plus a
common-surname dampener). Legal shape is identical to Companies House control: a factual entry on a
statutory **public** register, not inferred from any protected characteristic. It is a *new
processing purpose*, so it belongs in this LIA and feeds the Article 22 analysis, and it is
**corroboration-only** in the combiner (never a sole basis). Trustee names are personal data, so the
seed ships inert and real individuals only ever enter the table on the operator's own machine.

**Off by default (origin proxies; enable per-tenant only with a documented lawful basis):**
billing country as an origin proxy (GCC), origin-adjacent prime district, phone dialling-code country,
phone/address mismatch, foreign currency, nobiliary particle (de / von), name structure, heritage
surname. (Fields that speak only to origin — phone dialling code, email ccTLD — never originate a
score; the sole on-by-default use is agreement-as-confidence corroborating an address. See
[geography-signal-taxonomy.md](geography-signal-taxonomy.md).)

The authoritative list lives in `scoring/combine.py` (`SIGNAL_WEIGHTS` and
`ORIGIN_PROXY_SIGNALS`); this catalogue should be kept in step with it.

## 7. Children

If a material share of the Merchant's customers are under 18, the Children's Code (Age Appropriate
Design Code) expects a higher standard, and profiling children for commercial targeting may not be
appropriate at all. Ask younger-skewing Merchants directly. Where under-18s feature materially,
take specific advice before enabling the Service for that tenant.

## 8. Residual risk and sign-off

With origin proxies off, a human in the loop, an elevate-only effect, and zero retention, the
residual risk is low. The outstanding action is **legal sign-off**: a data-protection solicitor
must confirm the LIA balancing (§2.3) and the Article 22 judgment (§4) for the specific Merchant
and market before paying clients go live. This document makes the processing defensible and
clean-by-default; it does not replace that sign-off.
