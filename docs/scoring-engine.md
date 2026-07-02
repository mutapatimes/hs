# The Halia Scoring Engine — reference

> How Halia turns a store's order history into a ranked list of **hidden VICs** (Very Important
> Clients a merchant is under-serving), and why every part works the way it does. High-level summary
> first, then the technical mechanics with the actual formulas, weights, and worked calculations.
> Authoritative code: [`scoring/combine.py`](../scoring/combine.py) (registry + maths),
> [`scoring/grading.py`](../scoring/grading.py) (grade), [`build_mvp.py`](../build_mvp.py) (latent
> value), [`scoring/calibrate.py`](../scoring/calibrate.py) (per-merchant tuning). Companion:
> [geography-signal-taxonomy.md](geography-signal-taxonomy.md), [dpia-lia-support.md](dpia-lia-support.md).

---

## 1. High level

**What it does.** Every customer in a store is read once, scored on ~35 independent **signals** of
wealth / status / intent, and ranked. The product surfaces the **hidden VIC**: a customer who fires
wealth signals yet spends *below* the merchant's VIP threshold — someone with the means to be a top
client whom the merchant currently treats like everyone else.

**The five ideas that define the engine:**
1. **Wealth facts, not origin.** The score is built from *what someone does and where they live* —
   spend, work, a prime address, a wealth structure — never *where they're from*. Nationality/origin
   signals are off by default behind a gate. (See §7 and the taxonomy doc.)
2. **Evidence, decayed by correlation.** Many signals restate the *same* underlying fact (three
   "this person is in Monaco" tells are one piece of evidence, not three). Correlated signals get
   **diminishing returns**; independent evidence is rewarded. (§4.2)
3. **Never a sole basis.** Weak/broad signals (a name match against millions, a corroborating phone
   agreement) can *add* confidence but can never flag a customer **alone**. (§4.3)
4. **Upward-only, human-in-the-loop.** A high score only ever routes a customer toward *more*
   attention (a coffee, a preview invite) via an associate prompt — never denies anyone anything.
5. **Zero-retention.** Customers are scored in memory and discarded; nothing about them is persisted.
   The engine is pure: records in → `ScoreResult`s out.

**The pipeline in one line:**

```
records → normalize → run every in-scope signal → weight each → decay within correlation groups
        → sum → apply gates (supporting / origin) → raw score → hidden-VIC flag → grade + latent value
```

---

## 2. The pipeline (technical)

Entry point is [`scoring.combine.score_customers`](../scoring/combine.py); the facade
[`HaliaEngine`](../halia/engine.py) wraps it so every surface (dashboard, POS, webhook) scores
identically.

| Stage | Function | Output |
|---|---|---|
| Aggregate orders → one row per customer | `scoring/shopify.py:orders_to_customers` | a DataFrame |
| Run every in-scope signal | `run_all_signals` → each `flag_*` | boolean flag (+ reason) columns |
| Score with weights + group decay | `score_customers` | `signal_score`, `signal_count` |
| Build the human "why" | `build_reasons` | `reasons` string |
| Flag hidden VICs | `score_customers` | `hidden_vic` boolean |
| Grade + gesture | `scoring/grading.py` | 0–100, tier A*/A/B/C, associate prompt |
| Estimate upside | `build_mvp.py:_latent` | latent annual value (£) |

Signals are registered once in the `SIGNALS` list as `(key, label, apply_fn, flag_col, reason_fn)`.
`active_signals(include_origin)` filters that list by two exclusion sets (§7). The whole customer base
goes through as one vectorised pass.

---

## 3. The signal catalogue

Each signal adds a boolean column and a factual reason. Weights live in `SIGNAL_WEIGHTS`; a weight of
**1** means "flag it, but rank it low" (a corroborator), **3** is a strong standalone tell. Some
signals override their base weight per-row by *type* (below).

