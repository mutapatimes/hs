// Halia toolbar — a persistent, docked clienteling panel rendered into a Shadow DOM host so the
// page (Gmail, WhatsApp, the store admin) can neither restyle nor read it. It is always present:
// a handle on the right edge opens a panel that keeps your templates, running campaigns and
// catalogue ready, and updates the top "client" section live as you move between conversations.
// Exposes window.HaliaPanel. Reads live from the book and stores nothing.

(function () {
  if (window.HaliaPanel) return;

  const CHAN = { whatsapp: ["whatsapp", "chat"], email: ["email", "email"],
    admin: ["catalogue", "referral"] };

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .handle { position: fixed; right: 0; top: 50%; transform: translateY(-50%); z-index: 2147483647;
      background: #1a1a1a; color: #fbfaf7; border: 0; cursor: pointer; padding: 12px 7px;
      writing-mode: vertical-rl; text-orientation: mixed; letter-spacing: .12em; font-size: 11px;
      text-transform: uppercase; display: flex; align-items: center; gap: 8px; box-shadow: -2px 0 12px rgba(0,0,0,.18); }
    .handle .m { writing-mode: horizontal-tb; font-size: 14px; color: #cdb682; }
    .dock.open .handle { display: none; }
    .panel { position: fixed; right: 0; top: 0; height: 100vh; width: 344px; max-width: 92vw;
      z-index: 2147483647; background: #fbfaf7; color: #1a1a1a; border-left: 1px solid #e3ded3;
      box-shadow: -12px 0 44px rgba(0,0,0,.16); display: flex; flex-direction: column;
      transform: translateX(100%); transition: transform .18s ease; }
    .dock.open .panel { transform: translateX(0); }
    .bar { display: flex; align-items: center; gap: 8px; padding: 12px 14px; border-bottom: 1px solid #eee7da;
      background: #f4f1ea; flex: none; }
    .bar .m { color: #8a7a4f; font-size: 15px; }
    .bar .t { font-weight: 600; letter-spacing: .06em; text-transform: uppercase; font-size: 11px; color: #6b6355; }
    .bar .sp { flex: 1; }
    .modebtn { border: 1px solid #d8cfbc; background: #fff; color: #6b6355; font-size: 10px;
      text-transform: uppercase; letter-spacing: .05em; padding: 3px 8px; cursor: pointer; }
    .modebtn.int { background: #1a1a1a; color: #fbfaf7; border-color: #1a1a1a; }
    .chip { border: 1px solid #d8cfbc; background: #fff; color: #33302a; cursor: pointer; font-size: 11px;
      padding: 3px 8px; }
    .chip:hover { background: #f4f1ea; }
    .todo { padding: 8px 10px; border: 1px solid #ece5d6; background: #fff; margin-bottom: 6px;
      display: flex; gap: 8px; align-items: center; }
    .todo .tt { flex: 1; font-size: 12.5px; line-height: 1.35; }
    .ic { border: 0; background: transparent; cursor: pointer; color: #8a8271; font-size: 15px; padding: 2px 5px; }
    .ic:hover { color: #1a1a1a; }
    .scroll { overflow-y: auto; flex: 1; }
    .sec { border-bottom: 1px solid #efe9dc; padding: 13px 14px; }
    .sh { font-size: 11px; text-transform: uppercase; letter-spacing: .07em; color: #8a8271; margin: 0 0 9px;
      display: flex; align-items: center; gap: 7px; }
    .sh .n { background: #ece5d6; color: #6b6355; font-size: 10px; padding: 1px 6px; }
    .head { display: flex; align-items: flex-start; gap: 10px; }
    .grade { flex: none; min-width: 44px; height: 44px; padding: 0 8px; display: flex; align-items: center;
      justify-content: center; font-weight: 700; font-size: 19px; color: #fff; background: #6b6355; }
    .grade.g-a { background: #9a7b3f; } .grade.g-b { background: #55606b; } .grade.g-c { background: #8a8271; }
    /* initials avatar with a grade badge */
    .idw { position: relative; flex: none; }
    .ava2 { width: 46px; height: 46px; border-radius: 50%; background: #efe7d4; color: #7a6a3f;
      display: grid; place-items: center; font-weight: 600; font-size: 15px; letter-spacing: .02em; }
    .gbadge { position: absolute; right: -4px; bottom: -4px; min-width: 20px; height: 18px; padding: 0 4px;
      border-radius: 9px; display: flex; align-items: center; justify-content: center; font-weight: 700;
      font-size: 10px; color: #fff; background: #6b6355; border: 2px solid #fbfaf7; }
    .gbadge.g-a { background: #9a7b3f; } .gbadge.g-b { background: #55606b; } .gbadge.g-c { background: #8a8271; }
    /* handle grade chip (shown collapsed when a client is recognised) */
    .handle .hg { writing-mode: horizontal-tb; color: #fff; font-size: 10px; font-weight: 700;
      padding: 2px 5px; margin-bottom: 3px; letter-spacing: .02em; }
    /* skeleton shimmer while a client loads */
    .sk-row { height: 12px; margin: 8px 0; border-radius: 2px;
      background: linear-gradient(90deg, #ece5d6 25%, #f6f2ea 40%, #ece5d6 60%); background-size: 300% 100%;
      animation: shine 1.25s ease-in-out infinite; }
    .sk-row.gr { width: 46px; height: 46px; border-radius: 50%; margin: 0; flex: none; }
    /* collapsible sections */
    .sh { cursor: pointer; user-select: none; }
    .sh::after { content: "⌄"; margin-left: auto; color: #b3ab97; font-size: 14px; line-height: 1; transition: transform .2s; }
    .sec.folded .sh::after { transform: rotate(-90deg); }
    .sec.folded > :not(.sh) { display: none !important; }
    @media (prefers-reduced-motion: no-preference) {
      .fadein { animation: hfade .32s cubic-bezier(.2,.7,.2,1) both; }
      @keyframes hfade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
      @keyframes shine { 0% { background-position: 130% 0; } 100% { background-position: -30% 0; } }
    }
    .who { flex: 1; min-width: 0; }
    .who .nm { font-weight: 600; font-size: 15px; line-height: 1.2; }
    .who .sub { color: #6b6355; font-size: 12px; margin-top: 2px; line-height: 1.35; }
    .pill { display: inline-block; margin-top: 5px; margin-right: 4px; font-size: 10px; padding: 1px 7px;
      border: 1px solid #d8cfbc; color: #6b6355; letter-spacing: .04em; text-transform: uppercase; }
    .pill.play { background: #efe7d4; border-color: #d8cfbc; color: #7a6a3f; }
    .box { margin-top: 10px; padding: 8px 10px; background: #f2efe6; border: 1px solid #ece5d6; }
    .box.basket { background: #f6efe0; border-color: #e7d9bd; }
    .box .k { font-size: 10px; color: #6b6355; text-transform: uppercase; letter-spacing: .05em; }
    .box .v { font-size: 16px; font-weight: 700; margin-top: 1px; }
    .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: #6b6355; margin: 11px 0 5px; }
    .reasons { list-style: none; margin: 0; padding: 0; }
    .reasons li { padding: 3px 0 3px 13px; position: relative; line-height: 1.35; font-size: 12.5px; }
    .reasons li:before { content: "·"; position: absolute; left: 3px; color: #9a7b3f; font-weight: 700; }
    .reco { line-height: 1.4; color: #33302a; font-size: 12.5px; }
    .acts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .btn { border: 1px solid #d8cfbc; background: #fff; color: #1a1a1a; padding: 6px 10px; cursor: pointer;
      font-size: 12px; text-decoration: none; display: inline-block; }
    .btn:hover { background: #f4f1ea; }
    .btn.primary { background: #1a1a1a; color: #fbfaf7; border-color: #1a1a1a; }
    .btn.primary:hover { background: #333; }
    .mini { border: 1px solid #d8cfbc; background: #fff; color: #1a1a1a; cursor: pointer; font-size: 12px;
      padding: 1px 7px; line-height: 1.5; }
    .mini:hover { background: #f4f1ea; }
    input.psearch { flex: 1; padding: 7px 9px; border: 1px solid #d8cfbc; background: #fff; font-size: 12.5px;
      font-family: inherit; color: #1a1a1a; }
    .tot { margin-top: 7px; font-weight: 600; font-size: 13px; }
    .pth { width: 38px; height: 38px; object-fit: cover; border: 1px solid #ece5d6; flex: none;
      background: #f2efe6; }
    .tlist { border: 1px solid #ece5d6; max-height: 196px; overflow-y: auto; margin-bottom: 8px; background: #fff; }
    .tcat { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: #8a8271;
      padding: 8px 8px 3px; background: #faf7f0; position: sticky; top: 0; }
    .titem { display: block; width: 100%; text-align: left; border: 0; background: transparent;
      padding: 6px 8px; font-size: 12.5px; color: #1a1a1a; cursor: pointer; border-left: 2px solid transparent; }
    .titem:hover { background: #f4f1ea; }
    .titem.sel { background: #f2efe6; border-left-color: #9a7b3f; font-weight: 600; }
    select { width: 100%; padding: 6px; border: 1px solid #d8cfbc; background: #fff; font-size: 12px; }
    textarea { width: 100%; padding: 7px 9px; border: 1px solid #d8cfbc; background: #fff; font-size: 12.5px;
      font-family: inherit; resize: vertical; color: #1a1a1a; }
    .prev { margin-top: 6px; padding: 8px; background: #f6f3ec; border: 1px solid #ece5d6; font-size: 12px;
      line-height: 1.4; white-space: pre-wrap; max-height: 116px; overflow-y: auto; }
    .dbox { border: 1px solid #ece5d6; background: #fbf9f4; padding: 9px; margin-bottom: 11px; }
    .dbox .sh { margin: 0 0 7px; }
    textarea.dinstr { width: 100%; box-sizing: border-box; border: 1px solid #d8cfbc; background: #fff;
      font: inherit; font-size: 12.5px; padding: 7px 9px; resize: vertical; min-height: 32px; color: #1a1a1a; }
    .dsrc { font-size: 10.5px; text-transform: uppercase; letter-spacing: .05em; color: #8a8271; margin-top: 6px; }
    .urg { background: #ece5d6; color: #6b6355; font-size: 10px; padding: 1px 6px; letter-spacing: 0;
      text-transform: none; margin-left: 6px; }
    .bsum { margin-top: 9px; font-size: 12.5px; line-height: 1.5; color: #1a1a1a; }
    .blist { margin-top: 9px; display: flex; flex-direction: column; gap: 5px; }
    .bact { display: block; width: 100%; text-align: left; font: inherit; padding: 7px 9px;
      border: 1px solid #ece5d6; background: #fff; cursor: pointer; }
    .bact:hover { background: #f4f1ea; border-color: #d8cfbc; }
    .bact.note { cursor: default; background: transparent; border-style: dashed; }
    .bact b { display: block; font-size: 12.5px; font-weight: 600; color: #1a1a1a; }
    .bact i { display: block; font-style: normal; font-size: 11.5px; color: #6b6355; margin-top: 1px; }
    .row { padding: 8px 10px; border: 1px solid #ece5d6; background: #fff; margin-bottom: 7px; }
    .row .rn { font-weight: 600; font-size: 13px; }
    .row .rd { font-size: 11.5px; color: #6b6355; margin-top: 1px; }
    .row .live { color: #3f7a4f; font-weight: 600; }
    .muted { color: #6b6355; line-height: 1.45; font-size: 12.5px; }
    .warn { margin-top: 9px; padding: 7px 10px; background: #f7ede0; border: 1px solid #e6ceac;
      color: #86602a; font-size: 12px; line-height: 1.35; }
    .warn b { color: #6b481c; }
    .link { color: #9a7b3f; text-decoration: underline; cursor: pointer; font-size: 12px; }
    .foot { flex: none; padding: 9px 14px; border-top: 1px solid #eee7da; font-size: 11px; color: #9a9280;
      display: flex; align-items: center; gap: 6px; }
    .toast { position: fixed; right: 356px; bottom: 22px; background: #1a1a1a; color: #fff; font-size: 11px;
      padding: 5px 10px; opacity: 0; transition: opacity .15s; pointer-events: none; z-index: 2147483647; }
    .toast.on { opacity: 1; }
  `;

  let host = null, root = null, open = true, inserter = null, channel = "email";
  let ctx = null, client = null; // ctx = standing context; client = active client state
  let cart = [], prodResults = [], cartBase = ""; // the working cart + last product search
  let mode = "clienteling"; // "clienteling" (client-facing) | "internal" (team coordination)
  let tplQuery = "", tplSel = null;   // template search text + selected index
  let threadReader = null;            // surface-supplied () => [{from,text}] of the visible chat
  let draftInstr = "";                // the associate's optional "what to say" note
  let draft = null;                   // { text, source, busy, error, aiAvailable }
  let animKey = "";                   // last client key animated (so we fade in only on a new client)
  const folded = new Set();           // collapsed section names, persisted
  const contactHist = {};   // cid -> last outreach {at,by,action,note} | null | "pending"

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function money(v) { return "£" + Number(v || 0).toLocaleString(); }
  function gradeClass(g) {
    g = String(g || "").trim().toUpperCase();
    return g[0] === "A" ? "g-a" : g[0] === "B" ? "g-b" : g[0] === "C" ? "g-c" : "";
  }
  function gradeBg(g) {
    g = String(g || "").trim().toUpperCase();
    return g[0] === "A" ? "#9a7b3f" : g[0] === "B" ? "#55606b" : g[0] === "C" ? "#8a8271" : "#6b6355";
  }
  function initials(s) {
    s = String(s || "").trim();
    if (!s) return "·";
    if (s.indexOf("@") >= 0) {
      const l = s.split("@")[0].replace(/[^a-zA-Z]/g, "");
      return (l.slice(0, 2) || "·").toUpperCase();
    }
    const p = s.split(/\s+/).filter(Boolean);
    return (((p[0] || "")[0] || "") + ((p[1] || "")[0] || "")).toUpperCase() || "·";
  }
  function paintHandle() {
    const h = root && root.querySelector(".handle"); if (!h) return;
    const g = client && client.data && client.data.grade;
    let chip = h.querySelector(".hg");
    if (g) {
      if (!chip) { chip = document.createElement("span"); chip.className = "hg"; h.insertBefore(chip, h.firstChild); }
      chip.textContent = g; chip.style.background = gradeBg(g);
    } else if (chip) { chip.remove(); }
  }
  function applyFolds() {
    ["client", "team", "tpl", "camp", "prod", "cat"].forEach((n) => {
      const el = sec(n); if (el) el.classList.toggle("folded", folded.has(n));
    });
  }
  function toggleFold(name) {
    if (folded.has(name)) folded.delete(name); else folded.add(name);
    applyFolds();
    try { chrome.storage.local.set({ folded: Array.from(folded) }); } catch (e) { /* ignore */ }
  }
  function appendUtm(url, utm) {
    if (!url) return "";
    let base = url, frag = "";
    const hi = url.indexOf("#");
    if (hi >= 0) { frag = url.slice(hi); base = url.slice(0, hi); }
    const q = ["source", "medium", "campaign", "content"].filter((k) => utm[k])
      .map((k) => "utm_" + k + "=" + encodeURIComponent(utm[k])).join("&");
    return q ? base + (base.indexOf("?") >= 0 ? "&" : "?") + q + frag : url;
  }
  function activeFirst() {
    const n = client && client.data && client.data.name;
    return n ? String(n).split(" ")[0] : "there";
  }
  function copy(text, msg) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => toast(msg || "Copied"), () => toast("Copy failed"));
  }
  function place(text) { const ok = inserter && inserter(text); toast(ok ? "Inserted" : "Open a reply first"); }
  function ago(iso) {
    const t = Date.parse(iso); if (!t) return "";
    const s = (Date.now() - t) / 1000;
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    if (s < 86400) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  }
  function fetchHistory(cid) {
    try {
      chrome.runtime.sendMessage({ type: "halia:history", cid }, (r) => {
        contactHist[cid] = (r && !r.error && r.last_contact) ? r.last_contact : null;
        renderClient();
      });
    } catch (e) { contactHist[cid] = null; }
  }
  function act(body, okMsg) {
    try {
      chrome.runtime.sendMessage({ type: "halia:action", body }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) toast((r && r.detail) || "Couldn't complete that");
        else toast(okMsg);
      });
    } catch (e) { toast("Action failed"); }
  }
  function activeCid() { return client && client.data && client.data.cid; }
  function activeName() { return (client && client.data && client.data.name) || ""; }
  function logContact(cid, name, reason) {
    act({ action: "contacted", cid, client_name: name, reason: reason || "" },
      "Logged" + (ctx && ctx.slack ? " and told the team" : ""));
    if (cid) { delete contactHist[cid]; renderClient(); }   // refresh the 'last contacted' cue
  }

  const _CONTACT_REASONS = ["Sent a note", "Called", "WhatsApp", "Booked appointment", "Followed up"];
  const _TEAM_MSGS = ["I'm looking after {client}", "I've just contacted {client}",
    "{client} needs a follow-up", "Taking {client} from here"];

  function ensure() {
    if (root) return;
    host = document.createElement("div");
    host.id = "halia-badge-host";
    host.style.all = "initial";
    (document.body || document.documentElement).appendChild(host);
    root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    root.appendChild(style);
    const dock = document.createElement("div");
    dock.className = "dock" + (open ? " open" : "");
    dock.innerHTML = `
      <button class="handle" data-a="open"><span class="m">⁂</span>Halia</button>
      <aside class="panel">
        <div class="bar"><span class="m">⁂</span><span class="t">Halia</span><span class="sp"></span>
          <button class="modebtn" data-a="mode" title="Switch between client and team mode">Clienteling</button>
          <button class="ic" data-a="refresh" title="Refresh">⟳</button>
          <button class="ic" data-a="close" title="Collapse">›</button></div>
        <div class="scroll">
          <section class="sec" data-s="client"></section>
          <section class="sec" data-s="team"></section>
          <section class="sec" data-s="tpl"></section>
          <section class="sec" data-s="camp"></section>
          <section class="sec" data-s="prod"></section>
          <section class="sec" data-s="cat"></section>
        </div>
        <div class="foot"><span class="m" style="color:#8a7a4f">⁂</span> Read live from your book. Nothing stored.</div>
      </aside>
      <div class="toast">Copied</div>`;
    root.appendChild(dock);
    dock.querySelector('[data-a="open"]').onclick = () => setOpen(true);
    dock.querySelector('[data-a="close"]').onclick = () => setOpen(false);
    dock.querySelector('[data-a="refresh"]').onclick = () => window.dispatchEvent(new CustomEvent("halia:refresh"));
    dock.querySelector('[data-a="mode"]').onclick = () => setMode(mode === "internal" ? "clienteling" : "internal");
    // collapse a section by tapping its header (delegated, so it survives re-renders)
    dock.querySelector(".scroll").addEventListener("click", (e) => {
      const sh = e.target.closest(".sh"); if (!sh) return;
      const s = sh.closest(".sec"); if (s && s.dataset.s) toggleFold(s.dataset.s);
    });
    renderTemplates(); renderCampaigns(); renderProducts(); renderCatalogue();
    applyMode(); applyFolds(); paintHandle();
  }

  function setMode(m, persist) {
    mode = m === "internal" ? "internal" : "clienteling";
    if (persist !== false) { try { chrome.storage.local.set({ haliaMode: mode }); } catch (e) { /* ignore */ } }
    if (root) applyMode();
  }
  function applyMode() {
    const internal = mode === "internal";
    const show = (name, on) => { const el = sec(name); if (el) el.style.display = on ? "" : "none"; };
    show("team", internal);
    show("tpl", !internal); show("camp", !internal); show("prod", !internal); show("cat", !internal);
    const tg = root && root.querySelector('[data-a="mode"]');
    if (tg) { tg.textContent = internal ? "Internal" : "Clienteling"; tg.classList.toggle("int", internal); }
    renderClient(); renderTeam();
  }

  function setOpen(v) {
    open = v;
    const dock = root && root.querySelector(".dock");
    if (dock) dock.classList.toggle("open", v);
    try { chrome.storage.local.set({ panelOpen: v }); } catch (e) { /* ignore */ }
  }

  function toast(msg) {
    const t = root && root.querySelector(".toast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("on");
    setTimeout(() => t.classList.remove("on"), 1100);
  }

  function sec(name) { return root && root.querySelector(`[data-s="${name}"]`); }

  // ── CLIENT ────────────────────────────────────────────────────────────────
  function renderClient() {
    const el = sec("client"); if (!el) return;
    if (!client) { el.innerHTML = `<div class="sh">Client</div>
      <div class="muted">Open a chat or email and Halia shows who they are, their grade and the next move.</div>`;
      return; }
    if (client.loading) { el.innerHTML = `<div class="sh">Client</div>
      <div class="head" style="align-items:center">
        <div class="sk-row gr"></div>
        <div style="flex:1"><div class="sk-row" style="width:62%"></div><div class="sk-row" style="width:40%"></div></div>
      </div>
      <div class="sk-row" style="height:32px;margin-top:14px"></div>
      <div class="sk-row" style="width:92%"></div><div class="sk-row" style="width:74%"></div>`; return; }
    if (client.error) { el.innerHTML = `<div class="sh">Client</div><div class="muted">${esc(client.error)}</div>`; return; }
    if (client.notfound) { el.innerHTML = `<div class="sh">Client</div>
      <div class="muted">No Halia signal for ${esc(client.name || "this client")}. Not a flagged client in your book.</div>`;
      return; }
    const d = client.data || {};
    const gc = gradeClass(d.grade);
    const cart = d.cart && d.cart.value ? d.cart : null;
    const sub = [d.email, d.ordersCount != null ? d.ordersCount + " orders" : null,
      d.spend != null ? money(d.spend) + " spent" : null, d.last ? "last " + d.last : null]
      .filter(Boolean).join(" · ");
    const reasons = (d.reasons || []).slice(0, 5);
    const h = d.cid ? contactHist[d.cid] : null;
    let cue = "";
    if (h && typeof h === "object" && h.at) {
      const by = h.by ? " by " + esc(h.by) : "";
      const verb = h.action === "note" ? "Note added" : "Contacted";
      cue = `<div class="warn">${verb} <b>${esc(ago(h.at))}</b>${by}${h.note ? ` · “${esc(h.note)}”` : ""}</div>`;
    }
    const acts = [];
    if (d.cid && ctx && ctx.platform === "shopify") acts.push(`<button class="btn" data-a="pipe">Add to pipeline</button>`);
    if (d.adminUrl) acts.push(`<a class="btn" href="${esc(d.adminUrl)}" target="_blank" rel="noopener">Open in store</a>`);
    if (d.dashboard) acts.push(`<a class="btn primary" href="${esc(d.dashboard)}" target="_blank" rel="noopener">Open in Halia</a>`);
    const key = d.cid || d.email || d.name || "";
    const anim = key !== animKey ? " fadein" : ""; animKey = key;
    el.innerHTML = `
      <div class="sh">Client</div>
      <div class="head${anim}">
        <div class="idw">
          <div class="ava2">${esc(initials(d.name || d.email || ""))}</div>
          ${d.grade ? `<div class="gbadge ${gc}">${esc(d.grade)}</div>` : ""}
        </div>
        <div class="who">
          <div class="nm">${esc(d.name || d.email || "This client")}</div>
          ${sub ? `<div class="sub">${esc(sub)}</div>` : ""}
          ${d.playLabel ? `<span class="pill play">${esc(d.playLabel)}</span>` : ""}
          ${d.hidden ? `<span class="pill">Hidden VIC</span>` : ""}
        </div>
      </div>
      ${cue}
      ${d.latent ? `<div class="box"><div class="k">Latent value</div><div class="v">${esc(d.latent)}</div></div>` : ""}
      ${cart ? `<div class="box basket"><div class="k">Open basket</div>
        <div class="v">${money(cart.value)}${cart.count ? ` <span style="font-weight:400;font-size:11px;color:#6b6355">${esc(cart.count)} item${cart.count === 1 ? "" : "s"}</span>` : ""}</div>
        ${cart.url ? `<a class="link" href="${esc(cart.url)}" target="_blank" rel="noopener">Open checkout</a>` : ""}</div>` : ""}
      ${d.action ? `<div class="lbl">Next move</div><div class="reco">${esc(d.action)}</div>` : ""}
      ${reasons.length ? `<div class="lbl">Why</div><ul class="reasons">${reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      <div class="acts">${acts.join("")}</div>
      ${d.cid && ctx && ctx.platform === "shopify" ? `<div class="lbl">Note</div>
        <textarea data-a="note" rows="2" placeholder="Jot a note — saved to this customer in your Shopify"></textarea>
        <div class="acts"><button class="btn" data-a="notesave">Save note</button></div>` : ""}`;
    if (d.cid && ctx && ctx.platform === "shopify" && !(d.cid in contactHist)) {
      contactHist[d.cid] = "pending"; fetchHistory(d.cid);   // load the shared contact log once
    }
    const pipe = el.querySelector('[data-a="pipe"]');
    if (pipe) pipe.onclick = () => act({ action: "pipeline", cid: d.cid }, "Added to pipeline");
    const ns = el.querySelector('[data-a="notesave"]');
    if (ns) ns.onclick = () => {
      const ta = el.querySelector('[data-a="note"]');
      const v = ((ta && ta.value) || "").trim();
      if (!v) { toast("Write a note first"); return; }
      act({ action: "note", cid: d.cid, note: v }, "Note saved");
      if (ta) ta.value = "";
    };
  }

  // ── TEAM (internal mode) ──────────────────────────────────────────────────
  function renderTeam() {
    const el = sec("team"); if (!el) return;
    const todos = (ctx && ctx.todos) || [];
    const cname = activeName();
    const fill = (m) => m.replace("{client}", cname || "this client");
    el.innerHTML = `
      <div class="sh">Team</div>
      <div class="muted" style="margin-bottom:11px">${ctx && ctx.slack
        ? "Contact logs post to your team Slack, so nobody double-messages a client."
        : "Connect Slack in Halia → Settings to broadcast contact logs to your team."}</div>
      ${activeCid() ? `<div class="lbl">Log that you contacted ${esc(cname || "this client")}</div>
        <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:6px">
          ${_CONTACT_REASONS.map((x) => `<button class="chip" data-lr="${esc(x)}">${esc(x)}</button>`).join("")}
        </div>
        <div style="display:flex;gap:6px;margin-bottom:13px">
          <input data-a="lreason" placeholder="Reason (optional)" style="flex:1;padding:7px 9px;border:1px solid #d8cfbc;font-size:12.5px;color:#1a1a1a;background:#fff">
          <button class="btn primary" data-a="logc">Log</button>
        </div>` : ""}
      <div class="lbl">Message the team</div>
      <div style="margin-bottom:13px">${_TEAM_MSGS.map((m, i) => `<div class="row" style="display:flex;gap:6px;align-items:center">
        <span style="flex:1">${esc(fill(m))}</span>
        ${inserter ? `<button class="mini" data-tmi="${i}">Insert</button>` : ""}
        <button class="mini" data-tmc="${i}">Copy</button></div>`).join("")}</div>
      <div class="lbl">To-dos ${todos.length ? `<span class="n">${todos.length}</span>` : ""}</div>
      ${todos.length ? todos.map((t, i) => `<div class="todo"><span class="tt">${esc(t.text)}</span>${t.cid ? `<button class="mini" data-td="${i}">Contacted</button>` : ""}</div>`).join("")
        : `<div class="muted">Nothing needs the team right now.</div>`}`;
    el.querySelectorAll("[data-lr]").forEach((b) => b.onclick = () => {
      const inp = el.querySelector('[data-a="lreason"]'); if (inp) inp.value = b.dataset.lr;
    });
    const logc = el.querySelector('[data-a="logc"]');
    if (logc) logc.onclick = () => {
      const inp = el.querySelector('[data-a="lreason"]');
      logContact(activeCid(), cname, (inp && inp.value) || "");
      if (inp) inp.value = "";
    };
    _TEAM_MSGS.forEach((m, i) => {
      const ins = el.querySelector(`[data-tmi="${i}"]`); if (ins) ins.onclick = () => place(fill(m));
      const cp = el.querySelector(`[data-tmc="${i}"]`); if (cp) cp.onclick = () => copy(fill(m), "Copied");
    });
    todos.forEach((t, i) => {
      const b = el.querySelector(`[data-td="${i}"]`);
      if (b) b.onclick = () => logContact(t.cid, t.name, "");
    });
  }

  // ── TEMPLATES ─────────────────────────────────────────────────────────────
  function templateList() {
    const t = client && client.data && client.data.templates;
    return (t && t.length ? t : (ctx && ctx.templates) || []);
  }

  // ── THE BRIEF ─────────────────────────────────────────────────────────────
  // Reads the client on screen plus the visible conversation and asks Halia for one brief: where
  // the relationship stands, the next moves worth making, and a ready-to-send reply. Works without
  // AI too: the backend falls back to the scored book and the merchant's best-matching template.
  function collectThread() {
    try { return threadReader ? (threadReader() || []) : []; } catch (e) { return []; }
  }
  function draftErr(r) {
    const e = r && r.error;
    if (e === "no-token") return "Add your Halia token in the options to use this.";
    if (e === "unauthorized") return "Your token is not recognised. Re-generate it in Settings.";
    if (e === "network") return "Could not reach Halia. Check the address in the options.";
    return "Could not read that just now. Please try again.";
  }
  function runBrief() {
    const d = (client && client.data) || {};
    draft = Object.assign({}, draft, { busy: true, error: "" });
    renderTemplates();
    const body = { cid: d.cid || "", email: d.email || "", phone: d.phone || "", name: d.name || "",
      channel, instruction: draftInstr, thread: collectThread() };
    try {
      chrome.runtime.sendMessage({ type: "halia:brief", body }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) {
          draft = { busy: false, error: draftErr(r) };
        } else {
          draft = { busy: false, error: "", summary: r.summary || "", text: r.reply || "",
            urgency: r.urgency || "", actions: r.actions || [], campaign: r.campaign || null,
            read: r.read_thread || 0, source: r.source || "book", aiAvailable: r.ai_available };
        }
        renderTemplates();
      });
    } catch (e) { draft = { busy: false, error: "Brief failed" }; renderTemplates(); }
  }
  // An action is a button when the toolbar can actually carry it out, and a note otherwise.
  const _DOABLE = { pipeline: 1, campaign: 1, contacted: 1, catalogue: 1 };
  function doAction(a) {
    const cid = activeCid();
    if (a.kind === "pipeline" && cid) return act({ action: "pipeline", cid }, "Added to your list");
    if (a.kind === "campaign" && cid && draft && draft.campaign) {
      return act({ action: "campaign_add", campaign_id: draft.campaign.id, cid },
        "Added to " + draft.campaign.name);
    }
    if (a.kind === "contacted" && cid) return logContact(cid, activeName(), a.label || "");
    if (a.kind === "catalogue" && ctx && ctx.catalog) return place(ctx.catalog);
    toast("Nothing to do here yet");
  }
  function canDo(a) {
    if (!_DOABLE[a.kind]) return false;
    if (a.kind === "campaign") return !!(activeCid() && draft && draft.campaign);
    if (a.kind === "catalogue") return !!(ctx && ctx.catalog && inserter);
    return !!activeCid();
  }
  function draftBoxHtml() {
    const busy = draft && draft.busy;
    const has = draft && draft.text;
    const label = busy ? "Reading…"
      : (has ? "Read again" : (threadReader ? "Read this conversation" : "Brief me on this client"));
    const srcLine = has
      ? (draft.source === "ai"
          ? "Read by Halia" + (draft.read ? " · " + draft.read + " message" + (draft.read === 1 ? "" : "s") : "")
          : "From your book") +
        (draft.aiAvailable === false && draft.source !== "ai"
          ? " · add an AI key in Halia for a written brief" : "")
      : "";
    const acts = (draft && draft.actions) || [];
    return `<div class="dbox">
      <div class="sh">The brief${draft && draft.urgency && has ? ` <span class="urg">${esc(draft.urgency)}</span>` : ""}</div>
      <div class="acts">
        <button class="btn primary" data-a="brief"${busy ? " disabled" : ""}>${label}</button>
      </div>
      ${draft && draft.error ? `<div class="muted" style="margin-top:7px">${esc(draft.error)}</div>` : ""}
      ${draft && draft.summary ? `<div class="bsum">${esc(draft.summary)}</div>` : ""}
      ${acts.length ? `<div class="blist">${acts.map((a, i) => canDo(a)
        ? `<button class="bact" data-ba="${i}"><b>${esc(a.label)}</b><i>${esc(a.why || "")}</i></button>`
        : `<div class="bact note"><b>${esc(a.label)}</b><i>${esc(a.why || "")}</i></div>`).join("")}</div>` : ""}
      ${has ? `<div class="prev" style="margin-top:9px">${esc(draft.text)}</div>
        <div class="dsrc">${esc(srcLine)}</div>
        <div class="acts">
          ${inserter ? `<button class="btn primary" data-a="dins">Insert</button>` : ""}
          <button class="btn" data-a="dcopy">Copy</button>
        </div>
        <textarea class="dinstr" data-a="dinstr" rows="1" placeholder="Steer the reply, then Read again">${esc(draftInstr)}</textarea>` : ""}
    </div>`;
  }
  function wireDraft(el) {
    const ta = el.querySelector('[data-a="dinstr"]');
    if (ta) ta.oninput = () => { draftInstr = ta.value; };   // store without a re-render, to keep focus
    const b = el.querySelector('[data-a="brief"]'); if (b) b.onclick = runBrief;
    el.querySelectorAll("[data-ba]").forEach((n) => {
      n.onclick = () => doAction(((draft && draft.actions) || [])[+n.dataset.ba] || {});
    });
    const di = el.querySelector('[data-a="dins"]'); if (di) di.onclick = () => place(draft.text);
    const dc = el.querySelector('[data-a="dcopy"]'); if (dc) dc.onclick = () => copy(draft.text, "Reply copied");
  }

  function renderTemplates() {
    const el = sec("tpl"); if (!el) return;
    const list = templateList();
    if (!list.length) {
      el.innerHTML = draftBoxHtml() + `<div class="sh">Templates</div>
        <div class="muted">Add outreach templates in Halia → Settings → Templates.</div>`;
      wireDraft(el); return;
    }
    const fill = (s) => String(s || "").split("{first_name}").join(activeFirst());
    const q = tplQuery.trim().toLowerCase();
    const matches = list.map((t, i) => ({ t, i }))
      .filter(({ t }) => !q || ((t.name || "") + " " + (t.category || "") + " " + (t.body || "")).toLowerCase().includes(q));
    // group by category, preserving first-seen order
    const groups = []; const idx = {};
    matches.forEach(({ t, i }) => {
      const c = t.category || "General";
      if (!(c in idx)) { idx[c] = groups.length; groups.push({ cat: c, items: [] }); }
      groups[idx[c]].items.push({ t, i });
    });
    const sel = (tplSel != null && list[tplSel]) ? list[tplSel] : null;
    el.innerHTML = draftBoxHtml() + `
      <div class="sh">Templates <span class="n">${list.length}</span></div>
      <input class="psearch" data-a="tsearch" placeholder="Search templates" value="${esc(tplQuery)}" style="margin-bottom:8px">
      <div class="tlist">${groups.length
        ? groups.map((g) => `<div class="tcat">${esc(g.cat)}</div>` +
            g.items.map(({ t, i }) => `<button class="titem${i === tplSel ? " sel" : ""}" data-ti="${i}">${esc(t.name || ("Template " + (i + 1)))}</button>`).join("")).join("")
        : `<div class="muted" style="padding:10px">No templates match.</div>`}</div>
      ${sel ? `<div class="prev">${esc(fill(sel.body))}</div>
        <div class="acts">
          ${inserter ? `<button class="btn primary" data-a="tins">Insert</button>` : ""}
          <button class="btn" data-a="tcopy">Copy</button>
          <button class="btn" data-a="tcopys">Copy subject</button>
        </div>` : `<div class="muted">Pick a template above.</div>`}`;
    const search = el.querySelector('[data-a="tsearch"]');
    if (search) search.oninput = () => {
      tplQuery = search.value; renderTemplates();
      const s2 = sec("tpl") && sec("tpl").querySelector('[data-a="tsearch"]');
      if (s2) { s2.focus(); s2.setSelectionRange(s2.value.length, s2.value.length); }
    };
    el.querySelectorAll("[data-ti]").forEach((b) => b.onclick = () => { tplSel = +b.dataset.ti; renderTemplates(); });
    const body = () => fill((list[tplSel] || {}).body);
    const ins = el.querySelector('[data-a="tins"]'); if (ins) ins.onclick = () => place(body());
    const cp = el.querySelector('[data-a="tcopy"]'); if (cp) cp.onclick = () => copy(body(), "Message copied");
    const cs = el.querySelector('[data-a="tcopys"]'); if (cs) cs.onclick = () => copy(fill((list[tplSel] || {}).subject), "Subject copied");
    wireDraft(el);
  }

  // ── CAMPAIGNS ─────────────────────────────────────────────────────────────
  function taggedCatalog(utmCampaign) {
    if (!ctx || !ctx.catalog) return "";
    const cm = CHAN[channel] || CHAN.email;
    return appendUtm(ctx.catalog, { source: cm[0], medium: cm[1], campaign: utmCampaign });
  }
  function renderCampaigns() {
    const el = sec("camp"); if (!el) return;
    const camps = (ctx && ctx.campaigns) || [];
    const running = camps.filter((c) => c.running);
    const show = (running.length ? running : camps).slice(0, 6);
    if (!show.length) { el.innerHTML = `<div class="sh">Campaigns</div>
      <div class="muted">No campaigns yet. Create one in Halia → Campaigns.</div>`; return; }
    el.innerHTML = `<div class="sh">${running.length ? "Running now" : "Campaigns"} <span class="n">${show.length}</span></div>` +
      show.map((c, i) => `<div class="row">
        <div class="rn">${esc(c.name)}</div>
        <div class="rd">${c.running ? `<span class="live">● live</span> · ` : ""}${esc(c.starts)} → ${esc(c.ends)}${c.members ? ` · ${c.members} client${c.members === 1 ? "" : "s"}` : ""}</div>
        <div class="acts">
          ${activeCid() ? `<button class="btn primary" data-cadd="${i}">Add this client</button>` : ""}
          ${ctx.catalog && inserter ? `<button class="btn" data-ci="${i}">Insert catalogue link</button>` : ""}
          ${ctx.catalog ? `<button class="btn" data-cc="${i}">Copy catalogue link</button>` : ""}
          <button class="btn" data-cu="${i}">Copy UTM</button>
        </div></div>`).join("");
    show.forEach((c, i) => {
      const link = () => taggedCatalog(c.utm);
      const ins = el.querySelector(`[data-ci="${i}"]`); if (ins) ins.onclick = () => place(link());
      const cc = el.querySelector(`[data-cc="${i}"]`); if (cc) cc.onclick = () => copy(link(), "Tagged link copied");
      const cu = el.querySelector(`[data-cu="${i}"]`); if (cu) cu.onclick = () => {
        const cm = CHAN[channel] || CHAN.email;
        copy("utm_source=" + cm[0] + "&utm_medium=" + cm[1] + "&utm_campaign=" + c.utm, "UTM copied");
      };
      const ca = el.querySelector(`[data-cadd="${i}"]`);
      if (ca) ca.onclick = () => act({ action: "campaign_add", campaign_id: c.id, cid: activeCid() },
        "Added to " + c.name);
    });
  }

  // ── PRODUCTS / CART BUILDER (Shopify) ─────────────────────────────────────
  function cartLink() {
    if (!cartBase || !cart.length) return "";
    const items = cart.map((i) => i.id + ":" + i.qty).join(",");
    let url = cartBase.replace(/\/$/, "") + "/cart/" + items;
    const camp = ((ctx && ctx.campaigns) || []).find((c) => c.running);   // attribute to a live campaign
    if (camp) {
      const cm = CHAN[channel] || CHAN.email;
      url = appendUtm(url, { source: cm[0], medium: cm[1], campaign: camp.utm });
    }
    return url;
  }
  function addToCart(v, ptitle) {
    const ex = cart.find((i) => i.id === v.id);
    if (ex) ex.qty += 1;
    else cart.push({ id: v.id, qty: 1, price: v.price,
      label: ptitle + (v.title && v.title !== "Default Title" ? " · " + v.title : "") });
    paintCart(); toast("Added to cart");
  }
  function paintResults() {
    const box = root && root.querySelector('[data-a="presults"]'); if (!box) return;
    if (!prodResults.length) { box.innerHTML = ""; return; }
    box.innerHTML = prodResults.slice(0, 20).map((p, pi) => {
      const vs = p.variants || [];
      const single = vs.length === 1;
      const opts = vs.map((v, vi) => `<option value="${vi}">${esc(v.title || "Default")}${v.price ? " · £" + esc(v.price) : ""}</option>`).join("");
      return `<div class="row" style="display:flex;gap:8px;align-items:center">
        ${p.image ? `<img class="pth" data-pi="${pi}" src="${esc(p.image)}" referrerpolicy="no-referrer" alt="">` : ""}
        <div style="flex:1;min-width:0">
          <div class="rn">${esc(p.title)}</div>
          <div style="display:flex;gap:6px;margin-top:4px;align-items:center">
            ${single ? `<span class="rd" style="flex:1">${esc(vs[0].title === "Default Title" ? "" : vs[0].title)}${vs[0].price ? " · £" + esc(vs[0].price) : ""}</span>`
              : `<select data-pv="${pi}" style="flex:1">${opts}</select>`}
            <button class="btn" data-padd="${pi}">Add</button>
          </div>
        </div></div>`;
    }).join("");
    // Attach onerror in JS (inline handlers are blocked by strict page CSPs): a blocked or missing
    // image just hides itself rather than showing a broken icon.
    box.querySelectorAll("img.pth").forEach((im) => { im.onerror = () => { im.style.display = "none"; }; });
    prodResults.forEach((p, pi) => {
      const b = box.querySelector(`[data-padd="${pi}"]`);
      if (b) b.onclick = () => {
        const sel = box.querySelector(`[data-pv="${pi}"]`);
        const v = (p.variants || [])[sel ? +sel.value : 0];
        if (v) addToCart(v, p.title);
      };
    });
  }
  function paintCart() {
    const box = root && root.querySelector('[data-a="pcart"]'); if (!box) return;
    if (!cart.length) { box.innerHTML = ""; return; }
    const total = cart.reduce((s, i) => s + (parseFloat(i.price) || 0) * i.qty, 0);
    const count = cart.reduce((s, i) => s + i.qty, 0);
    const who = client && client.data && client.data.name ? " for " + esc(String(client.data.name).split(" ")[0]) : "";
    box.innerHTML = `<div class="lbl">Cart${who} <span class="n">${count}</span></div>` +
      cart.map((i, ci) => `<div class="row" style="display:flex;align-items:center;gap:6px">
        <span style="flex:1">${esc(i.label)}</span>
        <button class="mini" data-qd="${ci}">−</button><span>${i.qty}</span><button class="mini" data-qi="${ci}">+</button>
        <button class="mini" data-rm="${ci}">✕</button></div>`).join("") +
      `<div class="tot">Total ~ £${total.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
       <div class="acts">
         ${inserter ? `<button class="btn primary" data-a="csend">Send cart</button>` : ""}
         <button class="btn" data-a="ccopy">Copy cart link</button>
         <button class="mini" data-a="cclear">Clear</button>
       </div>`;
    cart.forEach((i, ci) => {
      const qd = box.querySelector(`[data-qd="${ci}"]`); if (qd) qd.onclick = () => { i.qty = Math.max(1, i.qty - 1); paintCart(); };
      const qi = box.querySelector(`[data-qi="${ci}"]`); if (qi) qi.onclick = () => { i.qty += 1; paintCart(); };
      const rm = box.querySelector(`[data-rm="${ci}"]`); if (rm) rm.onclick = () => { cart.splice(ci, 1); paintCart(); };
    });
    const send = box.querySelector('[data-a="csend"]'); if (send) send.onclick = () => place(cartLink());
    const cp = box.querySelector('[data-a="ccopy"]'); if (cp) cp.onclick = () => copy(cartLink(), "Cart link copied");
    const cl = box.querySelector('[data-a="cclear"]'); if (cl) cl.onclick = () => { cart = []; paintCart(); };
  }
  function doProductSearch(q) {
    const box = root && root.querySelector('[data-a="presults"]');
    if (box) box.innerHTML = `<div class="muted">Searching…</div>`;
    try {
      chrome.runtime.sendMessage({ type: "halia:products", q }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) {
          prodResults = [];
          if (box) box.innerHTML = `<div class="muted">Couldn't load products.</div>`;
          return;
        }
        prodResults = r.products || [];
        if (r.cart_base) cartBase = r.cart_base;
        if (!prodResults.length && box) box.innerHTML = `<div class="muted">No products found.</div>`;
        else paintResults();
      });
    } catch (e) { /* ignore */ }
  }
  function renderProducts() {
    const el = sec("prod"); if (!el) return;
    if (!ctx || ctx.platform !== "shopify") { el.innerHTML = ""; return; }  // cart permalinks are Shopify
    el.innerHTML = `<div class="sh">Build a cart</div>
      <div style="display:flex;gap:6px">
        <input class="psearch" data-a="psearch" placeholder="Search products">
        <button class="btn" data-a="pgo">Search</button>
      </div>
      <div data-a="presults" style="margin-top:8px"></div>
      <div data-a="pcart" style="margin-top:8px"></div>`;
    const inp = el.querySelector('[data-a="psearch"]');
    const go = () => doProductSearch((inp && inp.value) || "");
    el.querySelector('[data-a="pgo"]').onclick = go;
    if (inp) inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } };
    paintResults(); paintCart();
  }

  // ── CATALOGUE ─────────────────────────────────────────────────────────────
  function renderCatalogue() {
    const el = sec("cat"); if (!el) return;
    const url = ctx && ctx.catalog;
    if (!url) { el.innerHTML = `<div class="sh">Catalogue</div>
      <div class="muted">Set an active catalogue in Halia → Catalogues.</div>`; return; }
    el.innerHTML = `<div class="sh">Catalogue</div>
      <div class="muted" style="word-break:break-all">${esc(url)}</div>
      <div class="acts">
        ${inserter ? `<button class="btn primary" data-a="catins">Insert link</button>` : ""}
        <button class="btn" data-a="catcopy">Copy link</button>
      </div>`;
    const ins = el.querySelector('[data-a="catins"]'); if (ins) ins.onclick = () => place(url);
    el.querySelector('[data-a="catcopy"]').onclick = () => copy(url, "Catalogue link copied");
  }

  const API = {
    mount() {
      ensure();
      try {
        chrome.storage.local.get(["panelOpen", "haliaMode", "folded"], (r) => {
          if (r && typeof r.panelOpen === "boolean") setOpen(r.panelOpen);
          if (r && r.haliaMode) setMode(r.haliaMode);
          if (r && Array.isArray(r.folded)) { r.folded.forEach((n) => folded.add(n)); applyFolds(); }
        });
      } catch (e) { /* ignore */ }
    },
    setContext(c) {
      ctx = c && !c.error ? c : null;
      if (root) { renderTemplates(); renderCampaigns(); renderProducts(); renderCatalogue(); renderTeam(); }
    },
    setClient(state) {
      client = state; // null | {loading,name} | {found,data} | {notfound,name} | {error}
      if (state && state.found) client = { data: state.data };
      draft = null; draftInstr = "";   // a fresh client means a fresh draft; never carry one over
      if (root) { renderClient(); renderTemplates(); renderCampaigns(); paintCart(); renderTeam(); paintHandle(); }
    },
    setInserter(fn) { inserter = fn; },
    setThreadReader(fn) { threadReader = fn; },   // surface supplies () => [{from,text}] of the chat
    setChannel(ch) { if (CHAN[ch]) channel = ch; },
    setMode(m, persist) { setMode(m, persist); },
    hide() { /* the toolbar is persistent; collapse instead of removing */ setOpen(false); }
  };

  window.HaliaPanel = API;
  window.HaliaBadge = API; // back-compat for the surface scripts
})();
