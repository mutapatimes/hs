# Shopify ingestion & aggregation spec

The contract between the Shopify data pull and the scoring engine. Everything in
`scoring/signals/*` reads a flat, **one-row-per-customer** DataFrame with fixed
column names. Shopify gives us **one object per order**, plus a customer object.
This document defines exactly how we get from one to the other.

Status legend: ✅ built today · 🔶 partial / needs work · ❌ not built yet

---

## 1. Where this sits

```
Shopify Admin API ──fetch──▶ raw order/customer JSON ──flatten+aggregate──▶ per-customer DataFrame ──▶ score_customers()
        ❌ (fetch layer)              🔶 scoring/shopify.py (REST shapes)            ✅ unchanged
```

- **Fetch layer** — OAuth, pagination, webhooks, bulk operations. **Does not exist yet.** Phase 1's main build.
- **Flatten + aggregate** — `scoring/shopify.py`. Exists and is tested, but only covers `Spent`/`Items` + latest address. Missing the behavioural features the mockup sells.
- **Scorer** — `score_customers()` and the 12 signals. **Unchanged** by this work, as long as ingestion produces the columns below.

---

## 2. Scopes the custom app must request

| Scope | Feeds |
|---|---|
| `read_customers` | email, phone, name, tags, `amount_spent`, `number_of_orders`, default address |
| `read_orders` | per-order billing/shipping addresses, discounts, timestamps, line items |

`read_orders` only returns the last 60 days unless the app also has
`read_all_orders` (requires a one-line scope grant in a custom app — needed for
lifetime aggregation). Request both.

`browser_ip` (IP signal) and card BIN are the two sensitive fields — see §7.

---

## 3. The input contract the scorer requires (do not break these)

Every signal's `flag_*` function reads one of these columns. This is the
authoritative list, traced from the signal source.

| Column | Read by | Shopify source | Aggregation |
|---|---|---|---|
| `EMAIL_ADDR` | work_email | `customer.email` | latest non-null |
| `Name` | honorific, rich_list | `customer.first_name + last_name` | latest non-null |
| `PHONE` | phone_country | `customer.phone` → `order.phone` → `billing.phone` | latest non-null |
| `COMPANY_NAME` | company_keyword | `billing_address.company` | latest non-null |
| `LATEST_BILLING_ADDRESS1` | prime_residence | `billing_address.address1` | from most-recent order |
| `LATEST_BILLING_ADDRESS2` | prime_residence | `billing_address.address2` | " |
| `LATEST_BILLING_ADDRESS3` | prime_residence | `billing_address.city` | " |
| `LATEST_BILLING_ADDRESS4` | gcc_billing, wealth_jurisdiction, prime_residence | `billing_address.country` | " |
| `LATEST_BILLING_ZIP` | hnwi_postcode, prime_residence | `billing_address.zip` | " |
| `LATEST_SHIPPING_ADDRESS1-4` | delivery_venue | `shipping_address.address1/2/city/country` | from most-recent order |
| `LATEST_SHIPPING_ZIP` | delivery_venue | `shipping_address.zip` | " |
| `SEGMENT` | **combine** (hidden_vic gate) | derived from `customer.tags` | see §6 |
| `Spent` | combine (ranking), main display | Σ `order.total_price` *or* `customer.amount_spent` | sum |
| `credit_card_bin` / `credit_card_company` | premium_card | order transactions | dormant — §7 |
| `browser_ip` → `ip_city/region/country` | ip_location | `order.client_details.browser_ip` | dormant — §7 |

**Address packing convention** (important): the engine expects `ADDRESS4` to hold
the **country**, with city in `ADDRESS3`. This is inherited from the original CRM
export and `scoring/shopify.py` already maps it this way. Country matchers
(gcc, wealth_jurisdiction) read the country *name* and match against an alias list — so map
`billing_address.country` (the name, e.g. "United Arab Emirates"), **not**
`country_code`. See §8 for the optional country-code upgrade.

---

## 4. What `scoring/shopify.py` does today ✅

`orders_to_customers(orders)`:
1. `flatten_order` maps each REST order → the engine columns above.
2. Groups by `CUST_ID` (= customer id, falling back to email).
3. `Spent`/`Items` summed; `tags` unioned; every `LATEST_*` column takes the
   **last non-null** value after sorting by `created_at` → i.e. the most recent
   order that actually had that field. (Billing and shipping can therefore come
   from different orders — this is fine and slightly more robust.)
4. `SEGMENT` = `"VIP"` if tags intersect `{vip, vic}`, else `"Final Client"`.

Tested in `tests/test_shopify.py` against the real Shopify order resource shape.

---

## 5. Gaps to close 🔶❌

### 5a. Behavioural feature layer ✅ — built in `orders_to_customers`

The mockup's headline signals ("single full-price order then silence", "never
buys in a sale window", "three delivery addresses", "order timing tracks the
match calendar") **do not exist** — all 12 current signals are reference-list
lookups. Shopify order history makes them cheap. Add these per-customer columns
in the aggregation step:

| New column | Definition | Shopify source | Enables |
|---|---|---|---|
| `orders_count` | count of orders | `customer.number_of_orders` | AOV, single-order |
| `first_order_at` / `last_order_at` | min/max order date | `order.created_at` | recency, tenure |
| `days_since_last_order` | today − last_order_at | derived | "tested us once then silence" |
| `tenure_days` | last − first | derived | loyalty |
| `avg_order_value` | `Spent / orders_count` | derived | full-price-buyer profile |
| `full_price_ratio` | share of orders with **no** discount | `order.total_discounts > 0` per order | "never buys in a sale window" |
| `distinct_shipping_addresses` | unique normalised shipping addrs | dedupe `shipping_address` across orders | multi-property |
| `order_timestamps` | list of `created_at` | per order | cadence signals (match calendar) |

