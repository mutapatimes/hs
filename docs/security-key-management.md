# Runbook: protecting the store-access secrets (key management)

> Operator runbook. Not legal advice. The goal is to keep the *one thing Halia persists* —
> encrypted merchant access credentials — protected even if something else is compromised.

## What Halia actually holds
Halia stores **no customer data** (customers are scored in memory and discarded). The only
secrets persisted, per shop, are:
- the **Shopify offline access token** (`read_orders`, `read_customers`, and `write_customers`
  where tagging is enabled), and
- the merchant's **Klaviyo / Mailchimp API keys**.

These are encrypted at rest with **Fernet (AES-128-CBC + HMAC)** in
[`halia/crypto.py`](../halia/crypto.py), keyed by the `HALIA_ENCRYPTION_KEY` environment
variable. Encrypted values carry an `enc:v1:` prefix so we only ever try to decrypt what we
encrypted.

## Current posture (honest)
- ✅ The encryption key is **not in the database** — it's an env var. So a **stolen database
  dump cannot decrypt** the tokens. This is real and worth stating.
- ✅ Nothing sensitive is in git (`.env` is git-ignored; only fake tokens appear in tests).
- ⚠️ The key currently lives in the **app's environment** (Render env var), so an attacker who
  achieves **code execution on the running app** can read both the env key and the DB blobs.
  That is the residual risk this runbook reduces.

**Honest framing:** moving the key to a managed secrets service (below) gives **rotation,
access auditing, and no plaintext key sitting in the environment**. It does **not** make full
app-compromise harmless — the app must still decrypt a token to use it, so live RCE can always
read a token in use. The win is blast-radius + auditability + fast rotation, not immunity.

## The hosting layer already carries certifications
The app + Postgres run on **Render**, which holds **SOC 2 Type 2**, **ISO 27001**, an **annual
third-party penetration test**, and offers a **GDPR DPA**. Halia inherits that infrastructure
assurance; it is not a substitute for Halia's own review, but it is a legitimate, checkable part
of the story for a buyer's security team (see the Hosting FAQ).

## Step 1 — Baseline (do now, no code change)
- Set `HALIA_ENCRYPTION_KEY` only as a **Render secret env var** (already the pattern in
  [`render.yaml`](../render.yaml), `sync: false`), never committed, never logged.
- Restrict who can view Render env vars (workspace 2FA + least-privilege members).
- Confirm the Postgres instance is **not publicly reachable** (private networking; app-only).

## Step 2 — Move the key into a managed secrets service (highest-value hardening)
Pick one and fetch the key at startup instead of reading a plain env var:
- **AWS Secrets Manager / KMS**, **GCP Secret Manager**, **HashiCorp Vault**, or **Doppler /
  Infisical**. All give versioning, access logs, and rotation.
- Minimal change in [`halia/crypto.py`](../halia/crypto.py) `_fernet()`: instead of
  `os.environ.get("HALIA_ENCRYPTION_KEY")`, resolve the key from the secrets client (cache it in
  memory for the process lifetime; scope the app's IAM role to *read that one secret*).
- Keep the env-var path as a documented fallback for local dev.

## Step 3 — Support rotation (so a leaked key is recoverable fast)
- Switch Fernet → **MultiFernet** with an ordered key list `[new, old]`: it **encrypts with the
  first** key and **decrypts with any**. This lets you rotate without downtime:
  1. add the new key at the front, deploy (now decrypts old + new);
  2. re-encrypt existing rows lazily (on next read/write) or with a one-off pass;
  3. drop the old key on the next deploy.
- Document the rotation cadence (e.g. yearly, or immediately on suspected exposure).

## Step 4 — Contain and detect
- **Rotate/scope tokens:** keep Shopify tokens read-only by default; treat the `write_customers`
  stores (tagging) as higher-risk and rotate their tokens first if anything leaks.
- **No secrets in logs:** the request/scoring path logs only counts today — keep it that way;
  never log a token or a customer row (audit `traceback.print_exc()` sites in
  [`halia/notify.py`](../halia/notify.py) / [`onboarding.py`](../halia/api/onboarding.py) if you
  start attaching context to errors).
- **Own-account hygiene:** 2FA on Render, GitHub, the domain registrar, and email — account
  takeover of the deploy pipeline is a direct path to the app.

## Incident: a key (or token) may be exposed
1. Rotate `HALIA_ENCRYPTION_KEY` (Step 3) and/or revoke the affected store token at source
   (Shopify admin / Klaviyo / Mailchimp).
2. A tenant disconnect already deletes their stored key immediately — use it.
3. Notify the affected **merchant** (they are the data controller and decide any downstream
   notification to their customers).
4. Record what happened, when, and what was rotated.

## Before a serious enterprise client
Commission a **third-party penetration test** of the running system. The single highest-value
thing for the reviewer to confirm is Step 2 — that compromising the app server alone does not
hand over the ability to decrypt stored tokens.
