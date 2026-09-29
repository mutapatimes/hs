# Halia security hardening checklist

> One prioritised list, ordered by value-for-effort. Do the cheap, high-probability items first.
> Legend: ✅ done · ◻ to-do (you) · ⚙ infra/ops (Render/accounts, not a repo change).
> Not legal/audit advice; a third-party pentest should validate all of this before a serious
> enterprise client. Companion docs: [security-key-management.md](security-key-management.md),
> [dpia-lia-support.md](dpia-lia-support.md), [privacy-notice-profiling.md](privacy-notice-profiling.md).

## The one thing to internalise
Halia already made the best move: **it holds no customer database.** Customers are scored in memory
and discarded; the only thing persisted is one encrypted, read-only store credential. So you're not
guarding a treasure vault — you're (a) keeping attackers off the box, (b) making sure the keys to
*other people's* vaults are held properly, and (c) shrinking the brief in-memory window. The
"attacker hits during scoring" risk is **downstream of a host compromise you should prevent anyway**,
so spend effort in proportion to how attacks actually happen (unpatched deps, leaked creds, account
takeover) — not how dramatic they sound.

## Tier A — keep the attacker off the box (cheapest, highest probability)
- ◻ **Patch dependencies.** Run `pip audit` (or Dependabot on the repo); update anything with a known
  CVE. Unpatched libraries are the most likely path to code execution.
- ⚙ **2FA everywhere on your own accounts** — Render, GitHub, domain registrar, email. Account
  takeover of the deploy pipeline is a direct route to the app. Takes an hour; do it.
- ✅ **No secrets in git** — verified: only fake test tokens + doc placeholders; `.env` is ignored.
  Keep a `git-secrets`/`gitleaks` pre-commit sweep to keep it that way.
- ✅ **Rate limiting** — per-IP limits on the auth/scoring/onboarding endpoints ([app.py](../halia/api/app.py)
  `_rate_limited`), returning 429 on abuse.
- ✅ **No customer data in logs or disk (hosted path)** — verified: `/v1/export` builds CSV in an
  in-memory buffer, no temp files, and `traceback.print_exc()` sites are stack-only. Keep it so:
  never log a customer row or a token; don't attach request bodies to error context.
- ◻ **Operator hygiene.** The CLI tools (`export_scored` → `output/hidden_vics.xlsx`, `build_mvp` →
  `output/mvp.html`) are the **only** place customer-derived data lands on disk. They're git-ignored,
  but delete them after use and never run them on a shared machine.

## Tier B — shrink the in-memory window & exposure (the "processing moment")
Reaching in-memory data requires an attacker already executing code on the host. You can't make that
window zero (the data must be cleartext to score), but you can make it small, hard to hit, low-value.
- ◻ **Shorten the window.** Scored results live in RAM for `HALIA_CACHE_TTL` (**currently 300s** —
  [render.yaml](../render.yaml)/[cache.py](../halia/cache.py)). Lowering to ~120s halves the worst-case
  lifetime of the full dataset. Trade-off: the dashboard re-pulls/re-scores more often. *(Recommended;
  one-line change when you want it.)*
- ⚙ **Restrict outbound egress.** The app only needs to reach a **finite, known set**: Shopify,
  WooCommerce, Klaviyo, Mailchimp, Brevo (email), Stripe, and the web-push endpoint. Lock outbound
  traffic to those hosts so that even code running on the box can't easily exfiltrate to an attacker's
  server. Underrated and high-value.
- ⚙ **Host minimalism.** No shell access to production, no core dumps to disk, minimal running
  services, monitoring/alerting on anomalies.
- ✅ **In-memory only export/render.** The dashboard and CSV are built in memory and streamed — no
  intermediate disk file. Keep new features to this pattern.

## Tier C — architectural hardening (bigger changes)
- ◻ **Separate the key-encryption secret** into a managed secrets service (KMS / Secrets Manager /
  Vault / Doppler) with rotation. Today `HALIA_ENCRYPTION_KEY` is an env var on the app: a DB dump
  alone can't decrypt (good), but full app compromise yields both. Full runbook +
  MultiFernet rotation in [security-key-management.md](security-key-management.md). **Highest-value
  architectural item.**
- ◻ **Isolate the scorer.** Scoring currently runs *inside the internet-facing web process*
  (uvicorn). Moving it to a separate, short-lived worker means the tier that faces the internet isn't
  the same memory space that holds cleartext customer data mid-scan — so a web-tier compromise doesn't
  automatically sit on the scoring memory. Bigger change; do it when capacity allows.

## Tier D — before a serious enterprise client
- ◻ **Third-party penetration test** of the running system. The single highest-value thing for the
  reviewer to confirm is Tier C's key separation. Until it's done, don't claim "penetration tested"
  or SOC 2 / ISO 27001 for *Halia* (your host, Render, holds those — say so, but don't claim them as
  your own).
