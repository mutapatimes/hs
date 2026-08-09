# Connect your Shopify store to Halia (about 3 minutes)

Halia reads your orders and customers to surface your highest-potential clients. To let it in, you
create a private, read-only key inside your own Shopify admin and paste it into Halia once. Halia
stores nothing about your customers, it scores them and keeps only the result.

## Part 1 — Create the key in Shopify (about 2 minutes)

1. In your Shopify admin, open **Settings → Apps and sales channels → Develop apps**.
   (If you see a prompt, click **Allow custom app development** first, then continue.)
2. Click **Create an app**, name it **Halia**, and click **Create app**.
3. Open **Configuration → Configure Admin API scopes**, and tick these five:
   - `read_orders`
   - `read_all_orders`  (lets Halia see your full order history, recommended)
   - `read_customers`
   - `write_customers`  (lets Halia tag your best clients back into Shopify)
   - `read_products`

   Click **Save**.
4. Go to the **API credentials** tab, click **Install app** (top right), then **Install**.
5. Under **Admin API access token**, click **Reveal token once** and **copy** it. It starts with
   `shpat_`. Copy it now, Shopify only shows it one time.

## Part 2 — Give it to Halia (about 1 minute)

1. Go to **https://haliascore.com/connect**.
2. Choose **Shopify**.
3. Paste your **store domain** (the `.myshopify.com` address, even if you use a custom domain) and the
   **`shpat_` token** you just copied.
4. Tick the terms box and click **Connect**. (If Halia gave you a signup code, enter it here.)
5. You will get a **private dashboard link**. Bookmark it, it is your way in.

That is it. Halia starts scoring your customers straight away, usually within a minute.

---

### Operator notes (Halia side, not for the merchant)

- This is the manual/token path, used because the app is on **custom distribution** and can only
  auto-install stores in glen-norah's Plus org. Any unrelated store (e.g. htown) onboards this way
  until the App Store listing is live.
- If `HALIA_SIGNUP_CODE` (or the console `signup_code`) is set, the merchant needs it at step 4 of
  Part 2, send it to them.
- The token grants exactly the five scopes above, revoke any time by uninstalling the "Halia" custom
  app in the store admin. Once the public App Store app is approved, migrate these stores to the
  click-and-approve install and they can delete the custom app.
- Related: [[shopify-public-distribution]], docs/shopify-public-app.md.
