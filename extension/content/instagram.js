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

  // The open DM's recent messages, so the brief can answer what was actually said. Instagram
  // renders each message as a row; outgoing ones are labelled "You sent" in the accessibility
  // tree, which is the only reliable side-hint IG exposes. Read live; nothing is stored.
  function readThread() {
    if (!/\/direct\//.test(location.pathname)) return [];
    const main = document.querySelector('div[role="main"]') || document;
    return Halia.readMessages(main, 'div[role="row"]', /you sent|you replied|outgoing/i, 6);
  }

  HaliaPanel.setChannel("email");   // treat IG links as a direct/referral channel for UTMs
  HaliaPanel.setInserter(insert);
  HaliaPanel.setThreadReader(readThread);
  Halia.observe(extract);
})();
