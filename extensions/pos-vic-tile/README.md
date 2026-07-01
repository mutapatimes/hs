# Halia — POS "potential VIC" tile

A Shopify **POS UI extension**: a home Smart Grid tile that lights up when the customer on the
current cart is a potential VIC, and opens a modal with their Halia grade, the discreet suggested
play (gesture), and the "why". It calls the Halia backend (`GET /v1/pos/score`) live at the till.

## How it fits together
- **Backend** (already live): `GET /v1/pos/score?customer_id=…` on the FastAPI app returns a compact
  staff-facing payload. Auth is a POS **session token** (`Authorization: Bearer`), verified by the
  backend's `require_shop`. CORS is open to `cdn.shopify.com` / `extensions.shopifycdn.com`.
- **This extension** deploys to the **same Partner app** as the backend (`client_id` in the repo-root
  `shopify.app.toml` must equal `SHOPIFY_API_KEY`). Node is only needed here at deploy time — the
  production backend still runs `uvicorn` on Render, unchanged.

## First-time setup
```bash
# from the repo root
shopify app config link      # pick the existing "Halia" app → fills client_id in shopify.app.toml
```

## Develop & test (requires a dev store + the Shopify POS app on a device)
```bash
shopify app dev              # live preview; open your dev store in the POS app
```
1. In POS, add a **known VIC** to the cart (a customer your dashboard grades A*/A).
2. The **Halia** tile on the home grid should light up: `A* · Potential VIC`.
3. Tap it → modal shows the grade, the discreet play, and the signals.
4. **One-time auth check:** log/inspect the value of `shopify.session.getSessionToken()`. If it is a
   standard session token (HS256, `aud` = your API key, `dest` = shop) the backend already verifies
   it. If it is RS256/OIDC, add a JWKS branch to `verify_session_token` in
   `halia/api/shopify_auth.py` (the tile will 401 until then).

## Deploy
```bash
shopify app deploy           # versioned release of the extension to the Partner app
```

## Set the backend URL
`src/api.js` → `BACKEND` must equal your `HALIA_APP_URL` (default `https://halia.onrender.com`).

## Caveats
- Component tags in `Tile.jsx` / `Modal.jsx` follow the 2026 POS UI web-component API and could not
  be validated in CI. If `shopify app generate extension` (or `shopify app dev`) scaffolds a
  different signature, keep the logic and reconcile the JSX with the generated template. `src/api.js`
  (the backend contract) is the stable part.
- Bundle limit is 64 KB; requires the latest Shopify POS app.
- The tile only resolves customers who are **identified** on the cart (returning customer / captured
  email) — a true anonymous walk-in has no history until they pay.
