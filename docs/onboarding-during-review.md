# Onboarding Shopify clients while the app is under review

Shopify is reviewing Halia's public app. Until it approves, a store outside your own Partner
organisation cannot install the public app: Shopify blocks it with "This app is under review."
Two paths work today. Both end with the client fully live on Halia.

| | Bridge app (Path A) | Token method (Path B) |
|---|---|---|
| Client experience | One click, like a normal app install | ~2 minutes of copy-paste in their admin |
| Your setup per client | ~5 minutes in the Partner Dashboard | None |
| Use for | Priority brands, first impressions | Anyone who shows up, zero notice |
| Billing | Stripe | Stripe |

After approval, one env flip restores the normal public one-click for everyone new.

---

## Path A: bridge app (one-click, you set it up first)

A "bridge app" is a private copy of Halia you create in your Partner Dashboard for one specific
store. Shopify does not review these, so the client can install it today. It points at the same
backend as everything else.

### You do (once per client, ~5 minutes)

1. Go to **partners.shopify.com → Apps → Create app**. Name it "Halia — {Brand}".
   The name is only visible to you.
2. When asked about distribution, choose **Custom distribution** and enter the client's
   `.myshopify.com` address. Never do this on the main Halia app: the distribution choice is
   permanent per app.
3. In the app's Configuration, set:
   - **App URL**: `https://haliascore.com/`
   - **Allowed redirection URL**: `https://haliascore.com/connect/shopify/callback`
4. On the app's overview page, copy the **Client ID** and **Client secret** (two codes Shopify
   shows you). Add them to the `HALIA_SHOPIFY_CUSTOM_APPS` env var on Render:

   ```
   HALIA_SHOPIFY_CUSTOM_APPS=brand.myshopify.com=CLIENT_ID:CLIENT_SECRET
   ```

   More clients later are appended with commas:

   ```
   HALIA_SHOPIFY_CUSTOM_APPS=brand-a.myshopify.com=id:secret,brand-b.myshopify.com=id:secret
   ```

   Redeploy so it takes effect.
5. Send the client either the install link (Partner Dashboard → the app → **Generate link**)
   or simply `https://haliascore.com/connect`. The wizard recognises their store and shows
   them the one-click card.

### The client does

1. Click the link.
2. Approve the permissions screen in their Shopify admin. Done: Halia appears in their admin
   and the dashboard loads with their scores.

### First-install checks (do these on client number one)

- Open their dashboard and confirm order history goes back further than 60 days. If it stops
  at ~2 months, Shopify did not grant `read_all_orders` to the bridge app; tell me and we
  adjust the scope request.
- Confirm the Stripe billing panel renders in their Settings (requires the Stripe env vars
  below).

---

## Path B: token method (works today, zero setup from you)

### You do

Send them `https://haliascore.com/connect`. If `HALIA_SIGNUP_CODE` is set on Render, also
send the code. That is all.

### The client does (the wizard walks them through it)

1. In their Shopify admin: **Settings → Apps and sales channels → Develop apps**.
2. Click **Create an app**, name it Halia.
3. **Configure Admin API scopes** and turn on: `read_orders`, `read_customers`,
   `write_customers`, `read_products`. Save.
4. Click **Install app**, confirm, then copy the **Admin API access token** (starts with
   `shpat_`, shown once).
5. Paste their store address and the token into the wizard. Done.

---

## Billing during review (both paths)

Bridge and token clients pay through **Stripe**, not Shopify. Custom-distribution apps are not
allowed to use Shopify's billing, and token clients never touch the Shopify app at all. The
code is live; it needs three env vars on Render before anyone can pay:

| Env var | What it is |
|---|---|
| `STRIPE_SECRET_KEY` | Your Stripe API key |
| `STRIPE_PLAN_LINKS` | `discovery=https://buy.stripe.com/...,signal=...,atelier=...` payment links, one per plan, created in Stripe |
| `STRIPE_WEBHOOK_SECRET` | From a Stripe webhook endpoint pointed at `https://haliascore.com/webhooks/stripe` |

The client sees plan cards in their dashboard; choosing one opens Stripe checkout; the webhook
marks them active automatically. They manage or cancel from the Stripe portal in Settings.

Until these are set, clients can use Halia but cannot pay.

---

## After Shopify approves the public app

1. Set `HALIA_SHOPIFY_APP_LIVE=1` on Render and redeploy. The `/connect` wizard now shows the
   one-click Shopify card to **every** store, wired to the public app. That is the whole
   revert for new clients.
2. **Leave existing bridge clients exactly as they are.** Their apps keep working
   indefinitely, their Stripe billing keeps working, and nothing forces a migration. Keep
   their entries in `HALIA_SHOPIFY_CUSTOM_APPS`.
3. Migrate a bridge client to the public app only if you want them on Shopify billing. To do
   it: they install the public app from the App Store listing (one click), Halia swaps to the
   public app's token for their store automatically on install, then cancel their Stripe
   subscription and have them subscribe on the Plans screen. Remove their env entry only
   after that install has succeeded.
4. Token-method clients (Path B) can stay as they are forever, or install the public app the
   same way whenever you or they want the embedded admin experience.

---

## Env var quick reference

| Var | Purpose |
|---|---|
| `HALIA_SHOPIFY_APP_LIVE` | `1` once Shopify approves; shows the public one-click to everyone |
| `HALIA_SHOPIFY_CUSTOM_APPS` | `shop=client_id:secret,...` one entry per bridge client |
| `SHOPIFY_API_KEY` / `SHOPIFY_API_SECRET` | The public Halia app's credentials |
| `STRIPE_SECRET_KEY`, `STRIPE_PLAN_LINKS`, `STRIPE_WEBHOOK_SECRET` | Stripe billing for bridge + token clients |
| `HALIA_SIGNUP_CODE` | Optional gate on `/connect`; share it with invited clients |
