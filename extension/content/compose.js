// Halia templates in any composer — the send-anywhere companion to look-up-anywhere. Whenever the
// cursor is in a message box (a textarea or a rich composer) on any page, a small mark appears at its
// corner; one tap opens the house templates, filled for whoever you pick, with the greeting and
// sign-off on or off. Drops the note straight into the box. Self-contained (own shadow root), so it
// rides on pages the toolbar was never wired for. Reads live; the token stays in the background.
(function () {
  if (window.__haliaCompose) return;
  window.__haliaCompose = true;

  // ── template shaping: fill the name, and honour the greeting / sign-off toggles ──
  const GREET_RE = /^(dear|dearest|hi|hello|hey|good\s+(morning|afternoon|evening)|greetings)\b/i;
  const SIGN_LINE = /^(warm(est)?\s+(regards|wishes)|kind(est)?\s+regards|best(\s+(regards|wishes))?|very\s+best|all\s+the\s+best|with\s+(love|thanks|gratitude|appreciation|warm\s+wishes|warmth)|many\s+thanks|thank\s+you|thanks|yours(\s+(sincerely|truly|faithfully))?|sincerely|warmly|speak\s+soon|see\s+you\s+soon|regards|cheers|love|xx)[.,!]*(\s+[A-Z][\w'’.-]*(\s+[A-Z][\w'’.-]*)?)?$/i;
  function fillName(body, first) { return String(body || "").split("{first_name}").join(first || "there"); }
  // Remove the leading salutation clause up to its comma (handles "Dear X,\n\n…" and inline
  // "Hi X, …"), or a short own-line greeting with no comma.
  function stripGreeting(text) {
    let t = String(text || "").replace(/^\s+/, "");
    if (!GREET_RE.test(t)) return String(text || "");
    const comma = t.indexOf(","), nl = t.indexOf("\n");
    if (comma >= 0 && (nl < 0 || comma < nl)) {
      return t.slice(comma + 1).replace(/^[ \t]*\n+/, "").replace(/^[ \t]+/, "");
    }
    if (nl >= 0 && nl <= 24) return t.slice(nl + 1).replace(/^\s+/, "");
    return String(text || "");
  }
  // Cut from the closing line to the end. Only the last few lines are considered, and a line counts
  // as a closing only when it is essentially just a sign-off phrase (optionally a name), so body
  // text like "Thanks for your patience." is never mistaken for one.
  function stripSignoff(text) {
    const lines = String(text || "").split("\n");
    const nonEmpty = [];
    for (let k = 0; k < lines.length; k++) if (lines[k].trim()) nonEmpty.push(k);
    if (!nonEmpty.length) return String(text || "");
    const tail = nonEmpty.slice(-4);
    let cut = -1;
    for (let j = 0; j < tail.length; j++) if (SIGN_LINE.test(lines[tail[j]].trim())) { cut = tail[j]; break; }
    if (cut < 0) return String(text || "");
    let out = lines.slice(0, cut);
    while (out.length && !out[out.length - 1].trim()) out.pop();
    return out.join("\n");
  }
  function shape(body, first, greeting, signoff) {
    let t = fillName(body, first);
    if (!greeting) t = stripGreeting(t);
    if (!signoff) t = stripSignoff(t);
    return t;
  }

  // Insert text at the cursor of a field, preserving line breaks. Textareas/inputs take a spliced
  // value with the native setter (so frameworks notice); rich composers take a synthetic paste (the
  // editor's own handler keeps the line breaks), same approach the toolbar uses.
  function insertInto(el, text) {
    if (!el || !text) return false;
    el.focus();
    const t = String(text);
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      const s = el.selectionStart != null ? el.selectionStart : (el.value || "").length;
      const e = el.selectionEnd != null ? el.selectionEnd : (el.value || "").length;
      setter.call(el, (el.value || "").slice(0, s) + t + (el.value || "").slice(e));
      el.dispatchEvent(new Event("input", { bubbles: true }));
      try { el.selectionStart = el.selectionEnd = s + t.length; } catch (x) { /* ignore */ }
      return true;
    }
    try {
      const dt = new DataTransfer();
      dt.setData("text/plain", t);
      el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
      return true;
    } catch (x) {
      const lines = t.split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        if (i > 0) document.execCommand("insertLineBreak");
        if (lines[i]) document.execCommand("insertText", false, lines[i]);
      }
      return true;
    }
  }

  // Which element counts as a composer worth offering the mark on: a textarea or a rich editor. Short
  // inputs (search boxes) can still receive a template, but we don't clutter them with the mark.
  function editableRoot(el) {
    if (!el) return null;
    if (el.tagName === "TEXTAREA") return el;
    if (el.isContentEditable) {
      let e = el;
      while (e.parentElement && e.parentElement.isContentEditable) e = e.parentElement;
      return e;
    }
    return null;
  }

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .chip { position: fixed; z-index: 2147483646; width: 26px; height: 26px; border-radius: 50%;
      background: #1a1a1a; color: #6FBFA0; border: 0; cursor: pointer; font-size: 14px; line-height: 1;
      display: flex; align-items: center; justify-content: center; box-shadow: 0 3px 12px rgba(0,0,0,.28); }
    .chip:hover { background: #333; }
    .panel { position: fixed; z-index: 2147483647; width: 300px; max-width: 90vw; background: #fbfaf7;
      color: #1a1a1a; border: 1px solid #e3ded3; box-shadow: 0 14px 44px rgba(0,0,0,.26); }
    .ph { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #f4f1ea;
      border-bottom: 1px solid #eee7da; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #6b6355; }
    .ph .m { color: #1F564A; font-size: 13px; }
    .ph .sp { flex: 1; }
    .x { border: 0; background: transparent; color: #8a8271; cursor: pointer; font-size: 16px; line-height: 1; padding: 0 2px; }
    .body { padding: 10px 12px; }
    .row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #33302a; }
    .who { border: 1px solid #d8cfbc; background: #fff; color: #33302a; cursor: pointer; font-size: 12px;
      padding: 3px 9px; display: inline-flex; align-items: center; gap: 6px; }
    .who .clr { color: #8a8271; font-size: 13px; }
    .tgls { display: flex; gap: 14px; margin: 10px 0 2px; }
    .tgl { display: flex; align-items: center; gap: 7px; font-size: 12px; color: #33302a; cursor: pointer; user-select: none; }
    .tgl input { width: 15px; height: 15px; }
    input.s { width: 100%; padding: 7px 9px; border: 1px solid #d8cfbc; background: #fff; font-size: 12.5px;
      font-family: inherit; color: #1a1a1a; margin-top: 10px; }
    input.s:focus { outline: 2px solid #1F564A; outline-offset: -1px; }
    .tlist { border: 1px solid #ece5d6; max-height: 210px; overflow-y: auto; background: #fff; margin-top: 8px; }
    .tcat { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: #8a8271; padding: 7px 9px 3px; background: #faf7f0; position: sticky; top: 0; }
    .titem { display: block; width: 100%; text-align: left; border: 0; background: transparent; padding: 7px 9px;
      font-size: 12.5px; color: #1a1a1a; cursor: pointer; border-bottom: 1px solid #f4efe4; }
    .titem:last-child { border-bottom: 0; }
    .titem:hover { background: #f4f1ea; }
    .clist { border: 1px solid #ece5d6; max-height: 150px; overflow-y: auto; background: #fff; margin-top: 6px; }
    .cli { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; border: 0; background: transparent;
      padding: 6px 9px; cursor: pointer; border-bottom: 1px solid #f4efe4; }
    .cli:hover { background: #f4f1ea; }
    .cg { flex: none; min-width: 20px; height: 18px; padding: 0 4px; display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 9.5px; color: #fff; background: #6b6355; border-radius: 3px; }
    .cg.g-a { background: #1F564A; } .cg.g-b { background: #55606b; } .cg.g-c { background: #8a8271; }
    .cn { flex: 1; min-width: 0; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .muted { color: #6b6355; font-size: 12px; line-height: 1.45; padding: 8px 9px; }
    .toast { position: fixed; z-index: 2147483647; background: #1a1a1a; color: #fff; font-size: 11px; padding: 5px 10px;
      opacity: 0; transition: opacity .15s; pointer-events: none; }
    .toast.on { opacity: 1; }
  `;

  let host, root, chip, panel, toastEl;
  let target = null;             // the composer we will insert into (kept across the field's blur)
  let templates = null;          // cached [{name,category,subject,body}] | "busy" | "err"
  let clients = null;            // client roster for personalisation | "busy" | "err"
  let chosen = null;             // {name,grade,...} the note is addressed to
  let greeting = true, signoff = true;
  let tplQuery = "";

  try {
    chrome.storage.sync.get(["tplGreeting", "tplSignoff"], (r) => {
      if (r && typeof r.tplGreeting === "boolean") greeting = r.tplGreeting;
      if (r && typeof r.tplSignoff === "boolean") signoff = r.tplSignoff;
    });
  } catch (e) { /* defaults stand */ }

  function ensure() {
    if (root) return;
    host = document.createElement("div");
    host.style.all = "initial";
    (document.body || document.documentElement).appendChild(host);
    root = host.attachShadow({ mode: "open" });
    const st = document.createElement("style"); st.textContent = CSS; root.appendChild(st);
    chip = document.createElement("button");
    chip.className = "chip"; chip.textContent = "⁂"; chip.title = "Insert a Halia template";
    chip.style.display = "none";
    chip.onmousedown = (e) => e.preventDefault();     // don't steal focus from the composer
    chip.onclick = (e) => { e.stopPropagation(); openPanel(); };
    root.appendChild(chip);
    toastEl = document.createElement("div"); toastEl.className = "toast"; root.appendChild(toastEl);
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function gradeClass(g) {
    g = String(g || "").trim().toUpperCase();
    return g[0] === "A" ? "g-a" : g[0] === "B" ? "g-b" : g[0] === "C" ? "g-c" : "";
  }
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    const r = chip.getBoundingClientRect();
    toastEl.style.left = Math.max(8, r.left - 120) + "px";
    toastEl.style.top = (r.top - 6) + "px";
    toastEl.classList.add("on");
    setTimeout(() => toastEl.classList.remove("on"), 1400);
  }

  function placeChip() {
    if (!chip || !target || !target.isConnected) { if (chip) chip.style.display = "none"; return; }
    const r = target.getBoundingClientRect();
    if (r.width < 60 || r.bottom < 0 || r.top > window.innerHeight) { chip.style.display = "none"; return; }
    chip.style.display = "flex";
    chip.style.left = Math.min(window.innerWidth - 34, r.right - 32) + "px";
    chip.style.top = Math.min(window.innerHeight - 34, r.bottom - 32) + "px";
  }

  function firstOf(c) { return c && c.name ? String(c.name).trim().split(/\s+/)[0] : ""; }

  function openPanel() {
    ensure();
    if (panel) { closePanel(); return; }
    panel = document.createElement("div");
    panel.className = "panel";
    root.appendChild(panel);
    panel.addEventListener("mousedown", (e) => e.stopPropagation());
    if (templates === null) loadTemplates(); else renderPanel();
    renderPanel();
    positionPanel();
  }
  function closePanel() { if (panel) { panel.remove(); panel = null; } }
  function positionPanel() {
    if (!panel || !chip) return;
    const r = chip.getBoundingClientRect();
    const w = panel.offsetWidth, h = panel.offsetHeight;
    let left = r.right - w; if (left < 8) left = 8;
    let top = r.top - h - 8; if (top < 8) top = r.bottom + 8;
    panel.style.left = left + "px";
    panel.style.top = Math.max(8, top) + "px";
  }

  function loadTemplates() {
    templates = "busy"; renderPanel();
    try {
      chrome.runtime.sendMessage({ type: "halia:context" }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) templates = "err";
        else templates = (r.templates || []);
        renderPanel(); positionPanel();
      });
    } catch (e) { templates = "err"; renderPanel(); }
  }
  function loadClients(q) {
    clients = "busy"; renderPanel();
    try {
      chrome.runtime.sendMessage({ type: "halia:clients", q: q || "" }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) clients = "err";
        else clients = (r.clients || []);
        renderPanel(); positionPanel();
      });
    } catch (e) { clients = "err"; renderPanel(); }
  }

  let pickingClient = false;
  function renderPanel() {
    if (!panel) return;
    const list = Array.isArray(templates) ? templates : [];
    const q = tplQuery.trim().toLowerCase();
    const matches = list.map((t, i) => ({ t, i })).filter(({ t }) =>
      !q || ((t.name || "") + " " + (t.category || "") + " " + (t.body || "")).toLowerCase().indexOf(q) >= 0);
    const groups = []; const idx = {};
    matches.forEach(({ t, i }) => {
      const c = t.category || "General";
      if (!(c in idx)) { idx[c] = groups.length; groups.push({ cat: c, items: [] }); }
      groups[idx[c]].items.push({ t, i });
    });
    const forLabel = chosen ? `${esc(firstOf(chosen))} <span class="clr">✕</span>` : "Anyone";
    panel.innerHTML = `
      <div class="ph"><span class="m">⁂</span><span>Insert a template</span><span class="sp"></span>
        <button class="x" data-a="x">×</button></div>
      <div class="body">
        <div class="row">For <button class="who" data-a="who">${forLabel}</button></div>
        ${pickingClient ? `
          <input class="s" data-a="csearch" placeholder="Search your book" style="margin-top:8px">
          <div class="clist" data-a="clist"></div>` : ""}
        <div class="tgls">
          <label class="tgl"><input type="checkbox" data-a="g"${greeting ? " checked" : ""}>Greeting</label>
          <label class="tgl"><input type="checkbox" data-a="s"${signoff ? " checked" : ""}>Sign-off</label>
        </div>
        ${templates === "busy" ? `<div class="muted">Loading your templates…</div>`
          : templates === "err" ? `<div class="muted">Couldn't load your templates. Check the extension is connected.</div>`
          : !list.length ? `<div class="muted">Add outreach templates in Halia → Settings → Templates.</div>`
          : `<input class="s" data-a="tsearch" placeholder="Search templates" value="${esc(tplQuery)}">
             <div class="tlist">${groups.length
               ? groups.map((g) => `<div class="tcat">${esc(g.cat)}</div>` +
                   g.items.map(({ t, i }) => `<button class="titem" data-ti="${i}">${esc(t.name || ("Template " + (i + 1)))}</button>`).join("")).join("")
               : `<div class="muted">No templates match.</div>`}</div>`}
      </div>`;
    // wiring
    panel.querySelector('[data-a="x"]').onclick = closePanel;
    panel.querySelector('[data-a="who"]').onclick = () => {
      if (chosen) { chosen = null; renderPanel(); positionPanel(); return; }
      pickingClient = !pickingClient; renderPanel(); positionPanel();
      if (pickingClient && !Array.isArray(clients)) loadClients("");
    };
    const g = panel.querySelector('[data-a="g"]');
    if (g) g.onchange = () => { greeting = g.checked; saveToggles(); };
    const s = panel.querySelector('[data-a="s"]');
    if (s) s.onchange = () => { signoff = s.checked; saveToggles(); };
    const ts = panel.querySelector('[data-a="tsearch"]');
    if (ts) ts.oninput = () => { tplQuery = ts.value; renderPanel(); const n = panel.querySelector('[data-a="tsearch"]');
      if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } };
    panel.querySelectorAll("[data-ti]").forEach((b) => b.onclick = () => insertTemplate(+b.dataset.ti));
    if (pickingClient) {
      const cs = panel.querySelector('[data-a="csearch"]');
      if (cs) cs.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); loadClients(cs.value); } };
      paintClients();
    }
  }
  function paintClients() {
    const box = panel && panel.querySelector('[data-a="clist"]'); if (!box) return;
    if (clients === "busy") { box.innerHTML = `<div class="muted">Reading your book…</div>`; return; }
    if (clients === "err") { box.innerHTML = `<div class="muted">Couldn't reach your book.</div>`; return; }
    if (!Array.isArray(clients) || !clients.length) { box.innerHTML = `<div class="muted">No one found.</div>`; return; }
    box.innerHTML = clients.slice(0, 40).map((c, i) => `
      <button class="cli" data-cci="${i}">
        <span class="cg ${gradeClass(c.grade)}">${esc(c.grade || "·")}</span>
        <span class="cn">${esc(c.name)}</span></button>`).join("");
    box.querySelectorAll("[data-cci]").forEach((b) => b.onclick = () => {
      chosen = clients[+b.dataset.cci]; pickingClient = false; renderPanel(); positionPanel();
    });
  }
  function saveToggles() {
    try { chrome.storage.sync.set({ tplGreeting: greeting, tplSignoff: signoff }); } catch (e) { /* ignore */ }
  }
  function insertTemplate(i) {
    const list = Array.isArray(templates) ? templates : [];
    const t = list[i]; if (!t || !target) return;
    const text = shape(t.body, firstOf(chosen), greeting, signoff);
    const ok = insertInto(target, text);
    closePanel();
    if (!ok) { try { navigator.clipboard.writeText(text); } catch (e) { /* ignore */ } toast("Copied — paste it in"); }
    else toast("Inserted");
  }

  // ── follow the cursor ──
  function onFocusIn(e) {
    const root2 = editableRoot(e.target);
    if (root2) { target = root2; placeChip(); }
  }
  function onFocusOut() {
    setTimeout(() => {
      const a = document.activeElement;
      if (a === host) return;                       // focus moved into our own UI
      if (!editableRoot(a) && !panel) { if (chip) chip.style.display = "none"; }
    }, 150);
  }
  ensure();
  document.addEventListener("focusin", onFocusIn, true);
  document.addEventListener("focusout", onFocusOut, true);
  // Keep the mark pinned to the field as the page scrolls or resizes; close the panel on scroll so it
  // doesn't drift away from its anchor.
  let raf = 0;
  function reflow() { if (raf) return; raf = requestAnimationFrame(() => { raf = 0; placeChip(); if (panel) closePanel(); }); }
  window.addEventListener("scroll", reflow, true);
  window.addEventListener("resize", reflow, true);
  document.addEventListener("mousedown", (e) => {
    if (!panel) return;
    const path = e.composedPath ? e.composedPath() : [];
    if (path.indexOf(host) >= 0) return;            // clicks inside our UI keep it open
    closePanel();
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && panel) closePanel(); }, true);
})();
