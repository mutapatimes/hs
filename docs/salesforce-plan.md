# Plan (not built): Salesforce integration

**Status: parked.** Do not build speculatively. The trigger is a **named luxury house that runs on
Salesforce and wants the Halia grade in their CRM**. This doc is the ready-to-execute scope for when
that appears, so we can move fast without re-deciding the architecture.

## The key distinction (get this right)
Three different "Salesforce" things get conflated. They are not equally hard:

1. **Salesforce CRM as a sink — via the REST API (v1, the real first step).**
   Write the Halia grade into a client's Salesforce Contacts. This needs an **OAuth connected app +
   the standard REST/Bulk API** — *no* managed package, *no* AppExchange, *no* security review. It is
   architecturally the **same shape as the HubSpot sink**: upsert Contacts by email, write custom
   fields. Python-native, lives in Halia, buildable in ~the same effort as HubSpot. **This is v1.**

2. **Managed package + AppExchange listing (v2, distribution only).**
   Apex/SFDX + the ~6-week security review + $2,700 fee (paid listings only; free listings skip it).
   This is *only* needed to self-serve-distribute to many orgs or get a public listing. A **managed
   package can be installed privately into one client's org without the public review** — but it is
   still Apex, a different toolchain from Halia's Python. Do this only once there's repeatable demand.

3. **Salesforce Commerce Cloud (SFCC) as an order *source* (separate, heavy, later).**
   Demandware heritage, cartridge/SCAPI model — a different platform wearing a similar name. This is
   the enterprise-sales-gated, partner-mediated lift. Not part of v1 or v2. Defer until a client
   specifically needs Halia to read orders *from* SFCC at source (and even then, prefer landing the
   grade in their CRM first).

**Takeaway:** "put the Halia grade into their Salesforce" = item 1 = a Python REST sink, weeks, no
review. Everything heavy (Apex, AppExchange, SFCC) is a later, optional distribution/source concern.

## v1 scope — Salesforce REST sink (mirror the HubSpot adapter)
When triggered, build this and nothing more:
- **Auth:** a Salesforce **OAuth connected app** (client id/secret), per-tenant **refresh token** +
  **instance URL** (unlike HubSpot's single pasted token — SF is OAuth, so onboarding stores the
  refresh token and mints access tokens). Store encrypted, mirroring `save_hubspot`/`get_hubspot`.
- **Sink** `halia/adapters/salesforce_sink.py` (mirror `hubspot_sink.py`):
  - `ensure_fields()` — create custom Contact fields `Halia_Grade__c`, `Halia_Score__c`,
    `Halia_Tier__c`, `Halia_VIC__c`, `Halia_Signals__c`, `Halia_Reasons__c`, `Halia_Scored_At__c`
    (via the Tooling/Metadata API, or documented one-time manual setup for v1 to avoid Metadata-API
    complexity).
  - `push_one/push_many` — upsert Contacts by email via `PATCH
    /services/data/vXX.0/sobjects/Contact/Email/{email}` or the Composite/Bulk API for batches.
  - Injectable transport (no network in tests), exactly like the HubSpot/Mailchimp sinks.
- **Routes** `halia/api/salesforce_integration.py` (mirror `hubspot_integration.py`): status /
  connect (OAuth start + callback, or paste refresh token for MVP) / push / disconnect. `require_shop`.
- **Store:** `salesforce` table (`shop, refresh_token(enc), instance_url, connected_at`) + save/get/
  delete + add to `delete_shop`.
- **Dashboard:** a Salesforce connect card next to Mailchimp/HubSpot/Klaviyo.
- **Tests:** `tests/test_salesforce.py` — sink upsert with a fake transport + the routes, mirroring
  `tests/test_hubspot.py`.

This reuses everything already built for HubSpot; the only genuinely new part is OAuth token exchange.

## v2 scope — managed package + AppExchange (only when repeatable demand)
Build in **Apex/SFDX** (VS Code + Salesforce extensions, Partner Business Org). Not Halia's Python.
Sequence (from ISV field reports):
- Sign up as a **pre-contract ISV**, get a Partner Business Org, build + package in VS Code.
- **List free first to validate demand**, then switch to paid (pays back the $2,700 review fee).
- **Private managed-package install** to the first named client is possible *without* the full public
  review — use that to land the first whale before committing to the public listing.
- **Security-review gotchas (bake in from line 1 — the review "stops at the first fail"):**
  small surface area; **Named/External Credentials + OAuth** (no hardcoded keys); **bulkify**
  everything; **no guest-user endpoints**; document PII handling. Halia's **zero-retention** posture +
  existing DPIA/privacy docs are a direct asset here — sensitive-data apps get extra scrutiny and we
  already have the paperwork.

## Recommendation / triggers
- **Now:** ship BigCommerce + HubSpot (Python, near-term value). Salesforce stays parked.
- **Trigger for v1 (REST sink):** a named client that runs on Salesforce CRM and wants the grade in it.
- **Trigger for v2 (managed package/AppExchange):** repeatable inbound demand for self-serve install,
  or a strategic reason to be publicly listed.
- **Trigger for SFCC source:** a client that needs Halia to read orders from Commerce Cloud at source
  (and even then, land the grade in their CRM first).

## Out of scope until triggered
No connected app, no Apex, no SFCC, no code. This file is the plan; the build waits for a named
customer. Related: [[lantern-project]], `halia/adapters/hubspot_sink.py` (the pattern v1 mirrors).
