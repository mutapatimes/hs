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

  // ── Chat-list triage dots: a small grade tag on each chat whose saved name matches a client,
  // so the highest-grade client stands out in the list. Matched by name (WhatsApp exposes no
  // address in the list), batched per new set of visible names. Nothing is stored.
  const seen = {};          // lowercased name -> grade obj, or null once looked up
  let pending = false;

  function dotColor(g) {
    const t = String(g.grade || "").toUpperCase();
    return t[0] === "A" ? "#9a7b3f" : t[0] === "B" ? "#55606b" : "#8a8271";
  }
  function listRows() { return document.querySelectorAll('#pane-side div[role="listitem"]'); }
  function rowName(row) {
    const s = row.querySelector("span[title]");
    return s ? (s.getAttribute("title") || "").trim() : "";
  }
  function markRow(row, g) {
    const s = row.querySelector("span[title]");
    if (!s) return;
    let dot = row.querySelector(".halia-dot");
    if (!g) { if (dot) dot.remove(); return; }
    if (dot && dot.dataset.g === String(g.grade)) return;
    if (dot) dot.remove();
    dot = document.createElement("span");
    dot.className = "halia-dot";
    dot.dataset.g = String(g.grade);
    dot.textContent = g.grade;
    dot.title = "Halia grade " + g.grade + (g.play === "sleeping" ? " · gone quiet" : "");
    dot.style.cssText = "display:inline-block;min-width:15px;height:14px;line-height:14px;" +
      "text-align:center;font:700 9px Arial,sans-serif;color:#fff;margin-right:5px;padding:0 3px;" +
      "border-radius:0;vertical-align:middle;background:" + dotColor(g);
    s.parentNode.insertBefore(dot, s);
  }
  function applyKnown() {
    listRows().forEach((row) => {
      const n = rowName(row).toLowerCase();
      if (n && n in seen) markRow(row, seen[n]);
    });
  }
  function scan() {
    const need = new Set();
    listRows().forEach((row) => {
      const n = rowName(row).toLowerCase();
      if (n && !(n in seen)) need.add(n);
    });
    applyKnown();
    if (!need.size || pending) return;
    pending = true;
    try {
      chrome.runtime.sendMessage({ type: "halia:batch", body: { names: Array.from(need).slice(0, 100) } },
        (r) => {
          pending = false;
          if (chrome.runtime.lastError || !r || r.error) return;
          const grades = r.grades || {};
          need.forEach((n) => { seen[n] = grades[n] || null; });
          applyKnown();
        });
    } catch (e) { pending = false; }
  }
  const debScan = (() => { let t = null; return () => { clearTimeout(t); t = setTimeout(scan, 700); }; })();
  new MutationObserver(debScan).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("scroll", debScan, true);
  debScan();
})();