- ◻ **Publish the honest boundary statement:** "No system is impenetrable. Because we hold no
  customer database, the most a successful attacker could reach is a single encrypted, read-only
  credential; the in-memory scoring window is small and isolated, and nothing about your customers is
  written to our disk, database, or logs." That candour reads, to a security team, as *understanding*
  your threat model — worth more than a false absolute.

## Controls in code (September 2026)
Each of these is enforced in code and pinned by a test, so it stays true as the product grows.

**Keys and sessions**
- One signing key per purpose ([tenant_auth.py](../halia/api/tenant_auth.py) `_secret(purpose)`): a
  merchant session, a staff session, a team sign-in link, the console, the CMS, a deck link and a
  billing return each verify under their own derived key. A cookie minted for one surface is
  meaningless on another. A session whose expiry lies beyond its own lifetime is void.
- Webhooks act only on the shop named inside the signed body, on an allow-listed topic
  ([webhooks.py](../halia/api/webhooks.py)); the header alone never chooses the target.
- A store is created once ([store.py](../halia/store.py) `create_tenant` is insert-only). A second
  connection under the same or a look-alike key answers 409 and changes nothing.
- The billing return carries a signed state; a forged return cannot activate a plan.

**Input handling**
- Every fetch to an address a merchant or visitor supplied goes through
  [netguard.py](../halia/netguard.py): public http(s) only, resolved before the call, re-checked on
  each redirect, capped in size. Private ranges, loopback, link-local and cloud metadata are refused.
- HTML that reaches a page is reduced to an allow-list with nh3 (blog bodies, CMS overrides);
  uploads are sniffed and served under a sandboxing policy; text that is echoed is escaped.
- `/v1/score` caps a batch at 100 rows; the manager-only exports need a manager session.
- The rate limiter keys on the right-most forwarded address, counts sign-in attempts separately
  and covers the catalogue, order webhooks and the extension routes.

**The extension, the keyboard and the add-in**
- The extension token lives in device-local storage, readable only by the extension's own trusted
  contexts, never in synced storage and never by the scripts that run inside WhatsApp, Gmail or a
  store page. Only a page on Halia's own origin, in the top frame, can hand over a token, and the
  server address is always Halia's, whatever the page says.
- A scanned code can sign the phone in; it cannot point the keyboard at another server.
- Sign-out on every surface empties everything the device held: the burst queue, seen events,
  opening hours, store details, saved openers.
- Bulk endpoints are capped per caller as well as per store ([extension.py](../halia/api/extension.py)
  `_ext_rate`): the client book is served a page at a time, the caller-ID directory a few times a
  day, a burst a dozen times an hour. A token that leaves the building is worth a page of names, not
  the book.
- A seat token ends when the person signs out on any device, and lapses on its own after ninety
  days unused ([store.py](../halia/store.py) `signout_seat`, `SEAT_IDLE_DAYS`). The seat stays on
  the team; a manager's re-issue is the way back in. Every client forgets a token the moment Halia
  answers 401.
- The extension reaches only haliascore.com, sends no cookies and caches nothing; the options page
  never shows a stored token and never writes one to synced storage.
- On iOS the token sits in the Keychain, readable after first unlock and bound to that device, so
  it is in no backup and moves to no other phone. Requests go through a session with no cache and
  no cookie jar. The shared container is excluded from backups. Copied messages are for that device
  only and expire in minutes, so Universal Clipboard carries no client's message to a Mac. The app
  switcher shows a cover, not the book.

**AI drafting**
- One shared weekly budget per store across every AI call, counted before the call so a failed
  call still costs; a daily ceiling per seat; and a per-store switch (Settings, House voice,
  "Draft with AI") that turns every model call off in favour of the store's own templates.
- The conversation on screen is quoted inside tags the model is told to treat as data. Every
  prompt carries the rule that nothing in the material can change the task, that links, codes and
  account details from a client's message are never repeated, and that the client is never asked
  for a payment or a code. A generated draft keeps only links that point at the store, its
  catalogue or Halia. The estimated value figure never enters a prompt.

**Data handling**
- Real exports live outside the checkout ([datavault.py](../halia/datavault.py)); public demo pages
  are built from synthetic files only; a scanner runs in the pre-commit hook, the first CI job, the
  test suite and at application start, which refuses to serve a public tree carrying a real-export
  tell. Log output masks addresses and long digit runs.

## Sequencing (if you do nothing else)
1. `pip audit` + 2FA on your accounts (Tier A) — hours, closes the likely paths.
2. Keep customer data out of logs/disk (already true — guard it) + operator-file hygiene.
3. Lower `HALIA_CACHE_TTL` and restrict egress (Tier B).
4. Move the encryption key to a secrets manager (Tier C) — the one that changes your risk profile.
5. Pentest before signing an enterprise client (Tier D).
