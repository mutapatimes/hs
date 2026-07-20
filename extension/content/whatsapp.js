// Halia badge on WhatsApp Web. The open chat's header carries the contact's saved name, or their
// raw number if they aren't saved. We match on the number where we have it (the backend compares
// the trailing national digits), and fall back to an exact-name match against the book.

(function () {
  function extract() {
    const main = document.querySelector("#main");
    if (!main) return null;
    const titleEl = main.querySelector("header span[title]");
    const title = titleEl ? (titleEl.getAttribute("title") || "").trim() : "";
    if (!title) return null;
    const looksPhone = /^\+?[\d\s\-()]{7,}$/.test(title);
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

  HaliaBadge.setInserter(insert);
  Halia.observe(extract);
})();
