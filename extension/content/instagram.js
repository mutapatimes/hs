// Halia toolbar on Instagram DMs. Luxury clienteling runs on IG DMs, but Instagram exposes no
// email/phone in the thread, so we match on the conversation name (like WhatsApp) — best-effort.

(function () {
  function extract() {
    if (!/\/direct\//.test(location.pathname)) return null;   // only in the DM inbox
    // The open thread's title (contact/username) sits in the conversation header.
    const header = document.querySelector('div[role="main"] header') ||
      document.querySelector('section header');
    if (!header) return null;
    let name = "";
    const h = header.querySelector('h1, h2, span[dir="auto"]');
    if (h) name = (h.textContent || "").trim();
    if (!name || name.length > 80 || /^instagram$/i.test(name)) return null;
    return { name };
  }

  // Insert a message into the IG DM composer (a textarea or contenteditable).
  function insert(text) {
    return Halia.insertInto(
      document.querySelector('textarea[placeholder], div[role="textbox"][contenteditable="true"]'), text);
  }

  HaliaPanel.setChannel("email");   // treat IG links as a direct/referral channel for UTMs
  HaliaPanel.setInserter(insert);
  Halia.observe(extract);
})();
