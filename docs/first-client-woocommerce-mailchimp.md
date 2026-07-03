# Runbook: going live with the first client (WooCommerce → Halia → Mailchimp)

The first client is on **WooCommerce + Mailchimp**, not Shopify/Klaviyo. The scoring engine in the
middle is identical; only the two ends change. This is the operator's checklist to take them live.

The whole pipeline is proven end-to-end (no network) by
`tests/test_first_client_woo_mailchimp.py` — run it any time to confirm the path still holds.

---

## 0. What you need before you start

**You (operator) supply once** — set on the hosting env (see the table at the bottom):

- `HALIA_APP_URL`, `SESSION`/DB config, and the **encryption key** (creds are stored encrypted).
- Email sender for alerts: `HALIA_BREVO_API_KEY` + `HALIA_EMAIL_FROM` (a verified sender), **or** SMTP.
- Web push (optional but recommended): `HALIA_VAPID_PRIVATE` + `HALIA_VAPID_PUBLIC`.

**The client supplies** (walk them through it, read-only both):

- **WooCommerce REST key** — WP admin → WooCommerce → Settings → Advanced → REST API → *Add key*,
  permission **Read**. Gives a **Consumer key** (`ck_…`) and **Consumer secret** (`cs_…`) + the store URL.
- **Mailchimp API key** — Account → Extras → API keys. And which **audience** to write to.

Nothing about their customers is ever stored: orders are pulled, scored in RAM, and forgotten
(only the encrypted store/API credentials are persisted).

---

## 1. Prove it on their data first (offline preview)

Before anything is connected in the product, generate the dashboard from a live read-only pull.
This is the fastest way to show value and to sanity-check their data shape.

```bash
WOO_STORE_URL=https://theirstore.co.uk \
WOO_CONSUMER_KEY=ck_xxx \
WOO_CONSUMER_SECRET=cs_xxx \
HALIA_WOO_MAX_PAGES=2 \        # small first pull; unset for the full history
python build_woo.py           # -> output/theirstore-co-uk.html
```

Open the HTML, confirm the hidden VICs look right. If the store is large, drop `HALIA_WOO_MAX_PAGES`
for the full run (default cap is 60 pages ≈ 6,000 most-recent orders).

## 2. Onboard them as a tenant (hosted app)

Send them to **`/connect`**. The wizard detects WooCommerce (`POST /v1/detect`), takes the store URL
+ `ck_`/`cs_`, creates the tenant, and stores the credentials encrypted
(`create_tenant(kind="woocommerce")` + `save_woocommerce`). First sign-in is by email magic link
(`/app/signin`). After connecting, their dashboard at **`/app`** does a live pull → score → RAM cache.

> Setting the VIC spend threshold: default is `HALIA_VIC_THRESHOLD` (£5,000). Per-tenant settings
> (threshold, AOV benchmarks, signal weights) come from `settings_for(shop)` and can be tuned later.

## 3. Connect Mailchimp

From the dashboard (or via API), connect the audience:

- `POST /v1/mailchimp/connect { api_key, list_id? }` — stores the key, lets them pick the audience,
  and **provisions the Halia merge fields** (`HGRADE`, `HSCORE`, `HTIER`, `HVIC`, `HSIGNALS`,
  `HREASONS`, `HSCOREDAT`) on that audience.
- `GET /v1/mailchimp/status` — confirms connected + which audience.

## 4. Push the hidden VICs

- `POST /v1/mailchimp/push { customer_ids? }` — with no body, upserts **all surfaced hidden VICs**;
  with `customer_ids`, just those. Each member is upserted by email with the Halia merge fields and
  tagged (`Halia A*`, `Halia Hidden VIC`, `Halia: <signal>` …) so the client can build segments and
  automations off them.
- `POST /v1/mailchimp/segment { customer_ids, name }` — optional: make a static segment from a
  selection in one step.

In Mailchimp, confirm the members carry the `HGRADE`/`HVIC` merge fields and the `Halia …` tags.

## 5. Real-time alerts (optional, recommended)

When a hidden VIC orders, Halia notifies the team — it does **not** email the customer.

- Order webhook → `score_order()` scores the single customer in memory and dispatches an alert.
- Web push: the team subscribes via `POST /v1/push/subscribe` (needs the VAPID keys set).
- Email alert: sent via Brevo/SMTP if configured.

The team then chooses whether to reach out, from templates (the flow shown on the solutions pages).

---

## Verification checklist

- [ ] `python -m pytest tests/test_first_client_woo_mailchimp.py -q` passes.
- [ ] `build_woo.py` produces a sensible dashboard from their store.
- [ ] Tenant shows in `/app`; a refresh re-pulls and re-scores.
- [ ] `GET /v1/mailchimp/status` → connected to the intended audience.
- [ ] After push: sample members in Mailchimp have `HGRADE`/`HVIC` set and `Halia …` tags.
- [ ] (If used) a test order fires a push/email alert to the team.

## Operator environment variables

| Variable | Purpose | Needed for |
|---|---|---|
| `HALIA_APP_URL` | Public base URL of the hosted app | Always |
| `HALIA_WOO_MAX_PAGES` | Cap on WooCommerce pull (default 60; `0` = no cap) | Large stores |
| `HALIA_VIC_THRESHOLD` | Default VIC spend threshold (£5,000) | Tuning |
| `HALIA_BREVO_API_KEY` + `HALIA_EMAIL_FROM` | Transactional email (alerts, magic-link sign-in) | Email alerts / sign-in |
| `HALIA_SMTP_HOST` / `_PORT` / `_USER` / `_PASS` / `_FROM` | SMTP alternative to Brevo | Email (if no Brevo) |
| `HALIA_VAPID_PRIVATE` + `HALIA_VAPID_PUBLIC` | Web-push keys | Push alerts |

The client's WooCommerce `ck_`/`cs_` and Mailchimp API key are entered through the product and stored
encrypted per tenant — they are **not** operator env vars.

Related: [[first-client-woocommerce-mailchimp]] memory, `build_woo.py`, `halia/api/mailchimp_integration.py`,
`halia/api/data.py` (`sync_woo` / `results_for`), `docs/shopify_ingestion_spec.md` (the Shopify analogue).
