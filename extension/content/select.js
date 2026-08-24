// Halia look-up anywhere — highlight a name, email or phone on any page and check them against your
// book, without leaving where you are. A small pill appears by the selection; one tap shows their
// grade, why, and the next move. The mirror of highlighting a name into HaliaShare on iOS. This is a
// self-contained overlay (its own shadow root), separate from the full toolbar, so it can ride along
// on pages the toolbar doesn't run on. Reads live via the background; the page never sees the token.
(function () {
  if (window.__haliaSelect) return;
  window.__haliaSelect = true;

  const MAXLEN = 48;
  // What looks like a client identity worth a look-up. Kept tight so ordinary sentence selections
  // (and a person's own typing in a compose box) don't sprout a pill.
  const RE_EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  const RE_PHONE = /^\+?[\d][\d\s\-()]{6,}$/;
  const RE_NAME = /^[\p{L}][\p{L}'’.\-]+(?:\s+[\p{L}][\p{L}'’.\-]+){0,2}$/u;

  function classify(text) {
    const t = (text || "").trim();
    if (!t || t.length > MAXLEN) return null;
    if (RE_EMAIL.test(t)) return { email: t };
    if (RE_PHONE.test(t)) return { phone: t.replace(/[^\d+]/g, "") };
    if (RE_NAME.test(t) && /[A-Za-zÀ-ɏ]/.test(t)) return { name: t };
    return null;
  }

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .pill { position: fixed; z-index: 2147483647; background: #1a1a1a; color: #fbfaf7; border: 0;
      cursor: pointer; font-size: 12px; padding: 6px 10px; box-shadow: 0 4px 16px rgba(0,0,0,.28);
      display: inline-flex; align-items: center; gap: 7px; letter-spacing: .01em; }
    .pill:hover { background: #333; }
    .pill .m { color: #6FBFA0; font-size: 13px; }
    .card { position: fixed; z-index: 2147483647; width: 264px; max-width: 88vw; background: #fbfaf7;
      color: #1a1a1a; border: 1px solid #e3ded3; box-shadow: 0 12px 40px rgba(0,0,0,.24); }
    .card .top { display: flex; align-items: center; gap: 9px; padding: 11px 12px; background: #f4f1ea;
      border-bottom: 1px solid #eee7da; }
    .cg { flex: none; min-width: 26px; height: 24px; padding: 0 6px; display: flex; align-items: center;
      justify-content: center; font-weight: 700; font-size: 12px; color: #fff; background: #6b6355; border-radius: 3px; }
    .cg.g-a { background: #1F564A; } .cg.g-b { background: #55606b; } .cg.g-c { background: #8a8271; }
    .nm { flex: 1; min-width: 0; font-weight: 600; font-size: 13.5px; line-height: 1.2; }
    .nm .sub { font-weight: 400; font-size: 11px; color: #6b6355; margin-top: 2px; }
    .x { border: 0; background: transparent; color: #8a8271; cursor: pointer; font-size: 16px; padding: 0 2px; line-height: 1; }
    .body { padding: 10px 12px; }
    .pill-tag { display: inline-block; font-size: 10px; padding: 1px 7px; border: 1px solid #d8cfbc; color: #6b6355;
      letter-spacing: .04em; text-transform: uppercase; margin-bottom: 7px; }
    .pill-tag.hid { background: #efe7d4; border-color: #d8cfbc; color: #7a6a3f; }
    .kv { font-size: 12px; color: #33302a; line-height: 1.45; margin: 3px 0; }
    .kv b { font-weight: 600; }
    .reason { font-size: 12px; color: #33302a; line-height: 1.4; margin: 6px 0 0; padding-left: 12px; position: relative; }
    .reason:before { content: "·"; position: absolute; left: 3px; color: #1F564A; font-weight: 700; }
    .acts { display: flex; gap: 6px; margin-top: 11px; flex-wrap: wrap; }
    .btn { border: 1px solid #d8cfbc; background: #fff; color: #1a1a1a; padding: 5px 9px; cursor: pointer;
      font-size: 11.5px; text-decoration: none; display: inline-block; }
    .btn:hover { background: #f4f1ea; }
    .btn.primary { background: #1a1a1a; color: #fbfaf7; border-color: #1a1a1a; }
    .muted { color: #6b6355; font-size: 12px; line-height: 1.45; }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: #b3ab97; display: inline-block; margin-right: 6px;
      animation: hb 1s ease-in-out infinite; }
    @keyframes hb { 0%,100% { opacity: .3; } 50% { opacity: 1; } }
  `;

  let host, root, pill, card, lastText = "", anchor = null;

  function ensure() {
    if (root) return;
    host = document.createElement("div");
    host.style.all = "initial";
    (document.body || document.documentElement).appendChild(host);
    root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    root.appendChild(style);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function gradeClass(g) {
    g = String(g || "").trim().toUpperCase();
    return g[0] === "A" ? "g-a" : g[0] === "B" ? "g-b" : g[0] === "C" ? "g-c" : "";
  }

  function clearPill() { if (pill) { pill.remove(); pill = null; } }
  function clearCard() { if (card) { card.remove(); card = null; } }
  function clearAll() { clearPill(); clearCard(); lastText = ""; anchor = null; }

  // Place a floating element at the selection: just above it, nudged onto screen.
  function position(el, rect, h) {
    const pad = 6;
    let top = rect.top - (h || el.offsetHeight) - pad;
    if (top < pad) top = rect.bottom + pad;                 // no room above -> below
    let left = rect.left;
    const w = el.offsetWidth;
    if (left + w > window.innerWidth - pad) left = window.innerWidth - w - pad;
    if (left < pad) left = pad;
    el.style.top = Math.max(pad, top) + "px";
    el.style.left = left + "px";
  }

  function showPill(text, rect, query) {
    ensure(); clearCard(); clearPill();
    pill = document.createElement("button");
    pill.className = "pill";
    const label = text.length > 22 ? text.slice(0, 21) + "…" : text;
    pill.innerHTML = `<span class="m">⁂</span>Look up “${esc(label)}”`;
    root.appendChild(pill);
    anchor = rect;
    position(pill, rect);
    pill.onclick = (e) => { e.stopPropagation(); lookup(text, query, rect); };
  }

  const FRIENDLY = {
    "no-token": "Add your Halia token in the extension options first.",
    "unauthorized": "Your Halia token is not recognised. Re-generate it in Settings.",
    "network": "Could not reach Halia.",
    "no-token ": "Add your Halia token in the extension options first."
  };

  function lookup(text, query, rect) {
    ensure(); clearPill();
    card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<div class="body"><span class="dot"></span><span class="muted">Checking your book…</span></div>`;
    root.appendChild(card);
    position(card, rect, 90);
    card.addEventListener("click", (e) => e.stopPropagation());
    try {
      chrome.runtime.sendMessage({ type: "halia:lookup", query }, (r) => {
        if (chrome.runtime.lastError) return renderCard(text, { error: "network" }, rect);
        renderCard(text, r || { error: "empty" }, rect);
      });
    } catch (e) { renderCard(text, { error: "network" }, rect); }
  }

  function renderCard(text, r, rect) {
    if (!card) return;
    const close = `<button class="x" data-a="x" title="Close">×</button>`;
    if (r && r.error) {
      card.innerHTML = `<div class="top"><span class="nm">Halia</span>${close}</div>
        <div class="body"><div class="muted">${esc(FRIENDLY[r.error] || "Something went wrong.")}</div></div>`;
    } else if (!r || !r.found) {
      card.innerHTML = `<div class="top"><span class="nm">${esc(text)}</span>${close}</div>
        <div class="body"><div class="muted">No signal for this one in your book yet.</div></div>`;
    } else {
      const name = r.name || text;
      const sub = r.hidden ? "Hidden VIC" : (r.tier || "");
      const reason = (r.reasons && r.reasons[0]) || r.reco || r.action || "";
      const bits = [];
      if (r.latent) bits.push(`<div class="kv"><b>Latent</b> ${esc(String(r.latent))}</div>`);
      if (r.spend) bits.push(`<div class="kv"><b>Spend</b> £${Number(r.spend).toLocaleString()}</div>`);
      const acts = [];
      if (r.dashboard) acts.push(`<a class="btn primary" href="${esc(r.dashboard)}" target="_blank" rel="noopener">Open in Halia</a>`);
      if (r.adminUrl) acts.push(`<a class="btn" href="${esc(r.adminUrl)}" target="_blank" rel="noopener">Open in store</a>`);
      card.innerHTML = `
        <div class="top">
          <span class="cg ${gradeClass(r.grade)}">${esc(r.grade || "·")}</span>
          <span class="nm">${esc(name)}${sub ? `<span class="sub">${esc(sub)}</span>` : ""}</span>
          ${close}
        </div>
        <div class="body">
          ${r.playLabel ? `<span class="pill-tag${r.hidden ? " hid" : ""}">${esc(r.playLabel)}</span>` : ""}
          ${bits.join("")}
          ${reason ? `<div class="reason">${esc(reason)}</div>` : ""}
          ${acts.length ? `<div class="acts">${acts.join("")}</div>` : ""}
        </div>`;
    }
    const x = card.querySelector('[data-a="x"]'); if (x) x.onclick = clearAll;
    position(card, rect, card.offsetHeight);
  }

  // Watch the selection. A settled selection of a plausible identity offers the pill; anything else
  // clears whatever is showing.
  let t = null;
  function onSelect() {
    clearTimeout(t);
    t = setTimeout(() => {
      const sel = window.getSelection();
      const text = sel ? String(sel).trim() : "";
      if (!text || text === lastText && (pill || card)) return;
      const q = classify(text);
      if (!q) { if (!card) clearPill(); return; }
      let rect;
      try { rect = sel.getRangeAt(0).getBoundingClientRect(); } catch (e) { rect = null; }
      if (!rect || (!rect.width && !rect.height)) return;
      lastText = text;
      showPill(text, rect, q);
    }, 220);
  }

  document.addEventListener("mouseup", onSelect, true);
  document.addEventListener("keyup", (e) => { if (e.key === "Escape") clearAll(); else onSelect(); }, true);
  // Tapping elsewhere dismisses; the overlay lives in a shadow root so its own clicks don't count.
  document.addEventListener("mousedown", (e) => {
    if (e.target === host) return;
    if (!pill && !card) return;
    // Keep it open when the click is inside our own UI (composed path crosses the shadow boundary).
    const path = e.composedPath ? e.composedPath() : [];
    if (path.indexOf(host) >= 0) return;
    clearAll();
  }, true);
  window.addEventListener("scroll", () => { if (pill || card) clearAll(); }, true);
})();
