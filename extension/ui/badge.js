// Halia badge — a single floating card rendered into a Shadow DOM host so the surrounding page
// (Shopify admin, Gmail, WhatsApp) can neither restyle it nor read it. Exposes window.HaliaBadge.

(function () {
  if (window.HaliaBadge) return;

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .wrap {
      position: fixed; right: 20px; bottom: 20px; width: 328px; max-width: calc(100vw - 40px);
      z-index: 2147483647; background: #fbfaf7; color: #1a1a1a;
      border: 1px solid #e3ded3; box-shadow: 0 10px 40px rgba(0,0,0,.16); font-size: 13px;
    }
    .bar { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid #eee7da;
      background: #f4f1ea; cursor: default; }
    .mark { font-size: 15px; color: #8a7a4f; }
    .bar .t { font-weight: 600; letter-spacing: .06em; text-transform: uppercase; font-size: 11px; color: #6b6355; }
    .bar .sp { flex: 1; }
    .ic { border: 0; background: transparent; cursor: pointer; color: #8a8271; font-size: 15px; line-height: 1;
      padding: 2px 4px; }
    .ic:hover { color: #1a1a1a; }
    .body { padding: 12px; max-height: 60vh; overflow-y: auto; }
    .head { display: flex; align-items: flex-start; gap: 10px; }
    .grade { flex: none; min-width: 42px; height: 42px; padding: 0 8px; display: flex; align-items: center;
      justify-content: center; font-weight: 700; font-size: 18px; color: #fff; background: #6b6355; }
    .grade.g-a { background: #9a7b3f; } .grade.g-b { background: #55606b; } .grade.g-c { background: #8a8271; }
    .who { flex: 1; min-width: 0; }
    .who .nm { font-weight: 600; font-size: 15px; }
    .who .sub { color: #6b6355; font-size: 12px; margin-top: 1px; }
    .pill { display: inline-block; margin-top: 4px; font-size: 11px; padding: 1px 7px; border: 1px solid #d8cfbc;
      color: #6b6355; letter-spacing: .04em; text-transform: uppercase; }
    .pill.play { background: #efe7d4; border-color: #d8cfbc; color: #7a6a3f; }
    .latent { margin-top: 10px; padding: 8px 10px; background: #f2efe6; border: 1px solid #ece5d6; }
    .latent .k { font-size: 11px; color: #6b6355; text-transform: uppercase; letter-spacing: .05em; }
    .latent .v { font-size: 17px; font-weight: 700; }
    .sect { margin-top: 12px; }
    .sect .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #6b6355; margin-bottom: 5px; }
    .reasons { list-style: none; margin: 0; padding: 0; }
    .reasons li { padding: 3px 0 3px 14px; position: relative; line-height: 1.35; }
    .reasons li:before { content: "·"; position: absolute; left: 3px; color: #9a7b3f; font-weight: 700; }
    .reco { line-height: 1.4; color: #33302a; }
    .acts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
    .btn { border: 1px solid #d8cfbc; background: #fff; color: #1a1a1a; padding: 6px 10px; cursor: pointer;
      font-size: 12px; text-decoration: none; display: inline-block; }
    .btn:hover { background: #f4f1ea; }
    .btn.primary { background: #1a1a1a; color: #fbfaf7; border-color: #1a1a1a; }
    .btn.primary:hover { background: #333; }
    .tpl { margin-top: 8px; }
    .tpl select { width: 100%; padding: 5px; border: 1px solid #d8cfbc; background: #fff; font-size: 12px; }
    .tpl .prev { margin-top: 6px; padding: 8px; background: #f6f3ec; border: 1px solid #ece5d6; font-size: 12px;
      line-height: 1.4; white-space: pre-wrap; max-height: 120px; overflow-y: auto; }
    .muted { color: #6b6355; line-height: 1.4; }
    .toast { position: absolute; left: 12px; bottom: 10px; background: #1a1a1a; color: #fff; font-size: 11px;
      padding: 4px 8px; opacity: 0; transition: opacity .15s; pointer-events: none; }
    .toast.on { opacity: 1; }
    .link { color: #9a7b3f; text-decoration: underline; cursor: pointer; }
    .foot { margin-top: 12px; padding-top: 8px; border-top: 1px solid #eee7da; font-size: 11px; color: #9a9280;
      display: flex; align-items: center; gap: 6px; }
  `;

  let host = null, root = null, collapsed = false, currentEmail = "", inserter = null;

  function ensure() {
    if (root) return root;
    host = document.createElement("div");
    host.id = "halia-badge-host";
    host.style.all = "initial";
    (document.body || document.documentElement).appendChild(host);
    root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    root.appendChild(style);
    return root;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function gradeClass(grade) {
    const g = String(grade || "").trim().toUpperCase();
    if (g.startsWith("A")) return "g-a";
    if (g.startsWith("B")) return "g-b";
    if (g.startsWith("C")) return "g-c";
    return "";
  }

  function shell(inner) {
    ensure();
    let wrap = root.querySelector(".wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "wrap";
      root.appendChild(wrap);
    }
    wrap.innerHTML = `
      <div class="bar">
        <span class="mark">⁂</span><span class="t">Halia</span><span class="sp"></span>
        <button class="ic" data-a="collapse" title="Collapse">${collapsed ? "▢" : "—"}</button>
        <button class="ic" data-a="close" title="Dismiss">✕</button>
      </div>
      ${collapsed ? "" : `<div class="body">${inner}</div>`}
      <div class="toast">Copied</div>`;
    wrap.querySelector('[data-a="close"]').onclick = hide;
    wrap.querySelector('[data-a="collapse"]').onclick = () => { collapsed = !collapsed; shell(inner); };
    return wrap;
  }

  function toast(msg) {
    const t = root && root.querySelector(".toast");
    if (!t) return;
    t.textContent = msg || "Copied";
    t.classList.add("on");
    setTimeout(() => t.classList.remove("on"), 1100);
  }

  function copy(text) {
    navigator.clipboard.writeText(text).then(() => toast("Copied"), () => toast("Copy failed"));
  }

  const API = {
    loading(id) {
      currentEmail = (id && (id.email || id.name || id.phone || id.cid)) || "";
      shell(`<div class="muted">Looking up ${esc((id && (id.name || id.email)) || "this client")}…</div>`);
    },

    notFound(id) {
      shell(`<div class="muted">No Halia signal for ${esc((id && (id.name || id.email)) || "this client")}.
        They are not a flagged client in your book.</div>`);
    },

    error(code) {
      const msg = {
        "no-token": 'Add your Halia token in the extension options to start.',
        "unauthorized": 'Your Halia token is not recognised. Re-generate it in Settings and paste it in the options.',
        "network": 'Could not reach Halia. Check the API address in the options.',
        "bad-query": 'Could not read this client from the page.'
      }[code] || ('Something went wrong (' + esc(code) + ').');
      shell(`<div class="muted">${msg}</div>`);
    },

    mount(d) {
      const gc = gradeClass(d.grade);
      const reasons = (d.reasons || []).slice(0, 6);
      const templates = d.templates || [];
      const subline = [d.email, d.ordersCount != null ? d.ordersCount + " orders" : null,
        d.spend != null ? "£" + Number(d.spend).toLocaleString() + " spent" : null,
        d.last ? "last " + d.last : null]
        .filter(Boolean).join(" · ");
      const cart = d.cart && d.cart.value ? d.cart : null;

      const acts = [];
      if (d.adminUrl) acts.push(`<a class="btn" href="${esc(d.adminUrl)}" target="_blank" rel="noopener">Open in store</a>`);
      if (d.dashboard) acts.push(`<a class="btn primary" href="${esc(d.dashboard)}" target="_blank" rel="noopener">Open in Halia</a>`);
      if (d.catalog) acts.push(`<button class="btn" data-a="catalog">Copy catalogue link</button>`);

      const tplBlock = templates.length ? `
        <div class="sect tpl">
          <div class="lbl">Message</div>
          <select data-a="tplsel">${templates.map((t, i) =>
            `<option value="${i}">${esc(t.name || ("Template " + (i + 1)))}</option>`).join("")}</select>
          <div class="prev" data-a="tplprev"></div>
          <div class="acts">
            ${inserter ? `<button class="btn primary" data-a="insert">Insert message</button>` : ""}
            <button class="btn" data-a="copybody">Copy message</button>
            <button class="btn" data-a="copysubj">Copy subject</button>
          </div>
        </div>` : "";

      shell(`
        <div class="head">
          <div class="grade ${gc}">${esc(d.grade || "—")}</div>
          <div class="who">
            <div class="nm">${esc(d.name || d.email || "This client")}</div>
            ${subline ? `<div class="sub">${esc(subline)}</div>` : ""}
            ${d.playLabel ? `<span class="pill play">${esc(d.playLabel)}</span>` : ""}
            ${d.hidden ? `<span class="pill">Hidden VIC</span>` : ""}
          </div>
        </div>
        ${d.latent ? `<div class="latent"><div class="k">Latent value</div><div class="v">${esc(d.latent)}</div></div>` : ""}
        ${cart ? `<div class="latent" style="background:#f6efe0;border-color:#e7d9bd">
          <div class="k">Open basket</div>
          <div class="v">£${esc(Number(cart.value).toLocaleString())}${cart.count ? ` <span style="font-weight:400;font-size:12px;color:#6b6355">${esc(cart.count)} item${cart.count === 1 ? "" : "s"}</span>` : ""}</div>
          ${cart.url ? `<a class="link" href="${esc(cart.url)}" target="_blank" rel="noopener">Open checkout</a>` : ""}
        </div>` : ""}
        ${d.action ? `<div class="sect"><div class="lbl">Next move</div><div class="reco">${esc(d.action)}</div></div>` : ""}
        ${reasons.length ? `<div class="sect"><div class="lbl">Why</div>
          <ul class="reasons">${reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
        ${tplBlock}
        <div class="acts">${acts.join("")}</div>
        <div class="foot"><span class="mark">⁂</span> Read live from your book. Nothing stored.</div>
      `);

      const wrap = root.querySelector(".wrap");
      if (!wrap || collapsed) return;
      const sel = wrap.querySelector('[data-a="tplsel"]');
      const prev = wrap.querySelector('[data-a="tplprev"]');
      const paint = () => { if (prev && sel) prev.textContent = (templates[+sel.value] || {}).body || ""; };
      if (sel) { sel.onchange = paint; paint(); }
      const bodyOf = () => (templates[+(sel ? sel.value : 0)] || {}).body || "";
      const cb = wrap.querySelector('[data-a="copybody"]');
      if (cb) cb.onclick = () => copy(bodyOf());
      const cs = wrap.querySelector('[data-a="copysubj"]');
      if (cs) cs.onclick = () => copy((templates[+(sel ? sel.value : 0)] || {}).subject || "");
      const ins = wrap.querySelector('[data-a="insert"]');
      if (ins) ins.onclick = () => {
        const ok = inserter && inserter(bodyOf());
        toast(ok ? "Inserted" : "Open a reply first");
      };
      const cat = wrap.querySelector('[data-a="catalog"]');
      if (cat) cat.onclick = () => copy(d.catalog || "");
    },

    setInserter(fn) { inserter = fn; },

    hide() {
      if (host && host.parentNode) host.parentNode.removeChild(host);
      host = null; root = null; collapsed = false;
    }
  };

  function hide() { API.hide(); }
  window.HaliaBadge = API;
})();
