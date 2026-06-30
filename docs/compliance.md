# Halia, data protection & compliance

Halia is **zero-retention** for customer data. We read a merchant's customers from Shopify,
score them **in memory**, show the result to the merchant (and optionally write the grade
back to Shopify or to the merchant's own Klaviyo), and then **discard them**. No customer
personal data is ever written to our database or disk, and Halia staff can never browse a
database of anyone's clients.

## Data flow

```
Shopify (merchant's store)
        │  read (TLS) with the merchant's offline token
        ▼
Halia server, score in RAM, hold for ≤5 min (RAM only), then gone
        │
        ├─▶ merchant's browser (the embedded dashboard)
        ├─▶ Shopify write-back (grade as a tag/metafield, in the merchant's store)
        └─▶ merchant's own Klaviyo (profiles/events, merchant-directed)
```

## What we persist (and what we never do)

| Data | Stored at rest? | Where / how |
|---|---|---|
| Customer names, emails, phones, addresses, order history | **No, never** | RAM only (`halia/cache.py`), evicted on TTL / restart / redact |
| Scores, grades, reasons | **No** | computed in memory, sent to the surface, discarded |
| Shopify **offline access token** (per shop) | Yes | Postgres, **encrypted** (Fernet, `halia/crypto.py`) |
| Klaviyo **API key** (per shop) | Yes | Postgres, **encrypted** |

Only two secrets are persisted, both encrypted, and both are deletable on demand. Earlier
versions cached PII in `scores`/`orders`/`dashboards` tables, those are **dropped on every
deploy** (`halia/store.py`), so upgrading purges any previously-stored customer data.

## Mandatory privacy webhooks (`halia/api/webhooks.py`)

All authenticated by HMAC-SHA256 of the raw body (app secret); an invalid HMAC returns **401**.
Configure one URL, `https://<app>/webhooks/shopify`, for all topics.

| Topic | What Halia does |
|---|---|
| `customers/data_request` | We hold no customer data → acknowledge (nothing to return). |
| `customers/redact` | Evict any in-RAM cache for the shop. |
| `shop/redact` | **Delete** the shop's token + Klaviyo key; evict cache. |
| `app/uninstalled` | Same cleanup. |

## Mapping to Shopify Protected Customer Data requirements

| Requirement | How Halia meets it |
|---|---|
| Data minimisation | Only the fields the signals read; nothing else; nothing retained. |
| Encryption in transit | TLS everywhere (Render HTTPS; Shopify/Klaviyo HTTPS). |
| Encryption at rest | Only secrets are stored, and they're Fernet-encrypted. |
| Retention limits | Customer data retention = **none** (RAM ≤5 min). |
| Right to erasure | Trivial, we store no customer data; redact webhooks wipe secrets. |
| Access control | Per-shop session-token auth; no PII database for staff to access. |

## Deploy / configuration checklist

1. **Render env:** set `HALIA_ENCRYPTION_KEY` (generate:
   `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`).
   `HALIA_CACHE_TTL` defaults to 300s.
2. **Dev Dashboard app → compliance webhooks:** point the three privacy topics at
   `https://<app>/webhooks/shopify` (HMAC handled).
3. **Dev Dashboard app → Protected Customer Data:** request access, give the data-use reasons
   (customer analytics / clienteling), and attest to the controls above.
4. **Privacy policy URL:** required for PCD, see `docs/privacy-policy-template.md`.

## Deferred (process, not code)
## Client compliance pack (templates, review with a solicitor before use)
- [`docs/dpa.md`](dpa.md) : Data Processing Agreement (Merchant = controller, Halia = processor).
  Closes the "DPA available on request" promise in `terms.html` / `security.html` / `faq.html`.
- [`docs/privacy-notice-profiling.md`](privacy-notice-profiling.md) : the "logic of the profiling"
  wording a Merchant pastes into its own customer privacy notice (UK GDPR Art 13/14).
- [`docs/dpia-lia-support.md`](dpia-lia-support.md) : DPIA support + Legitimate Interests
  Assessment, the disparate-impact analysis, and the wealth-fact vs origin-proxy signal split.

## Lawful-by-default profiling
Origin-proxy signals (nationality / name / ethnicity tells) are **off by default** for every
tenant (`scoring.combine.ORIGIN_PROXY_SIGNALS`); the score is built from wealth, work, and
specific-address facts. They re-enable only per-tenant, operator-controlled, after that Merchant
documents a lawful basis (`HALIA_ORIGIN_SIGNAL_SHOPS`). See `docs/dpia-lia-support.md` §3.

## Deferred (process, not code)
- A formal legal privacy policy (template provided); the DPA template above still needs solicitor
  sign-off before use with a paying client.
- A data-protection solicitor must confirm the LIA wording and the Article 22 "significant effect"
  judgment before paying clients go live.
- SOC 2 / penetration test (operational maturity, when selling up-market).
- "Never touches our servers at all" (client-side / Shopify-native scoring): a future rebuild.
