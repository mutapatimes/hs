# Halia — Shopify App Store listing (draft)

Everything needed to submit HALIA for public distribution. Copy fields are written in brand voice and
are paste-ready; assets and Dashboard actions are checklists. Source of truth for pricing is
[halia/plans.py]; keep this in sync with it and web/site/pricing.html.

---

## Listing copy (paste-ready)

**App name**
```
Halia
```

**Tagline / card subtitle** (≤62 chars)
```
Private client intelligence for luxury retail
```

**App introduction** (one sentence, ≤100 chars)
```
Halia surfaces the high-value clients your spend thresholds miss, and the next move for each.
```

**App details** (long description)
```
Every luxury book holds clients who spend modestly with you and lavishly elsewhere. Halia finds them.
It reads your orders and customers against open wealth and intent signals, and surfaces the quiet
clients worth a personal word, each with the reason behind the grade and the next move to make.

Halia is private by design. It scores a customer and keeps the result. The person's data stays with
you, which is what lets Halia serve houses across the UK and the EU with confidence.

Your team sees the work where they already are. A dashboard ranks your hidden VICs by latent value. A
discreet toolbar puts a client's grade, the reasons, and a ready message inside WhatsApp Web, Gmail,
your store admin, and Shopify POS, so an associate never breaks stride. Branded catalogues, a
clienteling pipeline, and campaign tracking carry a signal all the way to a sale.

What you get:
• Hidden-VIC scoring: the high-potential clients your spend reports overlook, ranked by latent value.
• The reason and the move: why a client scores, and the next best action, in plain words.
• Where you work: a toolbar for WhatsApp Web, Gmail, store admin, and Shopify POS.
• Branded catalogues and pay-in-chat links your clients recognise as yours.
• A clienteling pipeline and campaign tracking, so outreach becomes revenue you can measure.
• Private by design: Halia keeps the score, your customers' data stays yours.

Built for premium and luxury houses who serve people, not segments.
```

**Primary category:** Store management → Customer analytics (confirm against Shopify's current list;
secondary: Marketing and conversion).

**Works with:** Shopify POS, WhatsApp Web, Gmail, Slack, Klaviyo, Mailchimp.

**Languages:** English.

---

## Pricing (must match your Shopify Billing plans — halia/plans.py)

| Plan | Price / month (GBP) | For |
|------|--------------------:|-----|
| Free scan | £0 | See what's hiding, free forever |
| Discovery | £150 | Smaller premium brands, up to 15k customers |
| Signal | £500 | Established brands, 15k–75k customers |
| Atelier | £1,200 | Large houses / high volume, 75k+ customers |
| Maison | Custom | Groups and largest houses, multi-brand |

Billed through Shopify Billing (recurring app charges, `EVERY_30_DAYS`), already implemented in
[halia/api/billing_shopify.py]. The App Store requires Shopify Billing for charges, this is met.

---

## Assets to produce

- **App icon** — 1200×1200 PNG, the ⁂ mark on brand deep green (source: extension/icons). No text.
- **Feature screenshots** — 1600×900, at least 3 (aim for 5–6), captured on a demo store with data:
  1. Overview: hidden-VIC count, total latent value, the grade donut.
  2. A client drawer: grade, the reasons behind it, latent value, the next move.
  3. The in-page toolbar on WhatsApp Web (grade + reasons + a ready message).
  4. Branded product catalogue / pay-in-chat link.
  5. The clienteling pipeline (VIC kanban).
  6. Campaigns: live sales + reactivation.
- **Demo video** (optional, recommended) — 30–60s: open dashboard → open a hidden VIC → send from the toolbar.
- **Privacy policy URL:** https://haliascore.com/privacy
- **FAQ URL:** https://haliascore.com/faq · **Security:** https://haliascore.com/security
- **Support email:** hello@haliascore.com

---

## Protected customer data (declaration answers)

