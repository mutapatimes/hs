// Halia badge in Gmail. Only fires when a conversation is actually open (a thread id in the hash),
// never on the inbox list. Gmail tags every correspondent's e-mail on a span[email] element; we
// take the other party (not the signed-in account) and match on that.

(function () {
  function accountEmail() {
    const el = document.querySelector('a[aria-label*="@"], [aria-label*="Google Account"]');
    if (el) {
      const m = (el.getAttribute("aria-label") || "").match(/[\w.+-]+@[\w.-]+\.\w+/);
      if (m) return m[0].toLowerCase();
    }
    return "";
  }

  function threadOpen() {
    const parts = location.hash.replace(/^#/, "").split("/");
    return parts.length >= 2 && parts[parts.length - 1].length > 8;
  }

  function extract() {
    if (!threadOpen()) return null;
    const main = document.querySelector('[role="main"]');
    if (!main) return null;
    const me = accountEmail();
    const els = Array.prototype.slice.call(main.querySelectorAll("span[email]"));
    const emails = els.map((e) => (e.getAttribute("email") || "").toLowerCase()).filter(Boolean);
    const other = emails.find((e) => e && e !== me) || emails[0];
    if (!other) return null;
    const nameEl = els.find((e) => (e.getAttribute("email") || "").toLowerCase() === other);
    const name = nameEl ? (nameEl.getAttribute("name") || "").trim() : "";
    return { email: other, name };
  }

  // Drop a template into the open compose or reply body (contenteditable). Only works when a
  // draft is actually open; otherwise the badge tells the user to open a reply first.
  function insert(text) {
    const box = document.querySelector(
      'div[aria-label="Message Body"], div[role="dialog"] div[contenteditable="true"], ' +
      'div[contenteditable="true"][role="textbox"]');
    if (!box || !text) return false;
    box.focus();
    return document.execCommand("insertText", false, text) !== false;
  }

  HaliaBadge.setInserter(insert);
  Halia.observe(extract);
})();
