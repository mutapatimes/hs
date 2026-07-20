// Halia badge on WhatsApp Web. The open chat's header carries the contact's saved name, or their
// raw number if they aren't saved. We match on the number where we have it (the backend compares
// the trailing national digits), and fall back to an exact-name match against the book.

(function () {
  function extract() {
    const main = document.querySelector("#main");
    if (!main) return null;
    const header = main.querySelector("header");
    if (!header) return null;
    // The open chat's name (or raw number if unsaved) lives in the header. WhatsApp's markup shifts,
    // so try a title attribute first, then the first readable text span, and clean it up.
    let title = "";
    const cand = header.querySelector('span[title][dir="auto"], span[title], span[dir="auto"]');
    if (cand) title = (cand.getAttribute("title") || cand.textContent || "").trim();
    if (!title) {
      const h1 = header.querySelector("h1, h2");
      if (h1) title = (h1.textContent || "").trim();
    }
    if (!title || title.length > 80) return null;
    const looksPhone = /^\+?[\d][\d\s\-()]{6,}$/.test(title);
    if (looksPhone) return { phone: title.replace(/[^\d+]/g, "") };
    return { name: title };
  }

  // Drop a template straight into the message box. WhatsApp's editor is contenteditable; an
  // execCommand insertText fires the input events it listens for, so the text is really typed,
  // not just pasted into a dead node.
  function insert(text) {
    const box = document.querySelector('footer [contenteditable="true"]');
    if (!box || !text) return false;
    box.focus();
    return document.execCommand("insertText", false, text) !== false;
  }

  HaliaPanel.setChannel("whatsapp");
  HaliaPanel.setInserter(insert);
  Halia.observe(extract);
})();
