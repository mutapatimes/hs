// Backend contract for the POS tile — the durable, framework-agnostic part.
//
// Auth: a POS session token is sent as `Authorization: Bearer <token>`. The Halia
// backend verifies it via the same `require_shop` path as the embedded admin app.
// If verify fails on a real device, decode the token once (check `alg`/`iss`/`aud`);
// if it is RS256/OIDC rather than HS256, add a JWKS branch to verify_session_token.
//
// Set BACKEND to your deployed HALIA_APP_URL.
export const BACKEND = "https://halia.onrender.com";

// Ask Halia about the customer currently on the cart.
// Returns { matched, vic, grade, score, tier, is_priority, hidden_vic,
//           gesture, signals: string[], reasons, spend } or { matched:false }.
export async function scoreCustomer(customerId) {
  if (!customerId) return { matched: false };
  const token = await shopify.session.getSessionToken();
  const url = `${BACKEND}/v1/pos/score?customer_id=${encodeURIComponent(customerId)}`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`Halia lookup failed (${res.status})`);
  return res.json();
}

// The customer id assigned to the current POS cart, or null.
export function currentCustomerId() {
  const cart = shopify?.cart?.current?.value;
  return cart && cart.customer ? cart.customer.id : null;
}
