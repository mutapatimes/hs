# Commerce pack: pay-by-link and reserve-for-collection (opt-in write scope)

## Why this doc

Halia is read-only by default, and that is part of the wedge: it reads a merchant's store to score
clients and never writes. Two clienteling actions people keep asking for, though, do need to write:
a real **pay-by-link** (so a client pays in the chat) and **reserve-for-collection** (so an item is
held). This doc records how we add those without giving up the read-only default: as an **opt-in
commerce pack** that requests one narrow extra Shopify scope, and serves **both** the iOS keyboard and
the Chrome extension from one backend endpoint.

## What already ships (read-only, no new scope)

- **Cart permalink ("Pay in chat").** `POST /v1/extension/cart_link {product_ids}` resolves each
  product to a buyable variant and returns a `/cart/<variant>:<qty>` link on the merchant's own
  domain. The client taps it and checks out themselves. It creates nothing on the store. Live in the
  keyboard today; trivial to add to the extension drawer (same endpoint). Caveat: it preloads a
  default variant, so size is adjusted at checkout.
- **Open-basket recovery link.** The lookup response already carries the abandoned-checkout URL; the
  keyboard's "Nudge basket" uses it. That is a real pay link for the client's own basket, with the
  right items and sizes, and needs no scope.

These cover a lot. The commerce pack is for when the merchant wants a proper invoice or a real hold.

## What the commerce pack adds (opt-in, one write scope)

### The scope
`write_draft_orders` on Shopify. It lets the app create draft orders and invoices. It cannot alter
products or inventory, and cannot read or change customer PII destructively. Least privilege.

### Opt-in, so read-only stays the default
- A merchant setting, "Enable commerce actions", off by default.
- Turning it on triggers a **re-authorization** that requests `write_draft_orders` in addition to the
  current read scopes. Merchants who never opt in are exactly as read-only as today.
- The setting gates the endpoint and the UI actions on both surfaces.

### The endpoint (shared by keyboard and extension)
`POST /v1/extension/payment_link`
- Body: `{product_ids | use_basket, cid, name, note?, hold?: bool}`
- Server: create a Shopify draft order for the customer (`cid`) with the line items (or the client's
  open basket). If `hold` is set, tag it `hold/collection` and add the note. Return the draft order's
  `invoice_url`.
- Read the scope from the merchant's stored grant; if commerce actions are off, return 403 with a
  clear "enable commerce actions" message so the surfaces can prompt.
- Zero-retention: the draft order lives in Shopify; Halia stores nothing new.

### The two features on top of that endpoint
1. **Pay-by-link.** Same selection UI as the catalogue/cart, but the action mints an `invoice_url`.
   The client pays at a real, itemised invoice (supports a custom note or agreed price).
2. **Reserve-for-collection.** `hold: true`. Creates the held draft order, tags it for the floor,
   inserts a confirmation ("set aside for you, ready Thursday"), and logs to the pipeline (reuse the
   existing `/v1/extension/action` "contacted"/note path).

## Both surfaces

- **iOS keyboard.** In suggestions mode, add "Pay-by-link" and "Reserve" beside "Send catalogue" and
  "Pay in chat". Gate on the commerce-actions setting synced with the token; if off, show the prompt.
- **Chrome extension.** The drawer's cart/catalogue section gains the same two buttons, calling the
  same endpoint. This is where the user specifically wants it too, and it is free once the endpoint
  exists.

## Costs and risks

- **Re-consent.** Existing merchants must re-authorize to grant `write_draft_orders`. This is the main
  operational friction, not the code. Keep it opt-in so only the merchants who want it re-consent.
- **Positioning.** Be explicit in the UI and marketing that the default stays read-only and that
  commerce actions are a deliberate, per-merchant opt-in. The read-only story is a selling point;
  protect it.
- **Least privilege.** Request only `write_draft_orders`. Do not bundle broader write scopes.

## Build order (when we do it)

1. Backend: the merchant setting + scope request in the OAuth flow; `POST /v1/extension/payment_link`
   (draft order create via Shopify Admin API), gated on the setting. Tests for the gate and the two
   modes (invoice, hold).
2. Keyboard: two actions in suggestions mode, gated; insert the returned `invoice_url` (or the hold
   confirmation).
3. Extension: the same two actions in the drawer.

## Out of scope for the pack
- Stripe payment links (a separate integration; Shopify draft orders are the native fit for a store).
- Modifying real inventory counts (a hold is a tagged draft order, not an inventory decrement).