**Location / address (group `geo`)** — where someone lives is a wealth fact:
`hnwi_postcode` (3), `us_hnwi_zip` (3), `intl_postcode` (3), `hnw_area` (3), `prime_residence` (3),
`property_value` (2 base), `wealth_jurisdiction` (2). All on by default. `property_value` still
grades by the area's median sale price *internally* (it sets the tier below) but is **displayed
non-intrusively** — label "Prime area", area name only, **no money figure** — showing a merchant an
estimated property value for a customer reads as surveillance.

**Structure** — routed through a wealth vehicle (origin-neutral): `wealth_structure` (3, standalone).

**Work / email (groups `email`, standalone)**: `work_email` (3), `domain_keyword` (2 base),
`custom_email` (1), `premium_email` (2), `elite_alumni` (2), `company_keyword` (2), `wealth_office` (2).

**Service / behaviour**: `hotel_concierge` (3), `delivery_venue` (3 base), `styling_service` (3),
`assistant_order` (2), `fashion_stylist` (2), `stylist_directory` (1), `honorific` (2),
`post_nominal` (2), `premium_card` (3), `ip_location` (1).

**Name-based (group `name`, correlated)**: `rich_list` (1), `companies_house` (1), `heritage_surname`
(1), `name_structure` (1), `nobiliary_particle` (1).

**Household linkage**: `shared_phone` (2), `landline` (1).

**Corroboration**: `geo_confirmation` (1) — phone/email jurisdiction *agreeing* with a high-value
address (§7).

**Gated by default** (origin proxies — off unless a tenant opts in with a lawful basis):
`gcc_billing` (2), `origin_adjacent_district` (2), `phone_country` (1), `phone_mismatch` (2),
`foreign_currency` (1), `nobiliary_particle`, `name_structure`, `heritage_surname`.

**Parked** (`CORE_DATA_ONLY=True` — transaction attributes we deliberately don't score):
`card_brand`, `foreign_currency`.

### Per-type weight overrides
Some signals grade their own strength per row and override the base weight:

| Signal | Type column drives | Weights |
|---|---|---|
| `property_value` | area value tier | `ultra`=4, `prime`=3, `high`=2 |
| `delivery_venue` | venue type | `private_jet_fbo`=5, `marina`=5, else base 3 |
| `domain_keyword` | finance tier | `elite`=3 (PE/hedge/family office/trust/chambers/yacht), `general`=2 |

---

## 4. The scoring maths

### 4.1 Per-signal contribution
For customer *i* and signal *k* that fired, the base contribution is `weight[k]` — or the type-override
weight where one applies (property tier, delivery type, domain tier).

### 4.2 Correlation groups + diminishing returns
Signals that encode the **same underlying fact** share a **group** (`SIGNAL_GROUP`): `geo` (all the
location tells), `name`, `email`, `payment`. Within a group, the fired weights are sorted **high→low**
and each successive one is discounted by `GROUP_DECAY ** rank` where **`GROUP_DECAY = 0.5`**:

```
group_score = Σ_r  weight_sorted[r] · 0.5^r          (r = 0,1,2,… within the group)
raw_score   = Σ_groups group_score                   (different groups add in full)
```

The strongest tell in a group counts fully; a second counts half; a third a quarter; and so on.
**Different groups add fully** — independent evidence (a prime address *and* a work email *and* a
name match) is rewarded; three restatements of "lives in Monaco" are not.

**Worked example.** A customer fires three `geo` signals — `hnwi_postcode` (3), `wealth_jurisdiction`
(2), `geo_confirmation` (1) — and one `email` signal, `work_email` (3):

```
geo   : sort [3, 2, 1] · [0.5^0, 0.5^1, 0.5^2] = 3·1 + 2·0.5 + 1·0.25 = 4.25
email : sort [3]       · [1]                    = 3.00
raw_score = 4.25 + 3.00 = 7.25
```

Signals with **no group** (e.g. `work_email`, `wealth_structure`, `hotel_concierge`) each stand alone
and add their full weight. `signal_count` is the raw number of signals that fired (before decay).

Implementation: [`score_customers`](../scoring/combine.py) builds a per-group matrix, `np.sort`
descending, multiplies by `0.5 ** np.arange(width)`, sums.

### 4.3 The supporting-signal gate ("never a sole basis")
`SUPPORTING_SIGNALS` = `{name_structure, nobiliary_particle, assistant_order, stylist_directory,
landline, custom_email, companies_house, geo_confirmation, rich_list, fashion_stylist, post_nominal}`.
A supporting signal is **zeroed unless at least one non-supporting ("core") signal also fired** for
that customer. This now includes a **name-match bright line**: no name-only match (`rich_list`,
`fashion_stylist`, `companies_house`, `post_nominal`) ever surfaces a customer *alone* — a namesake
collision must be corroborated by a non-name signal, the same logic applied to origin:

```
has_core = (count of fired non-supporting signals) > 0
for each supporting signal: fired = fired AND has_core     # and its reason is suppressed too
```

Rationale: a name matching one of millions of Companies-House PSCs, or a phone merely *agreeing* with
an address, is real corroboration but far too broad to surface someone on its own. `geo_confirmation`
additionally can't fire at all unless a wealth-geo signal fired (it reads those flags — it runs
**last** in `SIGNALS` for exactly this reason), so it is doubly precondition-gated.

