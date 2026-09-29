// Halia toolbar. One card on the right edge of the page (Gmail, WhatsApp Web, the store admin),
// rendered into a Shadow DOM host so the page can neither restyle nor read it. It shows one person
// and one next move, with a reply one click away; everything else is a view behind that. It opens
// when it recognises someone, stays out of the way otherwise, reads live from the book and stores
// nothing. Exposes window.HaliaPanel.

(function () {
  if (window.HaliaPanel) return;

  const CHAN = { whatsapp: ["whatsapp", "chat"], email: ["email", "email"],
    line: ["line", "chat"], admin: ["catalogue", "referral"] };

  // Inline icons: one stroke, no fill, so they sit with the text at any size.
  const I = (d, extra) => `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}${extra || ""}</svg>`;
  const ICON = {
    search: I('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
    more: I('<circle cx="5" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="19" cy="12" r="1.2" fill="currentColor"/>'),
    right: I('<path d="m9 6 6 6-6 6"/>'),
    left: I('<path d="m15 6-6 6 6 6"/>'),
    x: I('<path d="M6 6l12 12M18 6 6 18"/>'),
    refresh: I('<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>'),
  };

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
    button { font: inherit; }
    :where(button, input, textarea, select):focus-visible { outline: 2px solid #1F564A; outline-offset: 1px; }

    /* the handle: a small tab on the right edge; shows the grade when someone is recognised */
    .handle { position: fixed; right: 0; top: 50%; transform: translateY(-50%); z-index: 2147483647;
      background: #303030; color: #ffffff; border: 0; cursor: pointer; padding: 10px 8px 10px 9px;
      border-radius: 10px 0 0 10px; display: flex; flex-direction: column; align-items: center; gap: 6px;
      box-shadow: -2px 0 12px rgba(0,0,0,.16); }
    .handle .m { font-size: 15px; color: #6FBFA0; line-height: 1; }
    .handle .hg { font-size: 12px; font-weight: 700; padding: 2px 6px; border-radius: 6px; line-height: 1.2; }
    .dock.open .handle { display: none; }

    .panel { position: fixed; right: 0; top: 0; height: 100vh; width: 320px; max-width: 92vw;
      z-index: 2147483647; background: #ffffff; color: #303030; border-left: 1px solid #e3e3e3;
      box-shadow: -10px 0 40px rgba(0,0,0,.14); display: flex; flex-direction: column;
      transform: translateX(100%); transition: transform .2s cubic-bezier(.2,.7,.2,1); }
    .dock.open .panel { transform: translateX(0); }

    .bar { display: flex; align-items: center; gap: 8px; padding: 12px 12px 12px 14px;
      border-bottom: 1px solid #e3e3e3; flex: none; position: relative; }
    .bar .m { color: #1F564A; font-size: 16px; line-height: 1; flex: none; }
    .find { flex: 1; display: flex; align-items: center; gap: 6px; min-width: 0; padding: 6px 9px;
      border: 1px solid #e3e3e3; border-radius: 8px; background: #f7f7f7; color: #8a8a8a; }
    .find:focus-within { border-color: #1F564A; background: #fff; }
    .find input { flex: 1; min-width: 0; border: 0; background: transparent; font-size: 13px; color: #303030;
      padding: 0; outline: none; }
    .find input::placeholder { color: #8a8a8a; }
    .find .clr { display: none; border: 0; background: none; color: #8a8a8a; padding: 0; cursor: pointer; line-height: 0; }
    .find.has .clr { display: inline-flex; }
    .ic { border: 0; background: transparent; cursor: pointer; color: #616161; padding: 6px; border-radius: 8px;
      display: inline-flex; line-height: 0; flex: none; }
    .ic:hover { background: #f1f1f1; color: #303030; }

    .menu { position: absolute; right: 12px; top: 50px; z-index: 2; background: #fff; border: 1px solid #e3e3e3;
      border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.14); min-width: 200px; padding: 6px; }
    .menu[hidden] { display: none; }
    .menu .who { font-size: 12px; color: #8a8a8a; padding: 8px 10px 6px; }
    .menu button { display: block; width: 100%; text-align: left; border: 0; background: transparent; color: #303030;
      font-size: 13px; padding: 9px 10px; border-radius: 8px; cursor: pointer; }
    .menu button:hover { background: #f7f7f7; }

    .body { overflow-y: auto; flex: 1; padding: 16px; }
    .sub { display: flex; align-items: center; gap: 6px; margin: -4px 0 12px -8px; }
    .sub .back { border: 0; background: transparent; color: #616161; cursor: pointer; padding: 6px; border-radius: 8px;
      display: inline-flex; line-height: 0; }
    .sub .back:hover { background: #f1f1f1; color: #303030; }
    .sub .t { font-size: 15px; font-weight: 650; }
    .sub .n { margin-left: auto; font-size: 12px; color: #8a8a8a; }

    /* the person */
    .person { display: flex; align-items: center; gap: 12px; }
    .idw { position: relative; flex: none; }
    .ava { width: 46px; height: 46px; border-radius: 50%; background: #e7efeb; color: #1F564A;
      display: grid; place-items: center; font-weight: 600; font-size: 14px; letter-spacing: .02em; }
    .gbadge { position: absolute; right: -5px; bottom: -4px; min-width: 22px; height: 20px; padding: 0 5px;
      border-radius: 10px; display: flex; align-items: center; justify-content: center; font-weight: 700;
      font-size: 12px; color: #fff; background: #616161; border: 2px solid #ffffff; }
    .g-a { background: #1F564A !important; } .g-b { background: #55606b !important; } .g-c { background: #8a8a8a !important; }
    .who { flex: 1; min-width: 0; }
    .who .nm { font-weight: 650; font-size: 16px; line-height: 1.25; display: flex; align-items: center; gap: 6px; }
    .who .nm .clr { border: 0; background: none; color: #8a8a8a; cursor: pointer; padding: 2px; line-height: 0; border-radius: 6px; }
    .who .nm .clr:hover { color: #303030; background: #f1f1f1; }
    .who .facts { color: #616161; font-size: 12px; margin-top: 3px; line-height: 1.45; }
    .pills { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
    .pill { font-size: 12px; padding: 2px 8px; border: 1px solid #e3e3e3; border-radius: 8px; color: #616161; background: #fff; }
    .pill.play { background: #e7efeb; border-color: #cfe0d8; color: #1F564A; }
    .pill.basket { background: #edf3f0; border-color: #cfe0d8; color: #1F564A; }
    .cue { margin-top: 12px; padding: 9px 12px; background: #f9efec; border: 1px solid #e3c9c0; border-radius: 12px;
      color: #8e3b2b; font-size: 12px; line-height: 1.4; }
    .move { margin-top: 14px; }
    .k { font-size: 12px; color: #8a8a8a; margin-bottom: 4px; }
    .move p { margin: 0; font-size: 13.5px; line-height: 1.5; color: #303030; }

    .btn { border: 1px solid #cccccc; background: #fff; color: #303030; padding: 9px 13px; cursor: pointer;
      font-size: 13px; border-radius: 8px; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
    .btn:hover { background: #f7f7f7; }
    .btn:disabled { opacity: .5; cursor: default; }
    .btn.primary { background: #1F564A; color: #ffffff; border-color: #1F564A; }
    .btn.primary:hover { background: #27695b; }
    .btn.wide { width: 100%; margin-top: 14px; padding: 11px 13px; font-weight: 600; }
    .acts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .quick { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 8px; }
    .quick.three { grid-template-columns: repeat(3, 1fr); }
    .quick.two { grid-template-columns: repeat(2, 1fr); }
    .quick .btn { padding: 9px 4px; font-size: 12.5px; }
    .lnk { background: none; border: 0; color: #1F564A; font-size: 12.5px; cursor: pointer; padding: 6px 0 0; }
    .lnk:hover { text-decoration: underline; }
    .mini { border: 1px solid #cccccc; background: #fff; color: #303030; cursor: pointer; font-size: 12px;
      padding: 3px 8px; border-radius: 8px; line-height: 1.4; }
    .mini:hover { background: #f7f7f7; }

    /* rows: one line each, an arrow when they lead somewhere */
    .rows { margin-top: 14px; border-top: 1px solid #ececec; }
    .row { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; border: 0; background: transparent;
      border-bottom: 1px solid #ececec; padding: 11px 2px; cursor: pointer; color: #303030; font-size: 13px; }
    .row:hover { background: #fafafa; }
    .row .rt { flex: 1; min-width: 0; }
    .row .rd { display: block; font-size: 12px; color: #8a8a8a; margin-top: 1px; }
    .row .ar { color: #8a8a8a; line-height: 0; flex: none; }
    .strip { display: flex; align-items: center; gap: 8px; width: 100%; text-align: left; margin-top: 14px; padding: 10px 12px;
      border: 1px solid #cfe0d8; background: #edf3f0; border-radius: 12px; color: #1F564A; cursor: pointer; font-size: 13px; }
    .strip .ar { margin-left: auto; line-height: 0; }

    .muted { color: #616161; line-height: 1.5; font-size: 13px; }
    .sect { margin-top: 18px; }
    .sect .k { margin-bottom: 8px; }
    .reasons { list-style: none; margin: 0; padding: 0; }
    .reasons li { padding: 5px 0 5px 14px; position: relative; line-height: 1.5; font-size: 13px; }
    .reasons li:before { content: "·"; position: absolute; left: 2px; color: #1F564A; font-weight: 700; }
    .orow { display: flex; gap: 8px; align-items: baseline; padding: 6px 0; border-top: 1px solid #f0f0f0; font-size: 12.5px; }
    .orow:first-child { border-top: 0; }
    .orow .od { color: #616161; white-space: nowrap; }
    .orow .oa { font-weight: 600; white-space: nowrap; }
    .orow .ot { color: #8a8a8a; flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { border: 1px solid #cccccc; background: #fff; color: #303030; cursor: pointer; font-size: 12px;
      padding: 4px 9px; border-radius: 8px; }
    .chip:hover { background: #f7f7f7; }
    .chip.on { background: #1F564A; color: #fff; border-color: #1F564A; }

    input.field, textarea.field, select.field { width: 100%; padding: 8px 10px; border: 1px solid #cccccc; border-radius: 8px;
      background: #fff; font-size: 13px; color: #303030; font-family: inherit; }
    textarea.field { resize: vertical; line-height: 1.45; }
    .frow { display: flex; gap: 6px; }
    .frow .field { flex: 1; min-width: 0; }
    .prev { margin-top: 8px; padding: 10px 12px; background: #f7f7f7; border: 1px solid #e3e3e3; border-radius: 12px;
      font-size: 13px; line-height: 1.5; white-space: pre-wrap; max-height: 40vh; overflow-y: auto; }
    .src { font-size: 12px; color: #8a8a8a; margin-top: 6px; }
    .tgl { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: #303030; cursor: pointer; user-select: none; }
    .tgl input { width: 15px; height: 15px; accent-color: #1F564A; margin: 0; }

    .list { border: 1px solid #e3e3e3; border-radius: 12px; overflow: hidden; background: #fff; margin-top: 8px;
      max-height: 44vh; overflow-y: auto; }
    .lcat { font-size: 12px; color: #8a8a8a; padding: 9px 12px 4px; background: #f7f7f7; position: sticky; top: 0; }
    .litem { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; border: 0; background: transparent;
      border-bottom: 1px solid #f0f0f0; padding: 10px 12px; cursor: pointer; color: #303030; font-size: 13px; }
    .litem:last-child { border-bottom: 0; }
    .litem:hover, .litem.sel { background: #f7f7f7; }
    .litem.sel { font-weight: 600; }
    .litem .cn { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .litem .cx { flex: none; font-size: 12px; color: #8a8a8a; }
    .cg { flex: none; min-width: 24px; height: 20px; padding: 0 5px; display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 12px; color: #fff; background: #616161; border-radius: 6px; }

    .card { border: 1px solid #e3e3e3; border-radius: 12px; padding: 12px; margin-top: 10px; background: #fff; }
    .card .rn { font-weight: 600; font-size: 13px; }
    .card .rd { font-size: 12px; color: #616161; margin-top: 2px; }
    .card .live { color: #3f7a4f; font-weight: 600; }
    .opt { display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px; border: 1px solid #e3e3e3; border-radius: 12px;
      background: #fff; margin-top: 6px; cursor: pointer; font-size: 13px; text-align: left; width: 100%; color: #303030; }
    .opt:hover { border-color: #cccccc; background: #fafafa; }
    .opt.note { cursor: default; border-style: dashed; }
    .opt b { display: block; font-weight: 600; }
    .opt i { display: block; font-style: normal; font-size: 12px; color: #616161; margin-top: 1px; }
    .opt input { margin-top: 3px; accent-color: #1F564A; }
    .pth { width: 40px; height: 40px; object-fit: cover; border: 1px solid #e3e3e3; border-radius: 8px; flex: none; background: #f7f7f7; }
    .prow { display: flex; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
    .prow .pt { flex: 1; min-width: 0; }
    .prow .pn { font-size: 13px; line-height: 1.3; }
    .prow .pp { font-size: 12px; color: #616161; margin-top: 2px; }
    .prow select { font-size: 12px; padding: 3px 6px; border: 1px solid #cccccc; border-radius: 6px; max-width: 120px; }
    .sel { position: sticky; bottom: -16px; margin: 12px -16px -16px; padding: 12px 16px; background: #fff; border-top: 1px solid #e3e3e3; }
    .sel .tot { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
    .sline { display: flex; align-items: center; gap: 6px; font-size: 12.5px; padding: 4px 0; }
    .sline span { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    /* loading: still skeletons, nothing that moves on its own */
    .sk { height: 12px; margin: 8px 0; border-radius: 6px; background: #ececec; }
    .sk.round { width: 46px; height: 46px; border-radius: 50%; margin: 0; flex: none; }
    .toast { position: absolute; left: 16px; right: 16px; bottom: 16px; background: #303030; color: #fff; font-size: 12.5px;
      padding: 9px 12px; border-radius: 10px; opacity: 0; transition: opacity .15s; pointer-events: none; text-align: center; }
    .toast.on { opacity: 1; }
    @media (prefers-reduced-motion: reduce) { .panel { transition: none; } }
  `;

  // ── state ─────────────────────────────────────────────────────────────────
  let host = null, root = null, inserter = null, channel = "email";
  let open = false, userCollapsed = false;   // the card opens itself for a client unless the associate closed it
  let ctx = null, client = null;             // ctx = standing context; client = active client state
  let view = "home";                          // home | reply | templates | book | sell | more | several | team | search | share
  let teamDefault = false;                    // a team surface (Slack, Teams) opens on the Team view
  let searchQ = "", searchResults = null;     // header search: "" | text; null | "busy" | "err" | []
  let cart = [], prodResults = [], cartBase = "";
  let prodView = { collection: "", size: "", ids: [], loaded: false, facets: { collections: [], sizes: [] } };
  let prodQ = "";
  let tplQuery = "", tplSel = null;
  let tplGreeting = true, tplSignoff = true;
  let tplRecent = [];
  let threadReader = null;
  let draftInstr = "";
  let draft = null;                           // { text, summary, actions, busy, error, source, aiAvailable }
  let suggest = null, suggestNote = "";
  let logReason = "";
  const contactHist = {};                     // cid -> last outreach {at,by,action,note} | null | "pending"
  let book = null;                            // the last booking's links, for "Send to client"
  // Reverse share (storefront): the page being shared, the client picked for it, the draft.
  let share = null, shareClient = null, shareOpener = 0, shareGreeting = true, shareDraft = null;
  let clientResults = null, clientQuery = "";
  // The guided burst: one template rendered per chosen client, sent by the associate one at a time.
  // The queue lives in chrome.storage.local (never synced), survives a page load, expires in a day.
  let burst = null;
  let bpick = { open: false, camp: "", q: "", list: null, ids: new Set(), tpl: "", chan: "" };
  const BURST_TTL = 24 * 3600 * 1000;

  // ── helpers ───────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function money(v) { return "£" + Number(v || 0).toLocaleString("en-GB", { maximumFractionDigits: 0 }); }
  function withToggles(text) {
    let t = String(text || "");
    if (!tplGreeting) t = window.HaliaShape.stripGreeting(t);
    if (!tplSignoff) t = window.HaliaShape.stripSignoff(t);
    return t;
  }
  function gradeClass(g) {
    g = String(g || "").trim().toUpperCase();
    return g[0] === "A" ? "g-a" : g[0] === "B" ? "g-b" : g[0] === "C" ? "g-c" : "";
  }
  function gradeBg(g) {
    g = String(g || "").trim().toUpperCase();
    return g[0] === "A" ? "#1F564A" : g[0] === "B" ? "#55606b" : g[0] === "C" ? "#8a8a8a" : "#616161";
  }
  function initials(s) {
    s = String(s || "").trim();
    if (!s) return "·";
    if (s.indexOf("@") >= 0) return (s.split("@")[0].replace(/[^a-zA-Z]/g, "").slice(0, 2) || "·").toUpperCase();
    const p = s.split(/\s+/).filter(Boolean);
    return (((p[0] || "")[0] || "") + ((p[1] || "")[0] || "")).toUpperCase() || "·";
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
  function digits(s) { return String(s || "").replace(/[^\d]/g, ""); }
  function ago(iso) {
    const t = Date.parse(iso); if (!t) return "";
    const s = (Date.now() - t) / 1000;
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    if (s < 86400) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  }
  function first(name) { const n = String(name || "").trim(); return n ? n.split(/\s+/)[0] : ""; }
  function activeCid() { return client && client.data && client.data.cid; }
  function activeName() { return (client && client.data && client.data.name) || ""; }
  function activeFirst() { return first(activeName()) || "there"; }
  function activeDetails() {
    const d = (client && client.data) || {};
    return { name: d.name || "", email: d.email || "", phone: d.phone || "" };
  }
  function shopify() { return !!(ctx && ctx.platform === "shopify"); }
  function runningCampaign() { return ((ctx && ctx.campaigns) || []).find((c) => c.running); }
  function tagged(url) {
    const camp = runningCampaign();
    if (!camp || !url) return url || "";
    const cm = CHAN[channel] || CHAN.email;
    return appendUtm(url, { source: cm[0], medium: cm[1], campaign: camp.utm });
  }

  function copy(text, msg) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => toast(msg || "Copied"), () => toast("Copy failed"));
  }
  function place(text) { const ok = inserter && inserter(text); toast(ok ? "Inserted" : "Open a reply first"); return !!ok; }
  function send(text) { if (inserter) place(text); else copy(text); }
  function loadThumb(imgEl, url, w) {
    if (!imgEl || !url) return;
    try {
      chrome.runtime.sendMessage({ type: "halia:image", url, w: w || 0 }, (r) => {
        if (chrome.runtime.lastError || !r || !r.dataUrl) { imgEl.style.display = "none"; return; }
        imgEl.src = r.dataUrl;
      });
    } catch (e) { imgEl.style.display = "none"; }
  }
  function fetchHistory(cid) {
    try {
      chrome.runtime.sendMessage({ type: "halia:history", cid }, (r) => {
        contactHist[cid] = (r && !r.error && r.last_contact) ? r.last_contact : null;
        render();
      });
    } catch (e) { contactHist[cid] = null; }
  }
  function act(body, okMsg, after) {
    try {
      chrome.runtime.sendMessage({ type: "halia:action", body }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) toast((r && r.detail) || "Couldn't complete that");
        else { toast(okMsg); if (after) after(r); }
      });
    } catch (e) { toast("Couldn't complete that"); }
  }
  function markContacted(cid, name, reason, quiet) {
    act({ action: "contacted", cid, client_name: name, reason: reason || "", quiet: !!quiet },
      quiet ? "Marked as contacted" : "Marked as contacted" + (ctx && ctx.slack ? ", the team knows" : ""));
    if (cid) { delete contactHist[cid]; render(); }
  }
  function why(r) {
    if (r && r.detail) return r.detail;
    const e = r && r.error;
    if (e === "no-token") return "Connect this browser from Halia to start.";
    if (e === "unauthorized") return "Your sign-in has ended. Open Halia and connect again.";
    if (e === "http-402") return "This store needs a plan for the toolbar. Open Halia to choose one.";
    if (e === "network") return "Could not reach Halia. Check your connection.";
    return "Could not do that just now. Please try again.";
  }

  const _CONTACT_REASONS = ["Sent a note", "Called", "WhatsApp", "Booked a visit", "Followed up"];
  const _TEAM_MSGS = ["I'm looking after {client}", "I've just contacted {client}",
    "{client} needs a follow-up", "Taking {client} from here"];
  const _CHAN_LABEL = { whatsapp: "WhatsApp", email: "Email", line: "LINE", admin: "Store" };

  // ── reverse share openers (storefront) ────────────────────────────────────
  const SHARE_KIND = {
    product:    { title: "Product",                action: "Send this piece" },
    collection: { title: "Collection",             action: "Send this edit" },
    care:       { title: "Care",                   action: "Send this to a client" },
    returns:    { title: "Returns",                action: "Send this to a client" },
    size:       { title: "Size guide",             action: "Send this to a client" },
    about:      { title: "About the house",        action: "Send this to a client" },
    contact:    { title: "Visit and appointments", action: "Invite a client" },
    press:      { title: "A link",                 action: "Send this to a client" }
  };
  const SHARE_OPENERS = {
    product: [
      { label: "Set aside",         body: "I have set {title} aside for you, if you would like it." },
      { label: "Just in",           body: "{title} just arrived and I thought of you straight away." },
      { label: "Your taste",        body: "{title} reminded me of your taste the moment it came in." },
      { label: "What do you think", body: "I would love to know what you think of {title}." },
      { label: "Limited",           body: "We are down to the last few of {title}, and I wanted you to have first look." },
      { label: "First look",        body: "An early look at {title} for you, before it goes out more widely." },
      { label: "Back in stock",     body: "Good news, {title} is back. I can hold one for you." }
    ],
    collection: [
      { label: "An edit for you",   body: "I put together a few pieces I thought you would love." },
      { label: "New season",        body: "The new season is in. Here is a first look, chosen with you in mind." }
    ],
    care:    [{ label: "Care guide", body: "Here is how to care for your piece, so it lasts beautifully." }],
    returns: [
      { label: "Returns",           body: "Here is everything on our returns and exchanges, in case it helps." },
      { label: "Happy to help",     body: "Of course. Here are the details, and I am here if you need anything." }
    ],
    size:    [{ label: "Size guide", body: "Our size guide, so you find the perfect fit. Tell me if you would like me to check." }],
    about:   [{ label: "About us",   body: "A little about the house, and how we like to look after you." }],
    contact: [
      { label: "Come see us",       body: "Come and see us whenever suits. Here are the details." },
      { label: "Book a visit",      body: "I would love to set aside some time for you. Shall we arrange a private appointment?" }
    ],
    press:   [{ label: "Thought of you", body: "Saw this and immediately thought of you." }]
  };
  function shareKind() { return (share && SHARE_KIND[share.kind]) ? share.kind : "press"; }
  function shareOpeners() {
    const k = shareKind();
    const over = ctx && ctx.openers && Array.isArray(ctx.openers[k]) && ctx.openers[k].length ? ctx.openers[k] : null;
    return over || SHARE_OPENERS[k] || SHARE_OPENERS.press;
  }
  function shareTitle() { const t = ((share && share.title) || "").trim(); return (t && t.length <= 60) ? t : ""; }
  function fillOpener(body) {
    const b = String(body || "");
    if (b.indexOf("{title}") < 0) return b;
    const t = shareTitle();
    let out = b.split("{title}").join(t || "this");
    if (!t) out = out.charAt(0).toUpperCase() + out.slice(1);
    return out;
  }

  // ── mount ─────────────────────────────────────────────────────────────────
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
      <button class="handle" data-a="open" title="Halia"><span class="m">⁂</span></button>
      <aside class="panel">
        <div class="bar">
          <span class="m">⁂</span>
          <label class="find"><span data-a="findicon">${ICON.search}</span>
            <input data-a="q" placeholder="Search your book" autocomplete="off" spellcheck="false">
            <button class="clr" data-a="qclear" title="Clear">${ICON.x}</button></label>
          <button class="ic" data-a="menu" title="More">${ICON.more}</button>
          <button class="ic" data-a="close" title="Hide">${ICON.right}</button>
          <div class="menu" data-a="menubox" hidden></div>
        </div>
        <div class="body" data-a="body"></div>
        <div class="toast"></div>
      </aside>`;
    root.appendChild(dock);
    dock.querySelector('[data-a="open"]').onclick = () => setOpen(true, true);
    dock.querySelector('[data-a="close"]').onclick = () => setOpen(false, true);
    dock.querySelector('[data-a="menu"]').onclick = (e) => { e.stopPropagation(); toggleMenu(); };
    dock.addEventListener("click", (e) => { if (!e.target.closest('[data-a="menubox"]')) hideMenu(); });
    const q = dock.querySelector('[data-a="q"]');
    let qt = null;
    q.oninput = () => { clearTimeout(qt); qt = setTimeout(() => doSearch(q.value), 250); dock.querySelector(".find").classList.toggle("has", !!q.value); };
    q.onkeydown = (e) => { if (e.key === "Escape") { q.value = ""; doSearch(""); } };
    dock.querySelector('[data-a="qclear"]').onclick = () => { q.value = ""; dock.querySelector(".find").classList.remove("has"); doSearch(""); };
    render(); paintHandle();
  }

  function setOpen(v, byUser) {
    open = v;
    if (byUser) { userCollapsed = !v; try { chrome.storage.local.set({ panelOpen: v }); } catch (e) { /* ignore */ } }
    const dock = root && root.querySelector(".dock");
    if (dock) dock.classList.toggle("open", v);
    if (!v) hideMenu();
  }
  function toggleMenu() {
    const m = root && root.querySelector('[data-a="menubox"]'); if (!m) return;
    if (!m.hidden) { m.hidden = true; return; }
    m.innerHTML = `${ctx && ctx.seat ? `<div class="who">Signed in as ${esc(ctx.seat)}</div>` : ""}
      <button data-m="team">Team</button>
      <button data-m="several">Message several clients</button>
      <button data-m="refresh">Refresh</button>
      ${ctx && ctx.seat ? `<button data-m="signout">Sign out</button>` : ""}`;
    m.hidden = false;
    m.querySelectorAll("[data-m]").forEach((b) => b.onclick = () => {
      const k = b.dataset.m; hideMenu();
      if (k === "team") go("team");
      else if (k === "several") go("several");
      else if (k === "refresh") window.dispatchEvent(new CustomEvent("halia:refresh"));
      else if (k === "signout") chrome.runtime.sendMessage({ type: "halia:signout" }, () => {
        ctx = null; burst = null; client = null; go("home");
        try { window.dispatchEvent(new CustomEvent("halia:refresh")); } catch (e) { /* ignore */ }
      });
    });
  }
  function hideMenu() { const m = root && root.querySelector('[data-a="menubox"]'); if (m) m.hidden = true; }
  function toast(msg) {
    const t = root && root.querySelector(".toast"); if (!t) return;
    t.textContent = msg; t.classList.add("on");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("on"), 1600);
  }
  function paintHandle() {
    const h = root && root.querySelector(".handle"); if (!h) return;
    const g = client && client.data && client.data.grade;
    let chip = h.querySelector(".hg");
    if (g) {
      if (!chip) { chip = document.createElement("span"); chip.className = "hg"; h.appendChild(chip); }
      chip.textContent = g; chip.style.background = gradeBg(g);
      h.title = activeName() ? activeName() + " · Halia" : "Halia";
    } else if (chip) { chip.remove(); h.title = "Halia"; }
  }
  function go(v) { view = v; render(); const b = root && root.querySelector('[data-a="body"]'); if (b) b.scrollTop = 0; }
  function body() { return root && root.querySelector('[data-a="body"]'); }
  function subhead(title, right) {
    return `<div class="sub"><button class="back" data-a="back" title="Back">${ICON.left}</button>
      <span class="t">${esc(title)}</span>${right ? `<span class="n">${right}</span>` : ""}</div>`;
  }
  function wireBack(el) { const b = el.querySelector('[data-a="back"]'); if (b) b.onclick = () => go(share && !client ? "share" : "home"); }

  // ── render ────────────────────────────────────────────────────────────────
  function render() {
    const el = body(); if (!el) return;
    if (searchQ) { renderSearch(el); return; }
    const v = (view === "home" && share && !client) ? "share" : view;
    if (v === "reply") renderReply(el);
    else if (v === "templates") renderTemplates(el);
    else if (v === "book") renderBook(el);
    else if (v === "sell") renderSell(el);
    else if (v === "more") renderMore(el);
    else if (v === "several") renderSeveral(el);
    else if (v === "team") renderTeam(el);
    else if (v === "share") renderShare(el);
    else renderHome(el);
    paintHandle();
  }

  // ── search (the header field) ─────────────────────────────────────────────
  function doSearch(q) {
    searchQ = String(q || "").trim();
    if (!searchQ) { searchResults = null; render(); return; }
    searchResults = "busy"; render();
    const mine = searchQ;
    try {
      chrome.runtime.sendMessage({ type: "halia:clients", q: mine }, (r) => {
        if (mine !== searchQ) return;
        searchResults = (chrome.runtime.lastError || !r || r.error) ? "err" : (r.clients || []);
        render();
      });
    } catch (e) { searchResults = "err"; render(); }
  }
  function pickSearch(c) {
    const q = root && root.querySelector('[data-a="q"]');
    if (q) { q.value = ""; root.querySelector(".find").classList.remove("has"); }
    searchQ = ""; searchResults = null;
    client = { loading: true, name: c.name };
    resetForClient(); view = "home"; render();
    try {
      chrome.runtime.sendMessage({ type: "halia:lookup", query: { cid: c.cid, name: c.name } }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) { client = { error: why(r) }; }
        else if (!r.found) { client = { notfound: true, name: c.name }; }
        else { client = { data: r, manual: true }; }
        render();
      });
    } catch (e) { client = { error: "Could not reach Halia." }; render(); }
  }
  function renderSearch(el) {
    const r = searchResults;
    let rows;
    if (r === "busy") rows = `<div class="muted" style="padding:10px 12px">Looking…</div>`;
    else if (r === "err") rows = `<div class="muted" style="padding:10px 12px">Couldn't reach your book.</div>`;
    else if (!r || !r.length) rows = `<div class="muted" style="padding:10px 12px">No one by that name in your book.</div>`;
    else rows = r.slice(0, 40).map((c, i) => `<button class="litem" data-i="${i}">
        <span class="cg ${gradeClass(c.grade)}">${esc(c.grade || "·")}</span><span class="cn">${esc(c.name)}</span></button>`).join("");
    el.innerHTML = `<div class="k">Your book</div><div class="list" style="margin-top:6px">${rows}</div>`;
    el.querySelectorAll("[data-i]").forEach((b) => b.onclick = () => pickSearch(r[+b.dataset.i]));
  }

  // ── home ──────────────────────────────────────────────────────────────────
  function burstStrip() {
    if (!burst) return "";
    const it = burst.items[burst.i];
    return `<button class="strip" data-a="strip">${it ? `Sending to several clients · ${burst.i + 1} of ${burst.items.length}` : "Several clients · all done"}<span class="ar">${ICON.right}</span></button>`;
  }
  function wireStrip(el) { const s = el.querySelector('[data-a="strip"]'); if (s) s.onclick = () => go("several"); }
  function renderHome(el) {
    if (!client) {
      const quick = [`<button class="btn" data-q="templates">Templates</button>`, `<button class="btn" data-q="several">Several clients</button>`];
      if (shopify()) quick.push(`<button class="btn" data-q="sell">Sell</button>`);
      el.innerHTML = `<div class="muted">Open a chat or an email and Halia shows who it is and the next move. Or search your book above.</div>
        ${burstStrip()}
        <div class="quick ${quick.length === 3 ? "three" : "two"}" style="margin-top:14px">${quick.join("")}</div>`;
      wireStrip(el); el.querySelectorAll("[data-q]").forEach((b) => b.onclick = () => go(b.dataset.q));
      return;
    }
    if (client.loading) {
      el.innerHTML = `<div class="person"><div class="sk round"></div>
        <div style="flex:1"><div class="sk" style="width:60%"></div><div class="sk" style="width:40%"></div></div></div>
        <div class="sk" style="margin-top:18px;width:30%"></div><div class="sk" style="width:92%"></div><div class="sk" style="width:70%"></div>`;
      return;
    }
    if (client.error) { el.innerHTML = `<div class="muted">${esc(client.error)}</div>`; return; }
    if (client.notfound) {
      el.innerHTML = `<div class="person"><div class="idw"><div class="ava">${esc(initials(client.name))}</div></div>
          <div class="who"><div class="nm">${esc(client.name || "This person")}</div><div class="facts">Not in your book yet</div></div></div>
        ${burstStrip()}
        <div class="quick two" style="margin-top:14px"><button class="btn" data-q="templates">Templates</button>
          ${shopify() ? `<button class="btn" data-q="sell">Sell</button>` : `<button class="btn" data-q="several">Several clients</button>`}</div>`;
      wireStrip(el); el.querySelectorAll("[data-q]").forEach((b) => b.onclick = () => go(b.dataset.q));
      return;
    }
    const d = client.data || {};
    const facts = [d.ordersCount != null ? d.ordersCount + " order" + (d.ordersCount === 1 ? "" : "s") : null,
      d.spend != null ? money(d.spend) : null, d.last ? "last " + d.last : null].filter(Boolean).join(" · ");
    const h = d.cid ? contactHist[d.cid] : null;
    let cue = "";
    if (h && typeof h === "object" && h.at) {
      cue = `<div class="cue">${h.action === "note" ? "Note added" : "Contacted"} <b>${esc(ago(h.at))}</b>${h.by ? " by " + esc(h.by) : ""}${h.note ? ` · “${esc(h.note)}”` : ""}</div>`;
    }
    const pills = [];
    if (d.playLabel) pills.push(`<span class="pill play">${esc(d.playLabel)}</span>`);
    if (d.hidden) pills.push(`<span class="pill">Hidden VIC</span>`);
    if (d.cart && d.cart.value) pills.push(`<span class="pill basket">Open basket · ${money(d.cart.value)}</span>`);
    const move = d.action || (d.reasons && d.reasons[0]) || "";
    const quick = [`<button class="btn" data-q="templates">Templates</button>`, `<button class="btn" data-q="book">Book</button>`];
    if (shopify()) quick.push(`<button class="btn" data-q="sell">Sell</button>`);
    quick.push(`<button class="btn" data-q="more">More</button>`);
    el.innerHTML = `
      <div class="person">
        <div class="idw"><div class="ava">${esc(initials(d.name || d.email || ""))}</div>
          ${d.grade ? `<div class="gbadge ${gradeClass(d.grade)}">${esc(d.grade)}</div>` : ""}</div>
        <div class="who">
          <div class="nm"><span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(d.name || d.email || "This client")}</span>
            ${client.manual ? `<button class="clr" data-a="unpin" title="Back to the page">${ICON.x}</button>` : ""}</div>
          ${facts ? `<div class="facts">${esc(facts)}</div>` : ""}
        </div>
      </div>
      ${pills.length ? `<div class="pills">${pills.join("")}</div>` : ""}
      ${cue}
      ${move ? `<div class="move"><div class="k">Next move</div><p>${esc(move)}</p></div>` : ""}
      <button class="btn primary wide" data-a="reply">${threadReader ? "Write the reply" : "Write a message"}</button>
      <div class="quick ${quick.length === 3 ? "three" : ""}">${quick.join("")}</div>
      ${burstStrip()}`;
    if (d.cid && shopify() && !(d.cid in contactHist)) { contactHist[d.cid] = "pending"; fetchHistory(d.cid); }
    el.querySelector('[data-a="reply"]').onclick = () => { go("reply"); if (!draft || (!draft.text && !draft.busy)) runBrief(); };
    el.querySelectorAll("[data-q]").forEach((b) => b.onclick = () => go(b.dataset.q));
    const un = el.querySelector('[data-a="unpin"]'); if (un) un.onclick = () => { client = null; resetForClient(); render(); };
    wireStrip(el);
  }

  // ── reply ─────────────────────────────────────────────────────────────────
  function collectThread() { try { return threadReader ? (threadReader() || []) : []; } catch (e) { return []; } }
  function runBrief() {
    const d = (client && client.data) || {};
    draft = Object.assign({}, draft, { busy: true, error: "" });
    render();
    const bodyReq = { cid: d.cid || "", email: d.email || "", phone: d.phone || "", name: d.name || "",
      channel, instruction: draftInstr, thread: collectThread() };
    try {
      chrome.runtime.sendMessage({ type: "halia:brief", body: bodyReq }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) draft = { busy: false, error: why(r) };
        else draft = { busy: false, error: "", summary: r.summary || "", text: r.reply || "",
          actions: r.actions || [], campaign: r.campaign || null, read: r.read_thread || 0,
          source: r.source || "book", aiAvailable: r.ai_available };
        render();
      });
    } catch (e) { draft = { busy: false, error: "Could not write that just now." }; render(); }
  }
  function briefLogReason() {
    const text = (draft && draft.text) || "";
    if (!text) return "";
    const f = text.replace(/\s+/g, " ").trim().split(/(?<=[.!?])\s/)[0] || text;
    const gist = f.length > 90 ? f.slice(0, 87).trimEnd() + "…" : f;
    const via = _CHAN_LABEL[channel] || "";
    return (via ? `Replied on ${via}: ` : "Replied: ") + gist;
  }
  const _DOABLE = { pipeline: 1, campaign: 1, contacted: 1, catalogue: 1 };
  function canDo(a) {
    if (!_DOABLE[a.kind]) return false;
    if (a.kind === "campaign") return !!(activeCid() && draft && draft.campaign);
    if (a.kind === "catalogue") return !!(ctx && ctx.catalog);
    return !!activeCid();
  }
  function doAction(a) {
    const cid = activeCid();
    if (a.kind === "pipeline" && cid) return act({ action: "pipeline", cid }, "Added to the pipeline");
    if (a.kind === "campaign" && cid && draft && draft.campaign)
      return act({ action: "campaign_add", campaign_id: draft.campaign.id, cid }, "Added to " + draft.campaign.name);
    if (a.kind === "contacted" && cid) return markContacted(cid, activeName(), a.label || "");
    if (a.kind === "catalogue" && ctx && ctx.catalog) return send(tagged(ctx.catalog));
    toast("Nothing to do here yet");
  }
  function renderReply(el) {
    const busy = draft && draft.busy, has = draft && draft.text;
    const acts = (draft && draft.actions) || [];
    el.innerHTML = subhead("Reply", activeName() ? esc(first(activeName())) : "") + `
      ${busy ? `<div class="sk" style="width:40%"></div><div class="sk" style="width:95%"></div><div class="sk" style="width:88%"></div><div class="sk" style="width:60%"></div>
        <div class="muted" style="margin-top:10px">${threadReader ? "Reading the conversation…" : "Writing…"}</div>` : ""}
      ${draft && draft.error ? `<div class="muted">${esc(draft.error)}</div>` : ""}
      ${!busy && draft && draft.summary ? `<div class="muted" style="margin-bottom:10px">${esc(draft.summary)}</div>` : ""}
      ${!busy && has ? `<textarea class="field" data-a="dtext" rows="8">${esc(draft.text)}</textarea>
        <div class="src">${draft.source === "ai" ? "Written by Halia" + (draft.read ? " from " + draft.read + " message" + (draft.read === 1 ? "" : "s") : "") : "From your templates"}${draft.aiAvailable === false && draft.source !== "ai" ? " · turn on AI drafting in Halia for a written reply" : ""}</div>
        <div class="acts">
          ${inserter ? `<button class="btn primary" data-a="dins">Insert</button>` : ""}
          <button class="btn" data-a="dcopy">Copy</button>
          ${activeCid() ? `<button class="btn" data-a="dlog">Mark as contacted</button>` : ""}
        </div>
        <div class="frow" style="margin-top:12px">
          <input class="field" data-a="dinstr" placeholder="Change something, then write again" value="${esc(draftInstr)}">
          <button class="btn" data-a="again">Again</button>
        </div>` : ""}
      ${!busy && !has && !(draft && draft.error) ? `<button class="btn primary wide" data-a="again" style="margin-top:0">${threadReader ? "Write the reply" : "Write a message"}</button>` : ""}
      ${!busy && acts.length ? `<div class="sect"><div class="k">Worth doing</div>${acts.map((a, i) => canDo(a)
        ? `<button class="opt" data-ba="${i}"><span><b>${esc(a.label)}</b><i>${esc(a.why || "")}</i></span></button>`
        : `<div class="opt note"><span><b>${esc(a.label)}</b><i>${esc(a.why || "")}</i></span></div>`).join("")}</div>` : ""}
      ${!busy ? `<button class="lnk" data-a="totpl" style="margin-top:14px">Use a template instead</button>` : ""}`;
    wireBack(el);
    const ta = el.querySelector('[data-a="dtext"]'); if (ta) ta.oninput = () => { draft.text = ta.value; };
    const di = el.querySelector('[data-a="dinstr"]'); if (di) di.oninput = () => { draftInstr = di.value; };
    el.querySelectorAll('[data-a="again"]').forEach((b) => b.onclick = runBrief);
    const ins = el.querySelector('[data-a="dins"]'); if (ins) ins.onclick = () => place(draft.text);
    const cp = el.querySelector('[data-a="dcopy"]'); if (cp) cp.onclick = () => copy(draft.text, "Reply copied");
    const lg = el.querySelector('[data-a="dlog"]'); if (lg) lg.onclick = () => markContacted(activeCid(), activeName(), briefLogReason());
    el.querySelectorAll("[data-ba]").forEach((n) => n.onclick = () => doAction(acts[+n.dataset.ba] || {}));
    const tt = el.querySelector('[data-a="totpl"]'); if (tt) tt.onclick = () => go("templates");
  }

  // ── templates ─────────────────────────────────────────────────────────────
  function templateList() {
    const t = client && client.data && client.data.templates;
    return (t && t.length ? t : (ctx && ctx.templates) || []);
  }
  function renderTemplates(el) {
    const list = templateList();
    if (!list.length) {
      el.innerHTML = subhead("Templates") + `<div class="muted">Add templates in Halia, under Settings.</div>`;
      wireBack(el); return;
    }
    const fill = (s) => String(s || "").split("{first_name}").join(activeFirst());
    const q = tplQuery.trim().toLowerCase();
    const matches = list.map((t, i) => ({ t, i }))
      .filter(({ t }) => !q || ((t.name || "") + " " + (t.category || "") + " " + (t.body || "")).toLowerCase().includes(q));
    // With no search, the right ones first: what the server suggests for the client on screen,
    // then what this associate reaches for. Each template appears once.
    const groups = []; const idx = {}; const taken = new Set();
    if (!q) {
      const byName = (names) => (names || []).map((n) => list.findIndex((t) => (t.name || "") === n))
        .filter((i) => i >= 0 && !taken.has(i)).map((i) => { taken.add(i); return { t: list[i], i }; });
      const sugg = byName((client && client.data && client.data.suggested) || (ctx && ctx.suggested) || []);
      const rec = byName(tplRecent).slice(0, 4);
      if (sugg.length) groups.push({ cat: client && client.data ? "For " + esc(activeFirst()) : "Start here", items: sugg });
      if (rec.length) groups.push({ cat: "Recent", items: rec });
    }
    matches.forEach(({ t, i }) => {
      if (taken.has(i)) return;
      const c = t.category || "General";
      if (!(c in idx)) { idx[c] = groups.length; groups.push({ cat: c, items: [] }); }
      groups[idx[c]].items.push({ t, i });
    });
    const sel = (tplSel != null && list[tplSel]) ? list[tplSel] : null;
    el.innerHTML = subhead("Templates", String(list.length)) + `
      <input class="field" data-a="tsearch" placeholder="Find a template" value="${esc(tplQuery)}">
      <div class="list">${groups.length
        ? groups.map((g) => `<div class="lcat">${g.cat}</div>` +
            g.items.map(({ t, i }) => `<button class="litem${i === tplSel ? " sel" : ""}" data-ti="${i}"><span class="cn">${esc(t.name || ("Template " + (i + 1)))}</span></button>`).join("")).join("")
        : `<div class="muted" style="padding:10px 12px">No templates match.</div>`}</div>
      ${sel ? `<div class="prev">${esc(withToggles(fill(sel.body)))}</div>
        <div style="display:flex;gap:14px;margin-top:8px">
          <label class="tgl"><input type="checkbox" data-a="tg"${tplGreeting ? " checked" : ""}>Greeting</label>
          <label class="tgl"><input type="checkbox" data-a="tso"${tplSignoff ? " checked" : ""}>Sign-off</label></div>
        <div class="acts">
          ${inserter ? `<button class="btn primary" data-a="tins">Insert</button>` : ""}
          <button class="btn" data-a="tcopy">Copy</button>
          ${sel.subject ? `<button class="btn" data-a="tcopys">Copy subject</button>` : ""}
        </div>` : ""}`;
    wireBack(el);
    const search = el.querySelector('[data-a="tsearch"]');
    search.oninput = () => { tplQuery = search.value; render(); const s2 = body().querySelector('[data-a="tsearch"]'); if (s2) { s2.focus(); s2.setSelectionRange(s2.value.length, s2.value.length); } };
    el.querySelectorAll("[data-ti]").forEach((b) => b.onclick = () => { tplSel = +b.dataset.ti; render(); });
    const saveTog = () => { try { chrome.storage.sync.set({ tplGreeting, tplSignoff }); } catch (e) { /* ignore */ } };
    const tg = el.querySelector('[data-a="tg"]'); if (tg) tg.onchange = () => { tplGreeting = tg.checked; saveTog(); render(); };
    const tso = el.querySelector('[data-a="tso"]'); if (tso) tso.onchange = () => { tplSignoff = tso.checked; saveTog(); render(); };
    const text = () => withToggles(fill((list[tplSel] || {}).body));
    const used = () => { const t = list[tplSel]; if (!t) return;
      tplRecent = [t.name].concat(tplRecent.filter((n) => n !== t.name)).slice(0, 6);
      try { chrome.storage.sync.set({ tplRecent }); } catch (e) { /* ignore */ } };
    const ins = el.querySelector('[data-a="tins"]'); if (ins) ins.onclick = () => { used(); place(text()); };
    const cp = el.querySelector('[data-a="tcopy"]'); if (cp) cp.onclick = () => { used(); copy(text(), "Message copied"); };
    const cs = el.querySelector('[data-a="tcopys"]'); if (cs) cs.onclick = () => copy(fill((list[tplSel] || {}).subject), "Subject copied");
  }

  // ── book a visit ──────────────────────────────────────────────────────────
  function renderBook(el) {
    const who = activeFirst();
    el.innerHTML = subhead("Book a visit", activeName() ? esc(who) : "") + (!activeCid()
      ? `<div class="muted">Open a client first, then book them in.</div>`
      : `<div class="k">When</div>
        <input class="field" data-a="apwhen" type="datetime-local">
        <div class="k" style="margin-top:10px">Where</div>
        <input class="field" data-a="applace" placeholder="The boutique, a private room, a call">
        <button class="btn primary wide" data-a="apbook">Book</button>
        ${book ? `<div class="sect"><div class="k">Booked</div>
          <div class="muted">Add to your calendar: <a class="lnk" href="${esc(book.google)}" target="_blank" rel="noopener">Google</a> · <a class="lnk" href="${esc(book.outlook)}" target="_blank" rel="noopener">Outlook</a> · <a class="lnk" href="${esc(book.ics_data)}" download="appointment.ics">Apple</a></div>
          <div class="acts"><button class="btn primary" data-a="apsend">${inserter ? "Send the details to " + esc(who) : "Copy the details for " + esc(who)}</button></div></div>` : ""}`);
    wireBack(el);
    const apb = el.querySelector('[data-a="apbook"]');
    if (apb) apb.onclick = () => {
      const w = el.querySelector('[data-a="apwhen"]'), pl = el.querySelector('[data-a="applace"]');
      if (!w || !w.value) { toast("Pick a date and time"); return; }
      const d = activeDetails();
      apb.disabled = true; apb.textContent = "Booking…";
      act({ action: "appointment", cid: activeCid(), when: new Date(w.value).toISOString(),
        place: (pl && pl.value) || "", client_name: d.name, client_email: d.email }, "Booked",
        (r) => { book = r.links || null; render(); });
      setTimeout(() => { if (apb.isConnected) { apb.disabled = false; apb.textContent = "Book"; } }, 4000);
    };
    const sb = el.querySelector('[data-a="apsend"]'); if (sb) sb.onclick = () => send(book.message);
  }

  // ── sell: one search, add or send a photo, one selection ──────────────────
  function cartLink() {
    if (!cartBase || !cart.some((i) => i.id)) return "";
    const items = cart.filter((i) => i.id).map((i) => i.id + ":" + i.qty).join(",");
    return tagged(cartBase.replace(/\/$/, "") + "/cart/" + items);
  }
  function addToCart(v, ptitle, pid) {
    const ex = cart.find((i) => i.id === v.id);
    if (ex) ex.qty += 1;
    else cart.push({ id: v.id, qty: 1, price: v.price, product_id: pid || null,
      label: ptitle + (v.title && v.title !== "Default Title" ? " · " + v.title : "") });
    render(); toast("Added");
  }
  function sendCatalogue() {
    const ids = cart.map((i) => i.product_id).filter(Boolean);
    if (!ids.length) { toast("Add something first"); return; }
    try {
      chrome.runtime.sendMessage({ type: "halia:catalogue", body: Object.assign({ product_ids: ids }, activeDetails()) }, (r) => {
        if (chrome.runtime.lastError || !r || r.error || !r.url) { toast("Couldn't build that"); return; }
        send(tagged(r.url));
      });
    } catch (e) { toast("Couldn't build that"); }
  }
  function doProductSearch(q) {
    prodResults = "busy"; render();
    const filters = { collection: prodView.collection, size: prodView.size };
    try {
      chrome.runtime.sendMessage({ type: "halia:products", q, filters }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) { prodResults = "err"; prodView.ids = []; render(); return; }
        prodResults = r.products || [];
        prodView.ids = r.ids || [];
        if (r.facets && (r.facets.collections || []).length) prodView.facets = r.facets;
        if (r.cart_base) cartBase = r.cart_base;
        render();
      });
    } catch (e) { prodResults = "err"; render(); }
  }
  function addViewToCart() {
    const ids = prodView.ids || [];
    if (!ids.length) { toast("Nothing in this view"); return; }
    const byId = {}; (Array.isArray(prodResults) ? prodResults : []).forEach((p) => { byId[String(p.id)] = p; });
    let added = 0;
    ids.forEach((id) => {
      const p = byId[String(id)], v = p && (p.variants || [])[0];
      if (v) { if (!cart.find((i) => i.id === v.id)) { cart.push({ id: v.id, qty: 1, price: v.price, product_id: p.id, label: p.title }); added++; } }
      else if (!cart.find((i) => String(i.product_id) === String(id))) {
        cart.push({ id: null, qty: 1, price: (p && p.price) || null, product_id: id, label: (p && p.title) || "" }); added++;
      }
    });
    render(); toast(added + " added");
  }
  function runSuggest() {
    const d = (client && client.data) || {};
    suggest = { busy: true, picks: (suggest && suggest.picks) || [], error: "" };
    render();
    try {
      chrome.runtime.sendMessage({ type: "halia:suggest", body: { cid: d.cid || "", email: d.email || "", phone: d.phone || "",
        name: d.name || "", instruction: suggestNote, thread: collectThread() } }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) suggest = { busy: false, picks: [], error: why(r) };
        else { const picks = (r.picks || []).map((p) => Object.assign({ on: true }, p));
          suggest = { busy: false, picks, error: "", empty: !picks.length, aiAvailable: r.ai_available }; }
        render();
      });
    } catch (e) { suggest = { busy: false, picks: [], error: "Couldn't suggest just now." }; render(); }
  }
  function suggestIntoCart() {
    const on = ((suggest && suggest.picks) || []).filter((p) => p.on);
    if (!on.length) { toast("Tick something first"); return; }
    on.forEach((p) => {
      if (p.variant_id && !cart.find((i) => i.id === p.variant_id)) cart.push({ id: p.variant_id, qty: 1, price: p.price, label: p.title, product_id: p.product_id });
      else if (!p.variant_id && !cart.find((i) => i.product_id === p.product_id)) cart.push({ id: null, qty: 1, price: p.price, label: p.title, product_id: p.product_id });
    });
    render(); toast(on.length + " added");
  }
  function copyImage(url) {
    if (!url) return;
    try {
      chrome.runtime.sendMessage({ type: "halia:image", url }, (r) => {
        const dataUrl = r && r.dataUrl;
        if (chrome.runtime.lastError || !dataUrl) { copy(url, "Photo link copied"); return; }
        const img = new Image();
        img.onload = () => {
          try {
            const c = document.createElement("canvas");
            c.width = img.naturalWidth || 800; c.height = img.naturalHeight || 800;
            c.getContext("2d").drawImage(img, 0, 0);
            c.toBlob((blob) => {
              if (!blob || !navigator.clipboard || !window.ClipboardItem) { copy(url, "Photo link copied"); return; }
              navigator.clipboard.write([new ClipboardItem({ "image/png": blob })])
                .then(() => toast("Photo copied, paste it into the chat")).catch(() => copy(url, "Photo link copied"));
            }, "image/png");
          } catch (e) { copy(url, "Photo link copied"); }
        };
        img.onerror = () => copy(url, "Photo link copied");
        img.src = dataUrl;
      });
    } catch (e) { copy(url, "Photo link copied"); }
  }
  function renderSell(el) {
    if (!shopify()) { el.innerHTML = subhead("Sell") + `<div class="muted">Selling tools need a Shopify store.</div>`; wireBack(el); return; }
    const s = suggest || {};
    const f = prodView.facets || {}, cols = f.collections || [], sizes = f.sizes || [];
    const opt = (list, on, any) => `<option value="">${any}</option>` + list.map((v) => `<option value="${esc(v)}"${v === on ? " selected" : ""}>${esc(v)}</option>`).join("");
    let results = "";
    if (prodResults === "busy") results = `<div class="sk" style="width:80%"></div><div class="sk" style="width:60%"></div>`;
    else if (prodResults === "err") results = `<div class="muted">Couldn't load products.</div>`;
    else if (Array.isArray(prodResults) && !prodResults.length && prodView.loaded) results = `<div class="muted">Nothing here.</div>`;
    else if (Array.isArray(prodResults)) results = prodResults.slice(0, 20).map((p, pi) => {
      const vs = p.variants || [], single = vs.length <= 1, v0 = vs[0] || {};
      return `<div class="prow">${p.image ? `<img class="pth" data-pi="${pi}" alt="">` : `<span class="pth"></span>`}
        <div class="pt"><div class="pn">${esc(p.title)}</div>
          <div class="pp">${single ? esc((v0.title && v0.title !== "Default Title" ? v0.title + " · " : "") + (v0.price ? "£" + v0.price : ""))
            : `<select data-pv="${pi}">${vs.map((v, vi) => `<option value="${vi}">${esc(v.title || "Default")}${v.price ? " · £" + esc(v.price) : ""}</option>`).join("")}</select>`}</div></div>
        <div style="display:flex;flex-direction:column;gap:4px">
          <button class="mini" data-padd="${pi}">Add</button>
          ${p.image ? `<button class="mini" data-pimg="${pi}">Photo</button>` : ""}</div></div>`;
    }).join("");
    const total = cart.reduce((sum, i) => sum + (parseFloat(i.price) || 0) * i.qty, 0);
    const count = cart.reduce((sum, i) => sum + i.qty, 0);
    el.innerHTML = subhead("Sell", activeName() ? "for " + esc(activeFirst()) : "") + `
      ${activeCid() ? `<button class="btn wide" data-a="sgo" style="margin-top:0"${s.busy ? " disabled" : ""}>${s.busy ? "Looking…" : (s.picks && s.picks.length ? "Suggest again" : "Suggest pieces for " + esc(activeFirst()))}</button>
        ${s.error ? `<div class="muted" style="margin-top:8px">${esc(s.error)}</div>` : ""}
        ${s.empty ? `<div class="muted" style="margin-top:8px">Nothing in the range stood out for them. Search below.</div>` : ""}
        ${(s.picks || []).length ? s.picks.map((p, i) => `<label class="opt"><input type="checkbox" data-sp="${i}"${p.on ? " checked" : ""}>
          <span style="flex:1;min-width:0"><b>${esc(p.title)}${p.price ? " · " + esc(p.currency || "") + esc(p.price) : ""}</b><i>${esc(p.why || "")}</i></span></label>`).join("")
          + `<div class="acts"><button class="btn" data-a="sadd">Add ticked</button></div>` : ""}` : ""}
      <div class="frow" style="margin-top:${activeCid() ? 16 : 0}px">
        <input class="field" data-a="psearch" placeholder="Search products" value="${esc(prodQ)}">
        <button class="btn" data-a="pgo">Search</button></div>
      ${cols.length || sizes.length ? `<div class="frow" style="margin-top:6px">
        ${cols.length ? `<select class="field" data-a="fcol">${opt(cols, prodView.collection, "All collections")}</select>` : ""}
        ${sizes.length ? `<select class="field" data-a="fsize">${opt(sizes, prodView.size, "All sizes")}</select>` : ""}
        ${(prodView.ids || []).length ? `<button class="btn" data-a="fall">Add all ${prodView.ids.length}</button>` : ""}</div>` : ""}
      <div style="margin-top:8px">${results}</div>
      ${ctx.catalog ? `<div class="rows"><button class="row" data-a="catsend"><span class="rt">Send the catalogue<span class="rd">The house catalogue, as a link</span></span><span class="ar">${ICON.right}</span></button></div>` : ""}
      ${cart.length ? `<div class="sel"><div class="tot">${count} piece${count === 1 ? "" : "s"} · about ${money(total)}</div>
        ${cart.map((i, ci) => `<div class="sline"><span>${esc(i.label)}</span>
          <button class="mini" data-qd="${ci}">−</button><b style="font-size:12px">${i.qty}</b><button class="mini" data-qi="${ci}">+</button>
          <button class="mini" data-rm="${ci}" title="Remove">✕</button></div>`).join("")}
        <div class="acts" style="margin-top:8px">
          ${cart.some((i) => i.id) ? `<button class="btn primary" data-a="csend">${inserter ? "Send selection" : "Copy selection link"}</button>` : ""}
          <button class="btn" data-a="ccat">Send as catalogue</button>
          <button class="mini" data-a="cclear">Clear</button></div></div>` : ""}`;
    wireBack(el);
    const inp = el.querySelector('[data-a="psearch"]');
    const goS = () => { prodQ = (inp && inp.value) || ""; doProductSearch(prodQ); };
    el.querySelector('[data-a="pgo"]').onclick = goS;
    inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); goS(); } };
    const fc = el.querySelector('[data-a="fcol"]'); if (fc) fc.onchange = () => { prodView.collection = fc.value; doProductSearch(prodQ); };
    const fs = el.querySelector('[data-a="fsize"]'); if (fs) fs.onchange = () => { prodView.size = fs.value; doProductSearch(prodQ); };
    const fa = el.querySelector('[data-a="fall"]'); if (fa) fa.onclick = addViewToCart;
    const sgo = el.querySelector('[data-a="sgo"]'); if (sgo) sgo.onclick = runSuggest;
    const sadd = el.querySelector('[data-a="sadd"]'); if (sadd) sadd.onclick = suggestIntoCart;
    el.querySelectorAll("[data-sp]").forEach((b) => b.onchange = () => { const p = ((suggest && suggest.picks) || [])[+b.dataset.sp]; if (p) p.on = b.checked; });
    if (Array.isArray(prodResults)) prodResults.slice(0, 20).forEach((p, pi) => {
      loadThumb(el.querySelector(`img.pth[data-pi="${pi}"]`), p.image, 120);
      const b = el.querySelector(`[data-padd="${pi}"]`);
      if (b) b.onclick = () => { const s2 = el.querySelector(`[data-pv="${pi}"]`); const v = (p.variants || [])[s2 ? +s2.value : 0]; if (v) addToCart(v, p.title, p.id); };
      const im = el.querySelector(`[data-pimg="${pi}"]`); if (im) im.onclick = () => copyImage(p.image);
    });
    cart.forEach((i, ci) => {
      const qd = el.querySelector(`[data-qd="${ci}"]`); if (qd) qd.onclick = () => { i.qty = Math.max(1, i.qty - 1); render(); };
      const qi = el.querySelector(`[data-qi="${ci}"]`); if (qi) qi.onclick = () => { i.qty += 1; render(); };
      const rm = el.querySelector(`[data-rm="${ci}"]`); if (rm) rm.onclick = () => { cart.splice(ci, 1); render(); };
    });
    const cs = el.querySelector('[data-a="csend"]'); if (cs) cs.onclick = () => send(cartLink());
    const cc = el.querySelector('[data-a="ccat"]'); if (cc) cc.onclick = sendCatalogue;
    const cl = el.querySelector('[data-a="cclear"]'); if (cl) cl.onclick = () => { cart = []; render(); };
    const ct = el.querySelector('[data-a="catsend"]'); if (ct) ct.onclick = () => send(tagged(ctx.catalog));
    if (!prodView.loaded) { prodView.loaded = true; doProductSearch(prodQ); }
  }

  // ── more: why, orders, basket, the record ─────────────────────────────────
  function renderMore(el) {
    const d = (client && client.data) || {};
    if (!client || !client.data) { el.innerHTML = subhead("More") + `<div class="muted">Open a client first.</div>`; wireBack(el); return; }
    const orders = d.orders || [];
    const when = (iso) => { const t = Date.parse((iso || "") + "T00:00:00"); return isNaN(t) ? esc(iso || "") : new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); };
    const camps = ((ctx && ctx.campaigns) || []).filter((c) => c.running).slice(0, 4);
    el.innerHTML = subhead(d.name || "This client") + `
      ${(d.reasons || []).length ? `<div class="k">Why they surfaced</div><ul class="reasons">${d.reasons.slice(0, 8).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      ${d.cart && d.cart.value ? `<div class="sect"><div class="k">Open basket</div><div class="muted">${money(d.cart.value)}${d.cart.count ? ` · ${esc(d.cart.count)} item${d.cart.count === 1 ? "" : "s"}` : ""}${d.cart.url ? ` · <a class="lnk" href="${esc(d.cart.url)}" target="_blank" rel="noopener">Open checkout</a>` : ""}</div></div>` : ""}
      ${orders.length ? `<div class="sect"><div class="k">Previous orders</div>${orders.map((o) => `<div class="orow"><span class="od">${when(o.date)}</span><span class="oa">${o.amount != null ? money(o.amount) : ""}</span>${o.titles && o.titles.length ? `<span class="ot">${esc(o.titles.join(", "))}</span>` : ""}</div>`).join("")}</div>` : ""}
      ${d.cid ? `<div class="sect"><div class="k">Mark as contacted</div>
        <div class="chips">${_CONTACT_REASONS.map((x) => `<button class="chip${logReason === x ? " on" : ""}" data-lr="${esc(x)}">${esc(x)}</button>`).join("")}</div>
        <div class="frow" style="margin-top:8px"><input class="field" data-a="lreason" placeholder="A word on what you did" value="${esc(logReason)}"><button class="btn primary" data-a="logc">Mark</button></div></div>` : ""}
      <div class="rows">
        ${d.cid && shopify() ? `<button class="row" data-a="pipe"><span class="rt">Add to the pipeline<span class="rd">So the team can see them being looked after</span></span><span class="ar">${ICON.right}</span></button>` : ""}
        ${camps.map((c, i) => d.cid ? `<button class="row" data-cadd="${i}"><span class="rt">Add to ${esc(c.name)}<span class="rd"><span class="live">Live</span> · ${esc(c.starts)} to ${esc(c.ends)}</span></span><span class="ar">${ICON.right}</span></button>` : "").join("")}
        ${d.cid && shopify() ? `<button class="row" data-a="noteopen"><span class="rt">Add a note<span class="rd">Kept on their record in your store</span></span><span class="ar">${ICON.right}</span></button>` : ""}
        ${d.adminUrl ? `<a class="row" href="${esc(d.adminUrl)}" target="_blank" rel="noopener"><span class="rt">Open in your store</span><span class="ar">${ICON.right}</span></a>` : ""}
        ${d.dashboard ? `<a class="row" href="${esc(d.dashboard)}" target="_blank" rel="noopener"><span class="rt">Open in Halia</span><span class="ar">${ICON.right}</span></a>` : ""}
      </div>
      <div data-a="notebox"></div>`;
    wireBack(el);
    el.querySelectorAll("[data-lr]").forEach((b) => b.onclick = () => { logReason = b.dataset.lr; render(); });
    const lr = el.querySelector('[data-a="lreason"]'); if (lr) lr.oninput = () => { logReason = lr.value; };
    const lc = el.querySelector('[data-a="logc"]'); if (lc) lc.onclick = () => { markContacted(d.cid, d.name, logReason); logReason = ""; };
    const pipe = el.querySelector('[data-a="pipe"]'); if (pipe) pipe.onclick = () => act({ action: "pipeline", cid: d.cid }, "Added to the pipeline");
    camps.forEach((c, i) => { const b = el.querySelector(`[data-cadd="${i}"]`); if (b) b.onclick = () => act({ action: "campaign_add", campaign_id: c.id, cid: d.cid }, "Added to " + c.name); });
    const no = el.querySelector('[data-a="noteopen"]');
    if (no) no.onclick = () => {
      const nb = el.querySelector('[data-a="notebox"]');
      nb.innerHTML = `<div class="sect"><div class="k">Note</div><textarea class="field" data-a="note" rows="3" placeholder="What to remember about ${esc(first(d.name) || "them")}"></textarea>
        <div class="acts"><button class="btn primary" data-a="notesave">Save note</button></div></div>`;
      const ta = nb.querySelector('[data-a="note"]'); ta.focus();
      nb.querySelector('[data-a="notesave"]').onclick = () => {
        const v = (ta.value || "").trim(); if (!v) { toast("Write a note first"); return; }
        act({ action: "note", cid: d.cid, note: v }, "Note saved"); ta.value = "";
      };
    };
  }

  // ── team ──────────────────────────────────────────────────────────────────
  function renderTeam(el) {
    const todos = (ctx && ctx.todos) || [];
    const cname = activeName();
    const fill = (m) => m.replace("{client}", cname || "this client");
    el.innerHTML = subhead("Team") + `
      ${activeCid() ? `<div class="k">Mark ${esc(first(cname))} as contacted</div>
        <div class="chips">${_CONTACT_REASONS.map((x) => `<button class="chip${logReason === x ? " on" : ""}" data-lr="${esc(x)}">${esc(x)}</button>`).join("")}</div>
        <div class="frow" style="margin-top:8px"><input class="field" data-a="lreason" placeholder="A word on what you did" value="${esc(logReason)}"><button class="btn primary" data-a="logc">Mark</button></div>` : ""}
      <div class="sect"><div class="k">Tell the team</div>
        ${_TEAM_MSGS.map((m, i) => `<div class="sline" style="padding:6px 0"><span>${esc(fill(m))}</span>
          ${inserter ? `<button class="mini" data-tmi="${i}">Insert</button>` : ""}<button class="mini" data-tmc="${i}">Copy</button></div>`).join("")}</div>
      <div class="sect"><div class="k">Needs a hand${todos.length ? ` · ${todos.length}` : ""}</div>
        ${todos.length ? todos.map((t, i) => `<div class="sline" style="padding:6px 0"><span style="white-space:normal">${esc(t.text)}</span>${t.cid ? `<button class="mini" data-td="${i}">Done</button>` : ""}</div>`).join("")
          : `<div class="muted">Nothing needs the team right now.</div>`}</div>
      <div class="src" style="margin-top:16px">${ctx && ctx.slack ? "Contacts you mark post to the team's Slack, so nobody messages a client twice." : "Connect Slack in Halia and the team hears when a client is contacted."}</div>`;
    wireBack(el);
    el.querySelectorAll("[data-lr]").forEach((b) => b.onclick = () => { logReason = b.dataset.lr; render(); });
    const lr = el.querySelector('[data-a="lreason"]'); if (lr) lr.oninput = () => { logReason = lr.value; };
    const lc = el.querySelector('[data-a="logc"]'); if (lc) lc.onclick = () => { markContacted(activeCid(), cname, logReason); logReason = ""; };
    _TEAM_MSGS.forEach((m, i) => {
      const ins = el.querySelector(`[data-tmi="${i}"]`); if (ins) ins.onclick = () => place(fill(m));
      const cp = el.querySelector(`[data-tmc="${i}"]`); if (cp) cp.onclick = () => copy(fill(m), "Copied");
    });
    todos.forEach((t, i) => { const b = el.querySelector(`[data-td="${i}"]`); if (b) b.onclick = () => markContacted(t.cid, t.name, ""); });
  }

  // ── share (storefront) ────────────────────────────────────────────────────
  function shareFirst() { return first(shareClient && shareClient.name); }
  function buildShareDraft() {
    const ops = shareOpeners(), op = ops[shareOpener] || ops[0];
    const parts = [];
    const f = shareFirst();
    if (shareGreeting && f) parts.push("Dear " + f + ",");
    if (op && op.body) parts.push(fillOpener(op.body));
    const link = share && share.url ? tagged(share.url) : "";
    if (link) parts.push(link);
    shareDraft = parts.join("\n\n");
    const ta = root && root.querySelector('[data-a="shdraft"]');
    if (ta) ta.value = shareDraft;
  }
  function doClientSearch(q) {
    clientQuery = q; clientResults = "busy"; render();
    try {
      chrome.runtime.sendMessage({ type: "halia:clients", q }, (r) => {
        clientResults = (chrome.runtime.lastError || !r || r.error) ? "err" : (r.clients || []);
        render();
        const inp = root && root.querySelector('[data-a="shsearch"]');
        if (inp && q) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
      });
    } catch (e) { clientResults = "err"; render(); }
  }
  function currentShareText() { const ta = root && root.querySelector('[data-a="shdraft"]'); return (ta && ta.value) || shareDraft || ""; }
  function logShareContact() {
    if (!shareClient) return;
    const kind = SHARE_KIND[shareKind()];
    act({ action: "contacted", cid: shareClient.cid || "", client_name: shareClient.name,
      reason: "Shared: " + (share && share.title ? share.title : (kind ? kind.title : "a page")) }, "Marked as contacted");
  }
  function renderShare(el) {
    if (!share) { renderHome(el); return; }
    const meta = SHARE_KIND[shareKind()], ops = shareOpeners();
    let list = "";
    if (clientResults === "busy") list = `<div class="muted" style="padding:10px 12px">Looking…</div>`;
    else if (clientResults === "err") list = `<div class="muted" style="padding:10px 12px">Couldn't reach your book.</div>`;
    else if (Array.isArray(clientResults)) list = clientResults.length ? clientResults.slice(0, 40).map((c, i) => `<button class="litem" data-ci="${i}">
        <span class="cg ${gradeClass(c.grade)}">${esc(c.grade || "·")}</span><span class="cn">${esc(c.name)}</span>${c.phone ? "" : `<span class="cx">no number</span>`}</button>`).join("")
      : `<div class="muted" style="padding:10px 12px">No one by that name in your book.</div>`;
    el.innerHTML = `
      <div class="k">${esc(meta.title)}</div>
      <div style="font-size:14px;font-weight:600;line-height:1.3;word-break:break-word">${esc(share.title || share.url)}</div>
      <div class="k" style="margin-top:14px">${esc(meta.action)}</div>
      <div class="chips">${ops.map((o, i) => `<button class="chip${i === shareOpener ? " on" : ""}" data-op="${i}">${esc(o.label)}</button>`).join("")}</div>
      ${shareClient ? `
        <div class="person" style="margin-top:14px"><span class="cg ${gradeClass(shareClient.grade)}">${esc(shareClient.grade || "·")}</span>
          <span style="flex:1;font-weight:600;font-size:13px">${esc(shareClient.name)}</span>
          <button class="ic" data-a="shclear" title="Choose someone else">${ICON.x}</button></div>
        <textarea class="field" data-a="shdraft" rows="6" style="margin-top:8px">${esc(shareDraft || "")}</textarea>
        <label class="tgl" style="margin-top:8px"><input type="checkbox" data-a="shgreet"${shareGreeting ? " checked" : ""}>Open with “Dear ${esc(shareFirst() || "name")},”</label>
        ${digits(shareClient.phone) ? "" : `<div class="muted" style="margin-top:8px">No number on file. Copy the message and send it your way.</div>`}
        <div class="acts">
          <button class="btn primary" data-a="shwa">${digits(shareClient.phone) ? "Message on WhatsApp" : "Open WhatsApp"}</button>
          <button class="btn" data-a="shcopy">Copy</button></div>
        <button class="lnk" data-a="shlog">Mark as contacted</button>
      ` : `
        <div class="frow" style="margin-top:14px"><input class="field" data-a="shsearch" placeholder="Who is it for?" value="${esc(clientQuery)}"><button class="btn" data-a="shgo">Find</button></div>
        <div class="list">${list}</div>`}
      ${burstStrip()}`;
    wireStrip(el);
    el.querySelectorAll("[data-op]").forEach((b) => b.onclick = () => { shareOpener = +b.dataset.op; render(); buildShareDraft(); });
    if (shareClient) {
      el.querySelector('[data-a="shclear"]').onclick = () => { shareClient = null; render(); };
      const gr = el.querySelector('[data-a="shgreet"]'); gr.onchange = () => { shareGreeting = gr.checked; buildShareDraft(); };
      el.querySelector('[data-a="shwa"]').onclick = () => {
        const text = currentShareText(); if (!text) { toast("Pick an opener first"); return; }
        const dd = digits(shareClient.phone);
        const url = dd ? "https://wa.me/" + dd + "?text=" + encodeURIComponent(text) : "https://api.whatsapp.com/send?text=" + encodeURIComponent(text);
        try { window.open(url, "_blank", "noopener"); } catch (e) { copy(text, "Copied, paste it into WhatsApp"); }
        logShareContact();
      };
      el.querySelector('[data-a="shcopy"]').onclick = () => { const t = currentShareText(); if (t) { copy(t, "Message copied"); logShareContact(); } };
      el.querySelector('[data-a="shlog"]').onclick = logShareContact;
    } else {
      const inp = el.querySelector('[data-a="shsearch"]');
      const goF = () => doClientSearch((inp && inp.value) || "");
      el.querySelector('[data-a="shgo"]').onclick = goF;
      inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); goF(); } };
      el.querySelectorAll("[data-ci]").forEach((b) => b.onclick = () => { shareClient = clientResults[+b.dataset.ci]; shareDraft = null; render(); buildShareDraft(); });
      if (clientResults === null) doClientSearch("");
    }
  }

  // ── several clients (the burst) ───────────────────────────────────────────
  function saveBurst() { try { if (burst) chrome.storage.local.set({ haliaBurst: burst }); else chrome.storage.local.remove("haliaBurst"); } catch (e) { /* ignore */ } }
  function loadBurst(b) { burst = (b && Array.isArray(b.items) && (Date.now() - (b.started || 0)) < BURST_TTL) ? b : null; render(); }
  function burstChannels() {
    if (channel === "whatsapp") return ["whatsapp"];
    if (channel === "email") return ["email"];
    if (channel === "line") return ["line"];
    return ["whatsapp", "email", "line"];
  }
  const _BURST_CHAN_WORD = { whatsapp: "WhatsApp", email: "Email", line: "LINE" };
  function burstItem() { return (burst && burst.items[burst.i]) || null; }
  function burstText(it) { return it.text != null ? it.text : withToggles(it.message || ""); }
  function burstProgress() {
    return { sent: burst.items.filter((x) => x.status === "sent").length,
      skipped: burst.items.filter((x) => x.status === "skipped").length + (burst.skipped || []).length };
  }
  function burstMatchesCurrent(it) {
    const d = client && client.data; if (!d || !it) return false;
    if (d.cid && it.cid && String(d.cid) === String(it.cid)) return true;
    const a = digits(d.phone).slice(-9), b = digits(it.phone).slice(-9);
    if (a && b && a.length === 9 && a === b) return true;
    return !!(d.name && it.name && d.name.trim().toLowerCase() === it.name.trim().toLowerCase());
  }
  function consentLine(c) {
    const w = (v) => v === "subscribed" ? "subscribed" : v === "not_subscribed" ? "not subscribed" : "not on file";
    if (!c || (c.email === "unknown" && c.sms === "unknown")) return "Consent not on file";
    return "Email " + w(c.email) + " · SMS " + w(c.sms);
  }
  function warnLine(it) {
    const lc = it.last_contact;
    return ((it.warn || []).indexOf("contacted_recently") >= 0 && lc) ? "Contacted " + ago(lc.at) + (lc.by ? " by " + lc.by : "") : "";
  }
  function loadBurstClients(q) {
    bpick.q = q; bpick.list = "busy"; render();
    try {
      chrome.runtime.sendMessage({ type: "halia:clients", q }, (r) => {
        bpick.list = (chrome.runtime.lastError || !r || r.error) ? "err" : (r.clients || []);
        render();
        const inp = root && root.querySelector('[data-a="bq"]');
        if (inp && q) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
      });
    } catch (e) { bpick.list = "err"; render(); }
  }
  function startBurst() {
    const req = { template: { name: bpick.tpl }, channel: bpick.chan || burstChannels()[0] };
    if (bpick.camp) req.campaign_id = bpick.camp;
    if (bpick.ids.size) req.cids = Array.from(bpick.ids);
    if (!req.campaign_id && !req.cids) { toast("Choose who to message"); return; }
    if (!bpick.tpl) { toast("Choose a template"); return; }
    toast("Preparing…");
    try {
      chrome.runtime.sendMessage({ type: "halia:burst", body: req }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) { toast((r && r.detail) || "Couldn't prepare that"); return; }
        if (!(r.clients || []).length) { toast("No one to message on " + (_BURST_CHAN_WORD[req.channel] || "that channel")); return; }
        burst = { template: r.template || bpick.tpl, channel: req.channel, started: Date.now(), i: 0,
          items: r.clients.map((c) => Object.assign({}, c, { status: "pending" })), skipped: r.skipped || [] };
        bpick = { open: false, camp: "", q: "", list: null, ids: new Set(), tpl: "", chan: "" };
        saveBurst(); render();
        if (burst.skipped.length) toast(burst.skipped.length + " skipped, no address for " + _BURST_CHAN_WORD[req.channel]);
      });
    } catch (e) { toast("Couldn't prepare that"); }
  }
  function burstAdvance(sent) {
    const it = burstItem(); if (!it) return;
    if (sent) { it.status = "sent"; markContacted(it.cid, it.name, "Sent " + (burst.template || "a message") + " on " + (_BURST_CHAN_WORD[burst.channel] || burst.channel), true); }
    else it.status = "skipped";
    burst.i += 1; saveBurst(); render();
  }
  function finishBurst() {
    const p = burstProgress();
    if (p.sent) act({ action: "burst_done", n: p.sent, template: burst.template, channel: burst.channel }, "The team knows");
    burst = null; saveBurst(); go("home");
  }
  function gmailCompose(it, text) {
    return "https://mail.google.com/mail/?view=cm&fs=1&to=" + encodeURIComponent(it.email || "")
      + "&su=" + encodeURIComponent(it.subject || "") + "&body=" + encodeURIComponent(text);
  }
  function renderSeveral(el) {
    if (!burst) { renderSeveralBuilder(el); return; }
    const it = burstItem(), p = burstProgress();
    if (!it) {
      el.innerHTML = subhead("Several clients") + `<div class="muted">${p.sent} sent${p.skipped ? `, ${p.skipped} skipped` : ""}.</div>
        <button class="btn primary wide" data-a="bfin">Finish</button>`;
      wireBack(el); el.querySelector('[data-a="bfin"]').onclick = finishBurst; return;
    }
    const text = burstText(it), word = _BURST_CHAN_WORD[burst.channel] || "";
    const onSurface = channel === burst.channel, matched = onSurface && burstMatchesCurrent(it);
    const here = client && client.data && client.data.name;
    let lead = "", acts = "";
    if (onSurface && (burst.channel === "whatsapp" || burst.channel === "line")) {
      if (matched) acts += `<button class="btn primary" data-a="bins">Insert</button>`;
      else {
        lead = here && here.trim().toLowerCase() !== it.name.trim().toLowerCase() ? `This chat is ${esc(here)}, not ${esc(it.name)}.` : `Open the chat with ${esc(it.name)}.`;
        if (inserter) acts += `<button class="btn" data-a="bins">Insert anyway</button>`;
      }
    } else if (onSurface && burst.channel === "email") {
      if (inserter) acts += `<button class="btn primary" data-a="bins">Insert</button>`;
      acts += `<button class="btn" data-a="bgm">New email to ${esc(it.first || it.name)}</button>`;
    } else if (burst.channel === "whatsapp") acts += `<button class="btn primary" data-a="bwa">Open WhatsApp</button>`;
    else if (burst.channel === "email") acts += `<button class="btn primary" data-a="bgm">Open in Gmail</button><button class="btn" data-a="bmail">Mail app</button>`;
    else lead = "Copy the message and paste it into LINE.";
    el.innerHTML = subhead(`${burst.i + 1} of ${burst.items.length}`, esc(word)) + `
      <div class="person"><span class="cg ${gradeClass(it.grade)}">${esc(it.grade || "·")}</span>
        <div class="who"><div class="nm">${esc(it.name)}</div><div class="facts">${esc(consentLine(it.consent))}${warnLine(it) ? ` · <span style="color:#8a4b1f">${esc(warnLine(it))}</span>` : ""}</div></div></div>
      ${lead ? `<div class="muted" style="margin-top:10px">${lead}</div>` : ""}
      ${it.subject && burst.channel === "email" ? `<input class="field" data-a="bsub" value="${esc(it.subject)}" style="margin-top:12px">` : ""}
      <textarea class="field" data-a="bmsg" rows="7" style="margin-top:8px">${esc(text)}</textarea>
      <div class="acts">${acts}<button class="btn" data-a="bcopy">Copy</button></div>
      <div class="acts" style="margin-top:8px">
        <button class="btn primary" data-a="bsent">Sent, next</button>
        <button class="btn" data-a="bskip">Skip</button>
        <button class="lnk" data-a="bstop" style="padding:0 6px">Stop</button></div>`;
    wireBack(el);
    const ta = el.querySelector('[data-a="bmsg"]'); ta.oninput = () => { it.text = ta.value; saveBurst(); };
    const sub = el.querySelector('[data-a="bsub"]'); if (sub) sub.oninput = () => { it.subject = sub.value; saveBurst(); };
    const cur = () => (ta.value || "");
    const q = (k) => el.querySelector(`[data-a="${k}"]`);
    if (q("bins")) q("bins").onclick = () => place(cur());
    q("bcopy").onclick = () => copy(cur(), "Message copied");
    if (q("bwa")) q("bwa").onclick = () => { try { window.open("https://wa.me/" + digits(it.phone) + "?text=" + encodeURIComponent(cur()), "_blank", "noopener"); } catch (e) { copy(cur(), "Copied, paste it into WhatsApp"); } };
    if (q("bgm")) q("bgm").onclick = () => { const t = cur(); if (t.length > 6000) { copy(t, "Too long for a link, copied instead"); return; } try { window.open(gmailCompose(it, t), "_blank", "noopener"); } catch (e) { copy(t, "Copied"); } };
    if (q("bmail")) q("bmail").onclick = () => { location.href = "mailto:" + encodeURIComponent(it.email || "") + "?subject=" + encodeURIComponent(it.subject || "") + "&body=" + encodeURIComponent(cur()); };
    q("bsent").onclick = () => burstAdvance(true);
    q("bskip").onclick = () => burstAdvance(false);
    q("bstop").onclick = () => {
      if (burstProgress().sent === 0) { finishBurst(); return; }
      q("bstop").outerHTML = `<span class="muted" style="font-size:12.5px">Stop here? The rest will not be sent. <button class="lnk" data-a="bstopyes" style="padding:0">Yes, stop</button></span>`;
      el.querySelector('[data-a="bstopyes"]').onclick = finishBurst;
    };
  }
  function renderSeveralBuilder(el) {
    const camps = ((ctx && ctx.campaigns) || []).filter((c) => c.members > 0);
    if (!bpick.open) {
      el.innerHTML = subhead("Several clients") + `<div class="muted">One message, written for each person, sent from your own ${esc(_CHAN_LABEL[channel] === "Store" ? "apps" : (_CHAN_LABEL[channel] || "apps"))} one at a time.</div>
        <button class="btn primary wide" data-a="bopen">Choose clients</button>
        ${camps.length ? `<div class="rows">${camps.slice(0, 4).map((c, i) => `<button class="row" data-bc="${i}"><span class="rt">Everyone in ${esc(c.name)}<span class="rd">${c.members} client${c.members === 1 ? "" : "s"}</span></span><span class="ar">${ICON.right}</span></button>`).join("")}</div>` : ""}`;
      wireBack(el);
      el.querySelector('[data-a="bopen"]').onclick = () => { bpick.open = true; bpick.camp = ""; render(); loadBurstClients(""); };
      camps.slice(0, 4).forEach((c, i) => { const b = el.querySelector(`[data-bc="${i}"]`); if (b) b.onclick = () => { bpick.open = true; bpick.camp = c.id; render(); }; });
      return;
    }
    const tpls = templateList(), chans = burstChannels();
    const camp = camps.find((c) => c.id === bpick.camp);
    const n = camp ? camp.members : bpick.ids.size;
    let who;
    if (camp) who = `<div class="card"><div class="rn">${esc(camp.name)}</div><div class="rd">${camp.members} client${camp.members === 1 ? "" : "s"}</div>
        <button class="lnk" data-a="bpickinstead">Choose clients instead</button></div>`;
    else {
      const list = bpick.list; let rows = "";
      if (list === "busy") rows = `<div class="muted" style="padding:10px 12px">Looking…</div>`;
      else if (list === "err") rows = `<div class="muted" style="padding:10px 12px">Couldn't reach your book.</div>`;
      else if (Array.isArray(list)) rows = list.length ? list.slice(0, 60).map((c, i) => `<button class="litem${bpick.ids.has(String(c.cid)) ? " sel" : ""}" data-bi="${i}">
          <span class="cg ${gradeClass(c.grade)}">${esc(c.grade || "·")}</span><span class="cn">${esc(c.name)}</span>
          ${bpick.ids.has(String(c.cid)) ? `<span class="cx">✓</span>` : (c.phone || c.email ? "" : `<span class="cx">no address</span>`)}</button>`).join("")
        : `<div class="muted" style="padding:10px 12px">No one by that name in your book.</div>`;
      who = `<input class="field" data-a="bq" placeholder="Search your book" value="${esc(bpick.q)}">
        <div class="list">${rows}</div>
        <div class="acts" style="margin-top:6px">${Array.isArray(list) && list.length ? `<button class="mini" data-a="ball">Tick all shown</button>` : ""}
        ${bpick.ids.size ? `<button class="mini" data-a="bnone">Clear ${bpick.ids.size}</button>` : ""}</div>`;
    }
    el.innerHTML = subhead("Several clients") + who + `
      <div class="k" style="margin-top:14px">Template</div>
      <select class="field" data-a="btpl"><option value="">Choose a template</option>${tpls.map((t) => `<option${t.name === bpick.tpl ? " selected" : ""}>${esc(t.name)}</option>`).join("")}</select>
      ${chans.length > 1 ? `<div class="k" style="margin-top:10px">Send on</div>
        <select class="field" data-a="bchan">${chans.map((c) => `<option value="${c}"${(bpick.chan || chans[0]) === c ? " selected" : ""}>${_BURST_CHAN_WORD[c]}</option>`).join("")}</select>` : ""}
      <button class="btn primary wide" data-a="bgo"${n ? "" : " disabled"}>Prepare ${n || ""} message${n === 1 ? "" : "s"}</button>
      <button class="lnk" data-a="bcancel">Cancel</button>`;
    wireBack(el);
    const q = (k) => el.querySelector(`[data-a="${k}"]`);
    if (q("bq")) q("bq").oninput = () => loadBurstClients(q("bq").value);
    el.querySelectorAll("[data-bi]").forEach((b) => b.onclick = () => {
      const c = bpick.list[+b.dataset.bi]; if (!c) return;
      const k = String(c.cid); if (bpick.ids.has(k)) bpick.ids.delete(k); else bpick.ids.add(k); render();
    });
    if (q("ball")) q("ball").onclick = () => { bpick.list.slice(0, 60).forEach((c) => bpick.ids.add(String(c.cid))); render(); };
    if (q("bnone")) q("bnone").onclick = () => { bpick.ids = new Set(); render(); };
    if (q("bpickinstead")) q("bpickinstead").onclick = () => { bpick.camp = ""; render(); loadBurstClients(""); };
    q("btpl").onchange = () => { bpick.tpl = q("btpl").value; };
    if (q("bchan")) q("bchan").onchange = () => { bpick.chan = q("bchan").value; };
    q("bgo").onclick = () => { bpick.tpl = q("btpl").value; if (q("bchan")) bpick.chan = q("bchan").value; startBurst(); };
    q("bcancel").onclick = () => { bpick = { open: false, camp: "", q: "", list: null, ids: new Set(), tpl: "", chan: "" }; render(); };
  }

  // ── public API ────────────────────────────────────────────────────────────
  function resetForClient() {
    draft = null; draftInstr = ""; suggest = null; suggestNote = ""; book = null; logReason = "";
    if (["reply", "book", "more"].indexOf(view) >= 0) view = "home";
  }
  const API = {
    mount() {
      ensure();
      try {
        chrome.storage.local.get(["panelOpen", "haliaBurst"], (r) => {
          if (r && r.panelOpen === true) setOpen(true, false);
          if (r && r.haliaBurst) loadBurst(r.haliaBurst);
        });
        chrome.storage.onChanged.addListener((ch, area) => {
          if (area === "local" && ch.haliaBurst) loadBurst(ch.haliaBurst.newValue || null);
        });
        chrome.storage.sync.get(["tplGreeting", "tplSignoff", "tplRecent"], (r) => {
          if (Array.isArray(r.tplRecent)) tplRecent = r.tplRecent;
          if (r && typeof r.tplGreeting === "boolean") tplGreeting = r.tplGreeting;
          if (r && typeof r.tplSignoff === "boolean") tplSignoff = r.tplSignoff;
          render();
        });
      } catch (e) { /* ignore */ }
    },
    setContext(c) {
      ctx = c && !c.error ? c : null;
      if (ctx && teamDefault && view === "home" && !client) view = "team";
      render();
    },
    // The storefront surface hands the toolbar the page to share (url + title + kind).
    setShare(info) {
      const prevKind = share && share.kind;
      share = (info && info.url) ? { url: info.url, title: info.title || "", kind: info.kind || "press" } : null;
      if (share && share.kind !== prevKind) { shareOpener = 0; shareDraft = null; }
      if (share && shareClient) buildShareDraft();
      render();
    },
    setClient(state) {
      // A client the associate searched for stays until they let go of it.
      if (client && client.manual && state && !state.found && !state.loading) return;
      const prevKey = client && client.data ? (client.data.cid || client.data.email || client.data.name) : "";
      client = state; // null | {loading,name} | {found,data} | {notfound,name} | {error}
      if (state && state.found) client = { data: state.data };
      const key = client && client.data ? (client.data.cid || client.data.email || client.data.name) : "";
      if (key !== prevKey) resetForClient();
      if (client && client.data && !open && !userCollapsed) setOpen(true, false);
      render();
    },
    setInserter(fn) { inserter = fn; },
    setThreadReader(fn) { threadReader = fn; },
    setChannel(ch) { if (CHAN[ch]) channel = ch; },
    // Team surfaces (Slack, Teams) open on the Team view; the client and team views are one card now.
    setMode(m) { teamDefault = m === "internal"; if (teamDefault && view === "home" && !client) { view = "team"; render(); } },
    hide() { setOpen(false, false); }
  };

  window.HaliaPanel = API;
  window.HaliaBadge = API;
})();
