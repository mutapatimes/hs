// Halia Concierge in Klaviyo. On a customer profile, recognise them by email and show their Halia
// grade, so a marketer sees who quietly matters while building flows and segments. Read-only
// recognition (no composer here). Matched by email. Nothing is stored.

(function () {
  function extract() {
    if (!/\/profile/i.test(location.pathname)) return null;   // only on a profile page
    const scope = document.querySelector('main, [class*="profile" i]') || document;
    const email = Halia.pageEmail(scope);
    return email && email.indexOf("@") >= 0 ? { email } : null;
  }

  HaliaPanel.setChannel("email");
  Halia.observe(extract);   // no inserter: Klaviyo is a marketing view, not a 1:1 composer
})();