### 4.4 The origin gate (`include_origin`)
`active_signals(include_origin=False)` (the default) drops `ORIGIN_PROXY_SIGNALS` entirely — they never
apply, score, or appear in `reasons`. A tenant with a documented lawful basis is scored with
`include_origin=True`. (§7.)

### 4.5 The hidden-VIC flag
```
hidden_vic = (signal_count > 0) AND (Spent < VIC_SPEND_THRESHOLD)      # threshold default £5,000
```
Someone already spending above the threshold is a *known* top client, not hidden. The threshold is
per-merchant (Settings). `top_hidden_vics` returns the hidden set sorted by score, then spend.

---

## 5. Grade & latent value

### 5.1 Raw → 0–100 → tier ([`scoring/grading.py`](../scoring/grading.py))
Evidence is **not linear** — the gap between one weak tell (raw 1) and real convergent evidence
(raw 3) is huge; the gap between raw 6 and raw 8 is marginal. So the raw score is mapped through a
**logistic**, which compresses the top (a genuine 90+ is earned, **99 is rare**), spreads the middle
where discrimination matters, and makes `score100` behave like a **confidence**. **Still
provisional/display — not a fitted model.**

```
score100 = min(99, round( 100 / (1 + e^(-0.8·(raw − 3.5))) ))
tier: A* (A1) if ≥77 · A if ≥50 · B if ≥20 · C otherwise
```

The centre (3.5) and cuts are tuned so the tier boundaries land at the **same raw scores as the old
linear mapping** (A\* raw≥5.0, A raw≥3.5, B raw≥1.75) — grades don't shift, only the number is
honest. A zero-signal customer now reads **~6, not 50**. Each tier carries a discreet associate
`GESTURE` (staff-only) — "offer a coffee and mention the private preview", etc.

### 5.1a Confidence — breadth vs strength
`score100` says how **strong** the evidence is; **`signal_confidence`** says how much **independent**
evidence supports it — the number of *distinct groups* that fired (counting core, non-supporting
signals; an ungrouped signal is its own group). A one-group A\* ("strong signal, **single source**")
is a very different object from a four-group A\* ("strong signal, **corroborated**"). It costs nothing
extra to compute (the group structure already exists) and turns the correlation-decay maths into a
user-facing trust cue on the associate's screen. Surfaced on `ScoreResult.confidence` /
`.confidence_label`.

### 5.2 Latent value ([`build_mvp.py:_latent`](../build_mvp.py))
The projected annual value if this client is nurtured into a top client. **Two modes:**

**(a) Merchant benchmarks supplied** (their AOV, most orders from one client, highest-lifetime client):
```
target = max(highest_lifetime, AOV × max_orders)
latent = spend + (target − spend) · (score100 / 100)
latent = min(latent, target, max(spend, store_aov) · 12)    # spend-multiple guardrail, then round £100
```
The **spend-multiple cap** is the credibility guardrail: we never project more than ~**12× a client's
own current value**, nor above the merchant's best-ever client. Without it a £1,200 customer scored 97
projects to ~£94k (99% of your best client ever) — the fastest way to lose a clienteling director's
trust in month two. *Example:* spend £1,200, score 97, highest_lt £95,000 → capped at `1,200·12 =`
**£14,400**, not £92k.

