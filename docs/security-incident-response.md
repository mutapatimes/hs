# Halia — Security Incident Response Policy

**Status: internal policy. Review annually. Have counsel confirm the breach-notification timings for
your jurisdictions before relying on this.**

_Last updated: 2026-08-09_

## Purpose

To detect, contain, and recover from security incidents affecting Halia and the merchant data it
processes, and to notify affected parties promptly. Halia is **zero-retention**: it processes customer
and order data to compute a score and keeps the score, not the customer records. This narrows the blast
radius of any incident to configuration, access tokens, and the small amount of tenant metadata Halia
stores.

## Scope

All Halia systems: the application backend, its database, hosting (Render), source control (GitHub),
the browser extension, and any connected third-party services (Stripe, email/Slack integrations).

## Roles

- **Incident lead:** Valentine Eluwasi (founder). Owns triage, decisions, and communications.
- **Deputy / escalation:** name a second contact before launch.
- Until the team grows, the incident lead holds all roles below and documents actions as they go.

## What counts as an incident

- Unauthorized access to the backend, database, or a merchant's Admin API token.
- Exposure of secrets (API keys, tokens, `.env`) in code, logs, or a third party.
- A merchant reports suspicious activity attributable to Halia.
- A compromised dependency or hosting account.
- Loss of availability that risks data integrity.

## Response steps

1. **Detect and record.** On any signal (alert, report, anomaly in access logs), open a dated incident
   note. Record time, what was seen, and who is handling it.
2. **Contain.** Rotate the affected credential immediately (Shopify app secret, per-tenant tokens,
   Stripe keys, hosting/GitHub access). Revoke sessions. If a tenant token is involved, rotate that
   tenant's extension token and, if needed, its Admin API access.
3. **Assess.** Determine what data was reachable. Because Halia does not retain customer records, most
   incidents touch tokens and tenant config, not customer PII. Note explicitly whether any personal
   data was actually accessible.
4. **Eradicate and recover.** Remove the cause (patch, revoke, redeploy from clean source). Restore
   service. Verify the access logs are clean afterwards.
5. **Notify.**
   - **Affected merchants:** without undue delay once an incident affecting their store or data is
     confirmed. Tell them what happened, what data was involved, and what you did.
   - **Regulators:** where a personal-data breach is likely to risk individuals' rights, notify the
     relevant supervisory authority within the legal window (under UK/EU GDPR, **72 hours** of becoming
     aware). Confirm the exact obligation with counsel.
   - **Shopify:** report incidents involving Shopify data through Shopify's Partner channels.
6. **Review.** Within one week, write a short post-incident note: root cause, what worked, and the one
   or two changes that prevent recurrence. Apply them.

## Prevention baseline (keep these true)

- 2FA on Shopify Partner, Render, GitHub, and the operator email.
- Secrets only in environment variables, never in the repo (`.gitignore` enforces this).
- Encryption in transit (HTTPS) and at rest (tokens/secrets encrypted; managed-Postgres backups
  encrypted).
- Access logging on protected-data endpoints (see the backend access log).
- Least-privilege access; remove access when someone no longer needs it.

Related: docs/dpa.md, [[shopify-public-distribution]].
