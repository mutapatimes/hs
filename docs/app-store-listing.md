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

Already done (code):
- [x] Managed install + token exchange ([halia/api/shopify_auth.py])
- [x] Shopify Billing / recurring charges ([halia/api/billing_shopify.py])
- [x] Mandatory compliance webhooks, HMAC-verified ([halia/api/webhooks.py])
- [x] Embedded app + App Bridge; OAuth
- [x] App config (URLs, webhooks, app proxy) deployable ([shopify.app.toml])

To do (operator, in order):
- [ ] Stand up the **public app** and swap credentials — follow docs/shopify-public-app.md.
- [ ] Complete the **Protected customer data** declaration (answers above).
- [ ] Request **read_all_orders** (API access requests), then add it back to scopes and redeploy.
- [ ] Produce the **icon + screenshots** (list above) on a demo store with sample data.
- [ ] Fill the **listing** with the copy above; set the **pricing** to match plans.py.
- [ ] Give the reviewer a **demo store + test steps** (they need data to see hidden VICs — provide a
      store pre-loaded with the sample book and a 3-line walkthrough).
- [ ] **Submit for review.**

Related: docs/shopify-public-app.md, [[shopify-public-distribution]].