**(b) Fallback heuristic** (no benchmarks) — research-anchored, not a forecast:
```
base_aov = max(client_aov, store_aov)
latent   = base_aov · AOV_uplift[tier] · target_orders[tier]      # capped £100,000
```
with `target_orders` = A\*6 / A5 / B4 / C3 per year and `AOV_uplift` = A\*2.0 / A1.8 / B1.5 / C1.3
(loyal luxury clients buy ~4–6×/yr; clienteling lifts basket ~1.3–2×).

---

## 6. Per-merchant calibration ([`scoring/calibrate.py`](../scoring/calibrate.py))
Weights are sensible constants, but *which* signals predict spend differs per merchant. Calibration
measures each signal's **spend lift** on a merchant's own scored data and re-tunes:

```
lift[k]      = mean_spend(customers who fired k) / mean_spend(all customers)
multiplier   = clip(lift[k], 0.8, 1.25)                    # TIGHT: nudge ±25%, don't swing
new_weight[k]= max(1, round(base_weight[k] · multiplier))  # only if ≥ MIN_FIRED (25) fired k
```

Signals with too few firings keep their base weight; a signal is never zeroed. Adopted via
`HaliaEngine(weights=…)` / the `/v1/calibrate` endpoints, **preview-first, not auto-applied**.

> **Directional-bias warning (the important caveat).** Spend-lift calibration is *biased against
> Halia's own thesis.* The product finds people whose signals fire *despite* low spend, so a signal
> that is brilliant at that (`wealth_structure`) shows **weak** spend lift precisely because its best
> catches haven't converted yet — and naïve calibration would down-weight it toward the signals that
> merely track existing spend, i.e. **RFM through the back door**, erasing the differentiator. That is
> why v1 is deliberately timid (±25%). The real fix is calibrating on **conversion outcomes** (did
> surfaced VICs become top clients).

**The feedback loop (the bridge to outcome-based calibration).** The dashboard offers a one-tap
**"good call" / "not a fit"** on every surfaced VIC (`POST /v1/feedback`). Two things happen, both
zero-retention-preserving: Halia records an **aggregate per-signal tally** only — how often each
signal appeared on a good-call vs not-a-fit customer (`store.feedback_stats`, no customer id) — and
the per-customer verdict is written back as a tag in the merchant's **own** Shopify ("Halia: strong
lead" / "Halia: not a fit"). `GET /v1/feedback/stats` exposes each signal's feedback **precision**
(`fit / (fit+nofit)`). This produces labelled outcomes within weeks and is the training signal that
lets a future calibration re-weight on *precision*, not spend — fixing the directional bias above.

---

## 7. Lawful-by-default architecture
The single most important rule: **any signal derived from a national-origin-correlated input is an
origin proxy and stays OFF by default** (`ORIGIN_PROXY_SIGNALS`), on only when a tenant opts in with a
documented lawful basis. This holds even for beneficial sorting — UK GDPR Recital 71 is **effect-based**
and catches favourable treatment by protected characteristic too. Two disciplines back it:

- **Reason text is a bare, checkable fact** — "Phone jurisdiction (UAE) differs from billing country
  (UK)", never "likely international HNW". The explain-every-score audit trail records no sensitive
  inference.
- **The geography taxonomy** ([geography-signal-taxonomy.md](geography-signal-taxonomy.md)) enforces
  "does this sort by where someone is *from*, or by a *wealth fact*?" — Bucket 1 residence-is-wealth
  jurisdictions (`wealth_jurisdiction`, on), Bucket 2 structures (`wealth_structure`, on,
  origin-neutral), Bucket 3 origin-correlated Gulf (`gcc_billing` country + `origin_adjacent_district`,
  gated). **Origin fields corroborate, never originate:** phone dialling code and email ccTLD never
  start a score; their sole on-by-default use is `geo_confirmation` — *agreeing* with a high-value
  address nudges confidence up (a decayed +≤1 in the `geo` group), *disagreement does nothing*.