- **What data:** customer profiles (name, email, address) and order history, via `read_customers`,
  `read_orders`/`read_all_orders`. `write_customers` is used only to tag a client back into Shopify.
- **Why:** to compute a private potential-value ("hidden VIC") score from open wealth and intent
  signals, and to show the associate the reason and the next best action.
- **Retention:** minimal. Customer records are processed to compute the score and are not retained as
  a customer database; Halia keeps the resulting grade and signals, not the raw profile. State the
  exact retention window from the current architecture when filling the form.
- **Sharing / selling:** never sold, never shared. Any push to a CRM or email tool is merchant-
  initiated, to the merchant's own connected account.
- **Sub-processors:** hosting/infra only (e.g. Render). List them as they stand at submission.

This zero-retention posture is the strongest part of the review, lead with it.

---

## Review-readiness checklist

Audited against Shopify's app requirements on 2026-09-28. Everything the review can test in
code is in place; what remains lives in the Partner Dashboard, on Render, or in a recording.

In the code, verified:
- [x] Managed install and token exchange; OAuth completes before anything else runs, on
      reinstall too ([halia/api/shopify_auth.py]).
- [x] Session-token authentication, no cookies or local storage for identity, so incognito works
      ([halia/api/embedded.py]). Browser storage holds only view preferences.
- [x] App Bridge loaded from Shopify's CDN with the `shopify-api-key` meta tag; admin nav via
      `ui-nav-menu`; per-shop `frame-ancestors` CSP on the embedded page, `DENY` everywhere else.
- [x] Billing through the Billing API only: subscribe, upgrade and downgrade from Settings, Free
      is a cancel, no reinstall and no support contact needed ([halia/api/billing_shopify.py]).
      Stripe serves only tenants Shopify bars from the Billing API.
- [x] The four compliance webhooks, HMAC-verified, with uninstall erasing every row for the shop
      ([halia/api/webhooks.py]).
- [x] Scopes limited to what the features use: customers and orders to score, `write_customers`
      to tag and note, `read_products` for the catalogue. `read_all_orders` granted 2026-08-10.
- [x] First load returns at once and scores in the background, so a large book cannot time out
      the install ([halia/api/embedded.py], tests/test_embedded_first_load.py).
- [x] Admin API pinned to 2026-04, inside Shopify's support window and matching the webhook
      version; every query validated against 2026-01, 2026-04 and 2026-07.
- [x] Every confirmation and naming step uses an in-page dialog, so nothing depends on native
      browser dialogs inside the admin frame.
- [x] No storefront or theme code, so Lighthouse scores are untouched. The app proxy serves
      catalogue pages on their own URL with the proxy signature checked.
- [x] Listing assets at the required sizes: icon 1200×1200, three screenshots 1600×900
      ([docs/listing-assets/]). Privacy, security, FAQ and terms pages live on haliascore.com.

In the Partner Dashboard and on Render, yours:
- [ ] **Pricing section**: enter every plan from the table above, currency GBP, custom pricing on
      for Maison. The review paused on this (1.2.1).
- [ ] **Testing instructions**: paste the block from docs/listing-assets/review-instructions.md
      and add a review mailbox you check daily.
- [ ] **Screencast**: re-record from docs/listing-assets/screencast-script.md, English, under
      eight minutes, including the billing scene.
- [ ] **Render**: move the web service off the free plan before resubmitting, so the reviewer
      never meets a cold start.
- [ ] **Protected customer data**: confirm the declaration shows as applied, not draft.
- [ ] **Emergency developer contact** current in the Partner Dashboard.
- [ ] **Demo store**: a development store with orders older than a season, so grades show.
- [ ] Keep `HALIA_SHOPIFY_BILLING_TEST=true` through review; set it to `false` and
      `HALIA_SHOPIFY_APP_LIVE=1` on approval.
- [ ] **Resubmit.**

Related: docs/shopify-public-app.md, [[shopify-public-distribution]].