None of these require new scopes. They are the highest-leverage addition because
they unlock the signals the product is actually demoed on.

**Built** as of this iteration: `orders_count`, `first/last_order_at`,
`days_since_last_order`, `tenure_days`, `avg_order_value`, `full_price_ratio`,
`distinct_shipping_addresses`, `single_order_then_silent` — all produced per
customer by `orders_to_customers(today=…)` and tested. **Still to do:** turn
these *features* into scoring *signals* (new `scoring/signals/` modules + weights)
so they contribute to `signal_score` like the reference-list signals do.

### 5b. All-orders address scan 🔶

`delivery_venue` / `prime_residence` currently see only the **latest** address,
so "shipped to a hotel once across 30 orders" is missed. Add an aggregated
`SHIPPING_VENUE_SCAN` column = every distinct shipping address line concatenated
across the customer's order history, and call the signal with
`address_cols=["SHIPPING_VENUE_SCAN"]` (the function already accepts custom
columns). Same for billing → `BILLING_VENUE_SCAN`. Latest-only stays the default
for the flat contract; the scan column is a strict superset for these two
signals.

### 5c. Fetch layer ❌

`shopify.py` takes `orders: list[dict]` — someone has to produce that list.
Needed: OAuth install, cursor pagination (or a Bulk Operation for the initial
backfill of all orders), and `orders/create` + `customers/update` webhooks to
keep scores "live" (the mockup says "refreshed 6m ago"). REST shapes are what
`shopify.py` expects today; see §8 on GraphQL.

---

## 6. The "already a VIC" gate — spend threshold, not a tag (RESOLVED)

The original `SEGMENT ∈ {VIP, VIC}` gate came from a **manual tag maintained in
Power BI** on the CRM export — it is *not* a Shopify field and won't exist in
production. So the hidden-vs-known split moves to a **configurable spend
threshold**, which is exactly what the mockup already shows ("avg current spend
£1,840 — *below your VIC threshold*").

New definition:

> **hidden VIC** = at least one signal fired **AND** `Spent < VIC_THRESHOLD`.

Implications:
- `combine.py` changes from a tag check to a threshold check (one line). The
  `SEGMENT` column and `ALREADY_VIC_SEGMENTS` become legacy — keep ingesting
  `SEGMENT` for display, but it no longer gates `hidden_vic`.
- `VIC_THRESHOLD` is the one merchant input that matters here — set it to the
  store's existing VIC spend cutoff. Until set, pick a sane default and surface
  it in the UI ("threshold: £X").
- The Power BI tag is still useful **offline** as ground truth for validation:
  do our threshold + signals re-surface the people they hand-tagged as VICs?
  That's the back-test, not the gate.

---

## 7. Stays dormant (do not build on these)

- **`premium_card` / card BIN** — `_card_from_transactions` reads
  `payment_details.credit_card_bin`. This is Shopify-Payments-only, classed as
  financial/sensitive, and progressively restricted by API version. Keep the
  code dormant (it already no-ops when the column is absent). Verify current
  availability before promising it.
- **`ip_location`** — `client_details.browser_ip` is the most sensitive protected
  field and IP is noisy (VPN/office). Weighted lowest already. Keep optional;
  needs a MaxMind GeoLite2 DB to resolve (`add_ip_geolocation`).

---

## 8. Forward-looking notes

- **GraphQL fetch (DECIDED).** We fetch via the GraphQL Admin API and transform
  each order node into the REST-shaped dict `flatten_order` already expects, so
  the tested core (`shopify.py` → signals) stays untouched. The adapter is the
  only new surface: `scoring/shopify_graphql.py` holds the query + the
  node→REST transform. The query is customer-centric (`customers → orders`),
  which also gives `amountSpent` / `numberOfOrders` for the §5a behavioural
  features for free.
- **Country-code upgrade (optional).** Matchers currently key on country *name*.
  Adding `billing_address.country_code` (ISO `AE`, `SA`, …) as extra aliases in
  `gcc_countries.csv` / `wealth_jurisdictions.csv` would make those two signals immune to
  spelling variation. Pure reference-data change, no code edit.
- **Spend source.** Summing `order.total_price` (today) and `customer.amount_spent`
  should agree; prefer `amount_spent` when present — it's authoritative and saves
  fetching every order just for the total.

---

## 9. Phase 1 checklist (single merchant)

1. ❌ Custom app + OAuth, scopes `read_customers`, `read_orders`, `read_all_orders`.
2. ❌ Fetch layer: bulk backfill of orders → list of dicts (run `CUSTOMERS_QUERY`, page, adapt).
3. ✅ GraphQL→REST adapter (`scoring/shopify_graphql.py`).
4. ✅ §5a behavioural features in `orders_to_customers`. ❌ §5b all-orders scan columns.
5. ✅ Spend-threshold gate (`VIC_SPEND_THRESHOLD` in `combine.py`) — set the real cutoff with the merchant.
6. ❌ Turn behavioural features into scoring signals (new `signals/` modules + weights).
7. ⬜ Persist scored output (DB) — separate spec.
8. ✅ Existing xlsx export still works as the interim deliverable.