Everything is scored in RAM and discarded (zero-retention); only encrypted merchant secrets persist.

---

## 8. End-to-end worked example
A customer: billing **Monaco**, phone **+377…**, email **x@familyoffice.mc**, spend **£1,200**,
merchant benchmarks (AOV £1,800, max_orders 22, highest_lt £95,000), default (`include_origin=False`).

1. **Signals fire:** `wealth_jurisdiction` (Monaco, w2, geo), `hnw_area` (Monte Carlo, w3, geo),
   `domain_keyword` (familyoffice → elite, w3, email), `custom_email` (w1, email, *supporting*),
   `geo_confirmation` (phone +377 agrees with Monaco, w1, geo, *supporting*). `gcc_billing`/phone are
   gated off.
2. **Supporting gate:** core signals fired (wealth_jurisdiction, hnw_area, domain_keyword) → `custom_email`
   and `geo_confirmation` are allowed to count.
3. **Group decay:**
   - `geo`: sort [3 (hnw_area), 2 (wealth_jurisdiction), 1 (geo_confirmation)] → 3·1 + 2·0.5 + 1·0.25 = **4.25**
   - `email`: sort [3 (domain_keyword), 1 (custom_email)] → 3·1 + 1·0.5 = **3.5**
   - `raw_score = 7.75`
4. **Grade:** `min(99, round(100/(1+e^(-0.8·(7.75−3.5))))) = 97` → **A\*** (logistic — 99 stays rare).
5. **Confidence:** two distinct core groups fired (`geo`, `email`) → **corroborated (2 sources)**.
6. **Hidden VIC?** count = 5 > 0 and £1,200 < £5,000 → **yes**.
7. **Latent:** target = max(95,000, 1,800·22) = 95,000; raw `1,200 + 93,800·0.97 ≈ £92k`, then the
   spend-multiple cap `1,200·12 = ` **£14,400** wins → honest, not £92k.
8. **Output:** an A\* hidden VIC, corroborated by 2 independent sources, worth ~**£14,400** if
   nurtured; factual reasons; associate prompt "offer a coffee and mention the private preview".
   The payload also carries an **engine fingerprint** (`{version, hash}`) so this exact score is
   reproducible against the config that produced it.

---

## 9. Tuning & extension
- **Weights:** edit `SIGNAL_WEIGHTS` / the type-override tables in `combine.py`, or calibrate per merchant.
- **Correlation:** add a `SIGNAL_GROUP` entry to make a new signal share diminishing returns with its kin.
- **A new signal:** write `scoring/signals/<x>.py` with `flag_<x>(df)`→ flag+reason columns, add a
  `SIGNALS` tuple + weight (+ group). If origin-correlated → add to `ORIGIN_PROXY_SIGNALS`. If broad/weak
  → add to `SUPPORTING_SIGNALS`. Reason text must be a bare fact.
- **Knobs:** `VIC_SPEND_THRESHOLD` (hidden cutoff, per-merchant in Settings), `GROUP_DECAY` (correlation
  discount), `CORE_DATA_ONLY` (park transaction signals), `HALIA_CACHE_TTL` (in-memory window).

## 10. Why (rationale index)
- **Diminishing returns** stops a customer with five location fields out-scoring one with genuinely
  independent evidence — it makes the score track *distinct* reasons to believe, not field redundancy.
- **Supporting gate** keeps broad/portable signals (name-of-millions, an agreeing phone) as confidence,
  never as the reason someone is surfaced — critical for both precision and defensibility.
- **Origin gate + taxonomy** is the legal spine: one bright line ("all origin proxies off by default")
  is cheaper to defend than per-signal exceptions, and the corroboration rule extracts the residual
  value in phone/email without ever having to defend an origin-based sort.
- **Provisional grade / research-anchored latent** are honestly labelled as heuristics; calibration is
  the path to fitted numbers once a merchant has confirmed-VIC outcomes.
- **Zero-retention** means the strongest security posture is architectural: there is no customer
  database to breach.
