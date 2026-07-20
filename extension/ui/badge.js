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
    select { width: 100%; padding: 6px; border: 1px solid #d8cfbc; background: #fff; font-size: 12px; }
    .prev { margin-top: 6px; padding: 8px; background: #f6f3ec; border: 1px solid #ece5d6; font-size: 12px;
      line-height: 1.4; white-space: pre-wrap; max-height: 116px; overflow-y: auto; }
    .row { padding: 8px 10px; border: 1px solid #ece5d6; background: #fff; margin-bottom: 7px; }
    .row .rn { font-weight: 600; font-size: 13px; }
    .row .rd { font-size: 11.5px; color: #6b6355; margin-top: 1px; }
    .row .live { color: #3f7a4f; font-weight: 600; }
    .muted { color: #6b6355; line-height: 1.45; font-size: 12.5px; }
    .link { color: #9a7b3f; text-decoration: underline; cursor: pointer; font-size: 12px; }
    .foot { flex: none; padding: 9px 14px; border-top: 1px solid #eee7da; font-size: 11px; color: #9a9280;
      display: flex; align-items: center; gap: 6px; }
    .toast { position: fixed; right: 356px; bottom: 22px; background: #1a1a1a; color: #fff; font-size: 11px;
      padding: 5px 10px; opacity: 0; transition: opacity .15s; pointer-events: none; z-index: 2147483647; }
    .toast.on { opacity: 1; }
  `;

  let host = null, root = null, open = true, inserter = null, channel = "email";
  let ctx = null, client = null; // ctx = standing context; client = active client state

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function money(v) { return "£" + Number(v || 0).toLocaleString(); }
  function gradeClass(g) {
    g = String(g || "").trim().toUpperCase();
    return g[0] === "A" ? "g-a" : g[0] === "B" ? "g-b" : g[0] === "C" ? "g-c" : "";
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
          <button class="ic" data-a="refresh" title="Refresh">⟳</button>
          <button class="ic" data-a="close" title="Collapse">›</button></div>
        <div class="scroll">
          <section class="sec" data-s="client"></section>
          <section class="sec" data-s="tpl"></section>
          <section class="sec" data-s="camp"></section>
          <section class="sec" data-s="cat"></section>
        </div>
        <div class="foot"><span class="m" style="color:#8a7a4f">⁂</span> Read live from your book. Nothing stored.</div>
      </aside>
      <div class="toast">Copied</div>`;
    root.appendChild(dock);
    dock.querySelector('[data-a="open"]').onclick = () => setOpen(true);
    dock.querySelector('[data-a="close"]').onclick = () => setOpen(false);
    dock.querySelector('[data-a="refresh"]').onclick = () => window.dispatchEvent(new CustomEvent("halia:refresh"));
    renderClient(); renderTemplates(); renderCampaigns(); renderCatalogue();
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
      <div class="muted">Looking up ${esc(client.name || "this client")}…</div>`; return; }
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
    const acts = [];
    if (d.adminUrl) acts.push(`<a class="btn" href="${esc(d.adminUrl)}" target="_blank" rel="noopener">Open in store</a>`);
    if (d.dashboard) acts.push(`<a class="btn primary" href="${esc(d.dashboard)}" target="_blank" rel="noopener">Open in Halia</a>`);
    el.innerHTML = `
      <div class="sh">Client</div>
      <div class="head">
        <div class="grade ${gc}">${esc(d.grade || "—")}</div>
        <div class="who">
          <div class="nm">${esc(d.name || d.email || "This client")}</div>
          ${sub ? `<div class="sub">${esc(sub)}</div>` : ""}
          ${d.playLabel ? `<span class="pill play">${esc(d.playLabel)}</span>` : ""}
          ${d.hidden ? `<span class="pill">Hidden VIC</span>` : ""}
        </div>
      </div>
      ${d.latent ? `<div class="box"><div class="k">Latent value</div><div class="v">${esc(d.latent)}</div></div>` : ""}
      ${cart ? `<div class="box basket"><div class="k">Open basket</div>
        <div class="v">${money(cart.value)}${cart.count ? ` <span style="font-weight:400;font-size:11px;color:#6b6355">${esc(cart.count)} item${cart.count === 1 ? "" : "s"}</span>` : ""}</div>
        ${cart.url ? `<a class="link" href="${esc(cart.url)}" target="_blank" rel="noopener">Open checkout</a>` : ""}</div>` : ""}
      ${d.action ? `<div class="lbl">Next move</div><div class="reco">${esc(d.action)}</div>` : ""}
      ${reasons.length ? `<div class="lbl">Why</div><ul class="reasons">${reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      <div class="acts">${acts.join("")}</div>`;
  }

  // ── TEMPLATES ─────────────────────────────────────────────────────────────
  function templateList() {
    const t = client && client.data && client.data.templates;
    return (t && t.length ? t : (ctx && ctx.templates) || []);
  }
  function renderTemplates() {
    const el = sec("tpl"); if (!el) return;
    const list = templateList();
    if (!list.length) { el.innerHTML = `<div class="sh">Templates</div>
      <div class="muted">Add outreach templates in Halia → Settings → Templates.</div>`; return; }
    el.innerHTML = `<div class="sh">Templates <span class="n">${list.length}</span></div>
      <select data-a="tsel">${list.map((t, i) => `<option value="${i}">${esc(t.name || ("Template " + (i + 1)))}</option>`).join("")}</select>
      <div class="prev" data-a="tprev"></div>
      <div class="acts">
        ${inserter ? `<button class="btn primary" data-a="tins">Insert</button>` : ""}
        <button class="btn" data-a="tcopy">Copy</button>
        <button class="btn" data-a="tcopys">Copy subject</button>
      </div>`;
    const selEl = el.querySelector('[data-a="tsel"]');
    const prev = el.querySelector('[data-a="tprev"]');
    const fill = (s) => String(s || "").split("{first_name}").join(activeFirst());
    const body = () => fill((list[+selEl.value] || {}).body);
    const paint = () => { prev.textContent = body(); };
    selEl.onchange = paint; paint();
    const ins = el.querySelector('[data-a="tins"]'); if (ins) ins.onclick = () => place(body());
    el.querySelector('[data-a="tcopy"]').onclick = () => copy(body(), "Message copied");
    el.querySelector('[data-a="tcopys"]').onclick = () => copy(fill((list[+selEl.value] || {}).subject), "Subject copied");
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
          ${ctx.catalog && inserter ? `<button class="btn primary" data-ci="${i}">Insert catalogue link</button>` : ""}
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
    });
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
        chrome.storage.local.get(["panelOpen"], (r) => {
          if (r && typeof r.panelOpen === "boolean") setOpen(r.panelOpen);
        });
      } catch (e) { /* ignore */ }
    },
    setContext(c) {
      ctx = c && !c.error ? c : null;
      if (root) { renderTemplates(); renderCampaigns(); renderCatalogue(); }
    },
    setClient(state) {
      client = state; // null | {loading,name} | {found,data} | {notfound,name} | {error}
      if (state && state.found) client = { data: state.data };
      if (root) { renderClient(); renderTemplates(); }
    },
    setInserter(fn) { inserter = fn; },
    setChannel(ch) { if (CHAN[ch]) channel = ch; },
    hide() { /* the toolbar is persistent; collapse instead of removing */ setOpen(false); }
  };

  window.HaliaPanel = API;
  window.HaliaBadge = API; // back-compat for the surface scripts
})();
