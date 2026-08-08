# Going public: a new Shopify app with a universal install link

## Why a new app

The current app **HALIA** (`client_id 813658d9fa7652961809f617b47f1c0b`) is locked to **Custom
distribution** (tied to glen-norah's Plus org). Shopify does not let you convert a custom app to
public, so a smooth, any-store install link requires a **new app** created as **Public
distribution**.

You do **not** need a full App Store *listing* (the slow marketing review) to get that link. An
**unlisted public** app gives you a universal install link that any merchant can use with the normal
click-and-approve flow (no manual tokens). The App Store listing can come later.

Nearly everything the review needs is already built: managed install + token exchange
([halia/api/shopify_auth.py]), Shopify Billing / recurring charges ([halia/api/billing_shopify.py]),
and the mandatory compliance webhooks ([halia/api/webhooks.py]).

## Migrate now — it is cheap

The backend keys to ONE app at a time (`SHOPIFY_API_KEY`/`SHOPIFY_API_SECRET`). Switching to the new
app means existing installs on the old custom app must reinstall. Today that is only glen-norah (+
htown), so do it before you have real merchants.

## Steps (operator-run; the CLI needs your Partner login)

1. **Create the public app.** Partner Dashboard → Apps → **Create app**. Then open it →
   **Distribution** → choose **Public distribution**. (Public, unlisted is fine — you don't have to
   submit an App Store listing to use the install link.)

2. **Link a separate CLI config** so the custom app's `shopify.app.toml` is left untouched:
   ```
   shopify app config link --config public      # pick the NEW public app
   ```
   This writes `shopify.app.public.toml` with the new `client_id`.

3. **Replace `shopify.app.public.toml` with the canonical config below**, keeping the new `client_id`
   the CLI just filled in. (Same shape we deployed to the custom app; `read_all_orders` stays out
   until Shopify approves it.)

   ```toml
   client_id = "PASTE_THE_NEW_PUBLIC_APP_CLIENT_ID"
   application_url = "https://haliascore.com"
   embedded = true
   name = "Halia"

   [access_scopes]
   scopes = "read_customers,read_orders,write_customers,read_products"
   optional_scopes = [ ]
   use_legacy_install_flow = false

   [auth]
   redirect_urls = [
     "https://haliascore.com/connect/shopify/callback",
     "https://haliascore.com",
   ]

   [webhooks]
   api_version = "2026-04"

     [[webhooks.subscriptions]]
     compliance_topics = [ "customers/data_request", "customers/redact", "shop/redact" ]
     uri = "https://haliascore.com/webhooks/shopify"

     [[webhooks.subscriptions]]
     topics = [ "app/uninstalled" ]
     uri = "https://haliascore.com/webhooks/shopify"

   [app_proxy]
   url = "https://haliascore.com/proxy/catalogue"
   subpath = "catalogue"
   prefix = "a"
   ```

4. **Deploy the new app's config:**
   ```
   shopify app deploy --config public
   ```

5. **Swap the backend credentials (Render env), then redeploy the service:**
   - `SHOPIFY_API_KEY`   = the new app's client_id
   - `SHOPIFY_API_SECRET` = the new app's client **secret** (new app → API credentials)
   This is the switch-over point: the old custom app stops working, the new one takes over.

6. **Reinstall on your stores** via the new app's install link (Distribution → install link — now
   public, so any store). glen-norah and htown click, approve, done. Billing/comp state is keyed by
   store domain, so it carries over.

7. **Complete "Protected customer data"** in the new app (it reads `read_customers`/`read_orders`).
   Halia's zero-retention answer makes this the easy version.

8. **Request `read_all_orders`** under **API access requests**. Once granted, add `read_all_orders`
   back into the `scopes` line and `shopify app deploy --config public` again. Until then order
   history is ~60-day capped (already today's behaviour).

9. **Verify** post-deploy: `POST https://haliascore.com/webhooks/shopify` returns 401 (HMAC guard),
   and installing on a test store completes with no token prompt.

## After migration

- Keep the old custom **HALIA** app until glen-norah + htown are reinstalled on the new app, then
  retire it.
- App Store *listing* (discoverability + ratings) is a later, optional step: app listing copy, icon,
  screenshots, pricing, privacy URL, then submit for review. Ask and I'll draft the listing.

Related: [[shopify-public-distribution]].
