// Halia badge on the store admin — Shopify, BigCommerce, and (when the merchant grants it in the
// options) their own WooCommerce wp-admin. Identity comes from the URL where the platform puts a
// stable customer id, and from the customer's e-mail where it doesn't.

(function () {
  function mailtoEmail() {
    const a = document.querySelector('a[href^="mailto:"]');
    if (!a) return "";
    return decodeURIComponent((a.getAttribute("href") || "").slice(7).split("?")[0]).trim();
  }

  function shopify() {
    const m = location.pathname.match(/\/customers\/(\d+)/);
    if (m) return { cid: m[1], platform: "shopify", email: mailtoEmail() };
    if (/\/orders\/(\d+)/.test(location.pathname)) {
      const e = mailtoEmail();
      if (e) return { email: e, platform: "shopify" };
    }
    return null;
  }

  function bigcommerce() {
    const m = location.pathname.match(/\/customers\/(\d+)/);
    if (m) return { cid: m[1], platform: "bigcommerce", email: mailtoEmail() };
    if (/\/orders\//.test(location.pathname)) {
      const e = mailtoEmail();
      if (e) return { email: e, platform: "bigcommerce" };
    }
    return null;
  }

  function woocommerce() {
    if (!/\/wp-admin\//.test(location.pathname)) return null;
    const el = document.querySelector(
      '#email, #_billing_email, input[name="email"], input[name="_billing_email"]');
    const email = ((el && el.value) || mailtoEmail() || "").trim();
    if (email && /@/.test(email)) return { email, platform: "woocommerce" };
    return null;
  }

  function extract() {
    const h = location.hostname;
    if (h === "admin.shopify.com" || h.endsWith(".myshopify.com")) return shopify();
    if (h.endsWith(".mybigcommerce.com")) return bigcommerce();
    return woocommerce();
  }

  Halia.observe(extract);
})();
