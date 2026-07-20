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
    return Halia.insertInto(box, text);
  }

  HaliaPanel.setChannel("email");
  HaliaPanel.setInserter(insert);
  Halia.observe(extract);

  // ── Inbox triage dots: a small grade marker on each conversation row, so the highest-grade
  // client gets answered first. Grades are batched (one request per new set of visible senders)
  // and rendered as a coloured tag before the sender name. Nothing is stored.
  const seen = {};          // email -> grade obj, or null once looked up and not a client
  let pending = false;

  function dotColor(g) {
    const t = String(g.grade || "").toUpperCase();
    return t[0] === "A" ? "#9a7b3f" : t[0] === "B" ? "#55606b" : "#8a8271";
  }
  function inboxRows() { return document.querySelectorAll("tr.zA"); }
  function rowEmail(row) {
    const s = row.querySelector("span[email]");
    return s ? (s.getAttribute("email") || "").toLowerCase() : "";
  }
  function markRow(row, g) {
    const s = row.querySelector("span[email]");
    if (!s) return;
    let dot = row.querySelector(".halia-dot");
    if (!g) { if (dot) dot.remove(); return; }
    if (dot && dot.dataset.g === String(g.grade)) return;   // already correct — no DOM churn
    if (dot) dot.remove();
    dot = document.createElement("span");
    dot.className = "halia-dot";
    dot.dataset.g = String(g.grade);
    dot.textContent = g.grade;
    dot.title = "Halia grade " + g.grade + (g.play === "sleeping" ? " · gone quiet" : "");
    dot.style.cssText = "display:inline-block;min-width:15px;height:14px;line-height:14px;" +
      "text-align:center;font:700 9px Arial,sans-serif;color:#fff;margin-right:6px;padding:0 3px;" +
      "border-radius:0;vertical-align:middle;background:" + dotColor(g);
    s.parentNode.insertBefore(dot, s);
  }
  function applyKnown() {
    inboxRows().forEach((row) => {
      const em = rowEmail(row);
      if (em && em in seen) markRow(row, seen[em]);
    });
  }
  function scan() {
    const need = new Set();
    inboxRows().forEach((row) => {
      const em = rowEmail(row);
      if (em && !(em in seen)) need.add(em);
    });
    applyKnown();
    if (!need.size || pending) return;
    pending = true;
    try {
      chrome.runtime.sendMessage({ type: "halia:batch", body: { emails: Array.from(need).slice(0, 100) } },
        (r) => {
          pending = false;
          if (chrome.runtime.lastError || !r || r.error) return;
          const grades = r.grades || {};
          need.forEach((em) => { seen[em] = grades[em] || null; });
          applyKnown();
        });
    } catch (e) { pending = false; }
  }
  const debScan = (() => { let t = null; return () => { clearTimeout(t); t = setTimeout(scan, 600); }; })();
  new MutationObserver(debScan).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("scroll", debScan, true);
  debScan();
})();
