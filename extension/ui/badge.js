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
      background: #303030; color: #ffffff; border: 0; cursor: pointer; padding: 12px 7px;
      writing-mode: vertical-rl; text-orientation: mixed; letter-spacing: .12em; font-size: 11px;
       display: flex; align-items: center; gap: 8px; box-shadow: -2px 0 12px rgba(0,0,0,.18); }
    .handle .m { writing-mode: horizontal-tb; font-size: 14px; color: #6FBFA0; }
    .dock.open .handle { display: none; }
    .panel { position: fixed; right: 0; top: 0; height: 100vh; width: 364px; max-width: 92vw;
      z-index: 2147483647; background: #ffffff; color: #303030; border-left: 1px solid #e3e3e3;
      box-shadow: -12px 0 44px rgba(0,0,0,.16); display: flex; flex-direction: column;
      transform: translateX(100%); transition: transform .22s cubic-bezier(.2,.7,.2,1); }
    .dock.open .panel { transform: translateX(0); }
    .bar { display: flex; align-items: center; gap: 8px; padding: 15px 18px; border-bottom: 1px solid #e3e3e3;
      background: #f7f7f7; flex: none; position: relative; }
    .bar .m { color: #1F564A; font-size: 15px; }
    /* the engine's scanline: a hairline that sweeps under the bar whenever Halia is working */
    .bar::after { content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px;
      background: linear-gradient(90deg, transparent 15%, #1F564A 40%, #6FBFA0 50%, #1F564A 60%, transparent 85%);
      background-size: 240% 100%; opacity: 0; transition: opacity .25s ease; pointer-events: none; }
    .dock.thinking .bar::after { opacity: 1; }
    .bar .t { font-weight: 600;   font-size: 11px; color: #616161; }
    .bar .sp { flex: 1; }
    .modebtn { border: 1px solid #cccccc; background: #fff; color: #616161; font-size: 10px;
        padding: 3px 8px; cursor: pointer; }
    .modebtn.int { background: #303030; color: #ffffff; border-color: #303030; }
    .chip { border: 1px solid #cccccc; background: #fff; color: #303030; cursor: pointer; font-size: 11px;
      padding: 3px 8px; }
    .chip:hover { background: #f7f7f7; }
    .todo { padding: 8px 10px; border: 1px solid #e3e3e3; background: #fff; margin-bottom: 6px;
      display: flex; gap: 8px; align-items: center; }
    .todo .tt { flex: 1; font-size: 12.5px; line-height: 1.35; }
    .ic { border: 0; background: transparent; cursor: pointer; color: #8a8a8a; font-size: 15px; padding: 2px 5px; }
    .ic:hover { color: #303030; }
    /* crossbar: switch between Client / Reply / Sell so only one view shows at a time */
    .tabs { display: flex; padding: 0 8px; background: #f7f7f7; border-bottom: 1px solid #e3e3e3; flex: none; }
    .tabs.hide { display: none; }
    .tab { flex: 1; border: 0; background: transparent; color: #8a8a8a; font-size: 11px; 
      letter-spacing: .06em; padding: 12px 4px; cursor: pointer; border-bottom: 2px solid transparent; }
    .tab:hover { color: #303030; }
    .tab.on { color: #303030; border-bottom-color: #1F564A; font-weight: 600; }
    .lnkbtn { background: none; border: 0; color: #1F564A; font-size: 11.5px; cursor: pointer; padding: 6px 0 0; }
    .lnkbtn:hover { text-decoration: underline; }
    .scroll { overflow-y: auto; flex: 1; }
    .sec { border-bottom: 1px solid #e3e3e3; padding: 18px; }
    .sh { font-size: 11.5px;   color: #8a8a8a; margin: 0 0 12px;
      display: flex; align-items: center; gap: 7px; }
    .sh .n { background: #e3e3e3; color: #616161; font-size: 10px; padding: 1px 6px; }
    .head { display: flex; align-items: flex-start; gap: 13px; }
    .grade { flex: none; min-width: 44px; height: 44px; padding: 0 8px; display: flex; align-items: center;
      justify-content: center; font-weight: 700; font-size: 19px; color: #fff; background: #616161; }
    .grade.g-a { background: #1F564A; } .grade.g-b { background: #55606b; } .grade.g-c { background: #8a8a8a; }
    /* initials avatar with a grade badge */
    .idw { position: relative; flex: none; }
    .ava2 { width: 52px; height: 52px; border-radius: 50%; background: #e7efeb; color: #1F564A;
      display: grid; place-items: center; font-weight: 600; font-size: 15px; letter-spacing: .02em; }
    .gbadge { position: absolute; right: -4px; bottom: -4px; min-width: 20px; height: 18px; padding: 0 4px;
      border-radius: 9px; display: flex; align-items: center; justify-content: center; font-weight: 700;
      font-size: 10px; color: #fff; background: #616161; border: 2px solid #ffffff; overflow: hidden; }
    .gbadge.g-a { background: #1F564A; } .gbadge.g-b { background: #55606b; } .gbadge.g-c { background: #8a8a8a; }
    /* handle grade chip (shown collapsed when a client is recognised) */
    .handle .hg { writing-mode: horizontal-tb; color: #fff; font-size: 10px; font-weight: 700;
      padding: 2px 5px; margin-bottom: 3px; letter-spacing: .02em; }
    /* skeleton shimmer while a client loads */
    .sk-row { height: 12px; margin: 8px 0; border-radius: 2px;
      background: linear-gradient(90deg, #e3e3e3 25%, #f6f2ea 40%, #e3e3e3 60%); background-size: 300% 100%;
      animation: shine 1.25s ease-in-out infinite; }
    .sk-row.gr { width: 46px; height: 46px; border-radius: 50%; margin: 0; flex: none; }
    /* pixel-grid loader (square cells, chevron wavefront) for indeterminate work like a live brief */
    .loadrow { display: flex; align-items: center; gap: 9px; margin-top: 10px; }
    .pxgrid { display: inline-grid; grid-template-columns: repeat(3, 5px); gap: 2px; }
    .pxgrid i { width: 5px; height: 5px; background: #616161; opacity: .3; animation: pxon 650ms ease-in-out infinite; }
    .shimtx { -webkit-background-clip: text; background-clip: text; color: transparent; font-weight: 600; font-size: 12.5px;
      background-image: linear-gradient(90deg, #8a8a8a 20%, #303030 50%, #8a8a8a 80%); background-size: 220% 100%;
      animation: shimtx 1.1s linear infinite; }
    .elapsed { margin-left: auto; font: 11px ui-monospace, Menlo, monospace; color: #8a8a8a; font-variant-numeric: tabular-nums; }
    /* collapsible sections */
    .sh { cursor: pointer; user-select: none; }
    .sh::after { content: "⌄"; margin-left: auto; color: #8a8a8a; font-size: 14px; line-height: 1; transition: transform .2s; }
    .sec.folded .sh::after { transform: rotate(-90deg); }
    .sec.folded > :not(.sh) { display: none !important; }
    @media (prefers-reduced-motion: no-preference) {
      .fadein { animation: hfade .32s cubic-bezier(.2,.7,.2,1) both; }
      @keyframes hfade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
      @keyframes shine { 0% { background-position: 130% 0; } 100% { background-position: -30% 0; } }
      @keyframes pxon { 0%, 100% { opacity: .3; } 45% { opacity: .95; } }
      @keyframes shimtx { to { background-position: -220% 0; } }
      /* alive: a switched tab rises in; the client's reasons + actions cascade */
      .vin { animation: hfade .34s cubic-bezier(.2,.7,.2,1) both; }
      .reasons li { animation: hfade .3s cubic-bezier(.2,.7,.2,1) both; }
      .reasons li:nth-child(2) { animation-delay: .05s; }
      .reasons li:nth-child(3) { animation-delay: .10s; }
      .reasons li:nth-child(4) { animation-delay: .15s; }
      .reasons li:nth-child(5) { animation-delay: .20s; }
      .reasons li:nth-child(6) { animation-delay: .25s; }
      .acts .btn { animation: hfade .3s cubic-bezier(.2,.7,.2,1) both; }
      /* a light sheen sweeps the grade badge when a new client lands */
      .head.fadein .gbadge::after { content: ""; position: absolute; inset: 0; border-radius: 9px;
        background: linear-gradient(115deg, transparent 32%, rgba(255,255,255,.55) 50%, transparent 68%);
        transform: translateX(-130%); animation: sheen .8s ease .18s 1 both; }
      @keyframes sheen { to { transform: translateX(130%); } }
      /* the ⁂ mark breathes everywhere — a resting heartbeat; quicker while the engine works */
      .foot .m.live { animation: breathe 2.6s ease-in-out infinite; }
      .bar .m, .handle .m { animation: breathe 3.4s ease-in-out infinite; }
      .dock.thinking .bar .m { animation-duration: 1.1s; }
      @keyframes breathe { 0%, 100% { opacity: .5; } 50% { opacity: 1; } }
      .dock.thinking .bar::after { animation: scan 1.5s linear infinite; }
      @keyframes scan { from { background-position: 130% 0; } to { background-position: -130% 0; } }
      /* a new client's identity pops in, then the sheen sweeps the grade */
      .head.fadein .grade, .head.fadein .ava2 { animation: hpop .38s cubic-bezier(.2,.8,.3,1.15) both; }
      @keyframes hpop { from { transform: scale(.72); opacity: .3; } to { transform: none; opacity: 1; } }
    }
    :where(button, input, textarea, select):focus-visible { outline: 2px solid #1F564A; outline-offset: 1px; }
    .who { flex: 1; min-width: 0; }
    .who .nm { font-weight: 650; font-size: 16.5px; line-height: 1.25; }
    .who .sub { color: #616161; font-size: 12.5px; margin-top: 3px; line-height: 1.45; }
    .pill { display: inline-block; margin-top: 5px; margin-right: 4px; font-size: 10px; padding: 1px 7px;
      border: 1px solid #cccccc; color: #616161;   }
    .pill.play { background: #e7efeb; border-color: #cfe0d8; color: #1F564A; }
    .box { margin-top: 14px; padding: 12px 14px; background: #f7f7f7; border: 1px solid #e3e3e3; }
    .box.basket { background: #edf3f0; border-color: #cfe0d8; }
    .box .k { font-size: 10px; color: #616161;   }
    .box .v { font-size: 19px; font-weight: 650; margin-top: 2px; }
    .lbl { font-size: 11px;   color: #616161; margin: 16px 0 7px; }
    .reasons { list-style: none; margin: 0; padding: 0; }
    .reasons li { padding: 5px 0 5px 15px; position: relative; line-height: 1.5; font-size: 13px; }
    .reasons li:before { content: "·"; position: absolute; left: 3px; color: #1F564A; font-weight: 700; }
    .reco { line-height: 1.4; color: #303030; font-size: 12.5px; }
    .acts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    .btn { border: 1px solid #cccccc; background: #fff; color: #303030; padding: 8px 13px; cursor: pointer;
      font-size: 12.5px; text-decoration: none; display: inline-block; transition: background .15s ease, transform .06s ease; }
    .btn:hover { background: #f7f7f7; }
    .btn:active { transform: translateY(1px); }
    .btn.primary { background: #303030; color: #ffffff; border-color: #303030; }
    .btn.primary:hover { background: #333; }
    .mini { border: 1px solid #cccccc; background: #fff; color: #303030; cursor: pointer; font-size: 12px;
      padding: 1px 7px; line-height: 1.5; }
    .mini:hover { background: #f7f7f7; }
    input.psearch { flex: 1; padding: 7px 9px; border: 1px solid #cccccc; background: #fff; font-size: 12.5px;
      font-family: inherit; color: #303030; }
    .tot { margin-top: 7px; font-weight: 600; font-size: 13px; }
    .pth { width: 38px; height: 38px; object-fit: cover; border: 1px solid #e3e3e3; flex: none;
      background: #f7f7f7; }
    /* Media panel: a photo grid for sending product imagery into the chat */
    .mgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .mcard { border: 1px solid #e3e3e3; background: #fff; padding: 6px; display: flex; flex-direction: column; }
    .mimg { width: 100%; height: 122px; object-fit: cover; background: #f7f7f7; display: block; }
    .mtt { font-size: 11.5px; color: #303030; margin: 6px 0; line-height: 1.3; max-height: 2.6em; overflow: hidden; }
    .macts { display: flex; gap: 5px; flex-wrap: wrap; margin-top: auto; }
    .macts .btn { font-size: 11px; padding: 4px 8px; }
    .tlist { border: 1px solid #e3e3e3; max-height: clamp(240px, 44vh, 560px); overflow-y: auto; margin-bottom: 10px; background: #fff; }
    .tcat { font-size: 10.5px;   color: #8a8a8a;
      padding: 10px 11px 4px; background: #f7f7f7; position: sticky; top: 0; }
    .titem { display: block; width: 100%; text-align: left; border: 0; background: transparent;
      padding: 9px 11px; font-size: 13px; color: #303030; cursor: pointer; }
    .titem:hover { background: #f7f7f7; }
    .titem.sel { background: #f7f7f7; font-weight: 600; }
    select { width: 100%; padding: 6px; border: 1px solid #cccccc; background: #fff; font-size: 12px; }
    textarea { width: 100%; padding: 7px 9px; border: 1px solid #cccccc; background: #fff; font-size: 12.5px;
      font-family: inherit; resize: vertical; color: #303030; }
    .prev { margin-top: 6px; padding: 8px; background: #f7f7f7; border: 1px solid #e3e3e3; font-size: 12px;
      line-height: 1.4; white-space: pre-wrap; max-height: 116px; overflow-y: auto; }
    .dbox { border: 1px solid #e3e3e3; background: #f7f7f7; padding: 14px; margin-bottom: 14px; }
    .dbox .sh { margin: 0 0 7px; }
    textarea.dinstr { width: 100%; box-sizing: border-box; border: 1px solid #cccccc; background: #fff;
      font: inherit; font-size: 12.5px; padding: 7px 9px; resize: vertical; min-height: 32px; color: #303030; }
    .dsrc { font-size: 10.5px;   color: #8a8a8a; margin-top: 6px; }
    .urg { background: #e3e3e3; color: #616161; font-size: 10px; padding: 1px 6px; letter-spacing: 0;
      text-transform: none; margin-left: 6px; }
    .bsum { margin-top: 9px; font-size: 12.5px; line-height: 1.5; color: #303030; }
    .blist { margin-top: 9px; display: flex; flex-direction: column; gap: 5px; }
    .bact { display: block; width: 100%; text-align: left; font: inherit; padding: 7px 9px;
      border: 1px solid #e3e3e3; background: #fff; cursor: pointer; }
    .bact:hover { background: #f7f7f7; border-color: #cccccc; }
    .bact.note { cursor: default; background: transparent; border-style: dashed; }
    .bact b { display: block; font-size: 12.5px; font-weight: 600; color: #303030; }
    .bact i { display: block; font-style: normal; font-size: 11.5px; color: #616161; margin-top: 1px; }
    .row { padding: 8px 10px; border: 1px solid #e3e3e3; background: #fff; margin-bottom: 7px; }
    .row .rn { font-weight: 600; font-size: 13px; }
    .row .rd { font-size: 11.5px; color: #616161; margin-top: 1px; }
    .row .live { color: #3f7a4f; font-weight: 600; }
    .muted { color: #616161; line-height: 1.45; font-size: 12.5px; }
    .warn { margin-top: 12px; padding: 10px 13px; background: #f9efec; border: 1px solid #e3c9c0;
      color: #8e3b2b; font-size: 12px; line-height: 1.35; }
    .warn b { color: #6d2c1f; }
    .link { color: #1F564A; text-decoration: underline; cursor: pointer; font-size: 12px; }
    .foot { flex: none; padding: 12px 18px; border-top: 1px solid #e3e3e3; font-size: 11px; color: #8a8a8a;
      display: flex; align-items: center; gap: 6px; }
    .toast { position: fixed; right: 376px; bottom: 22px; background: #303030; color: #fff; font-size: 11px;
      padding: 5px 10px; opacity: 0; transition: opacity .15s; pointer-events: none; z-index: 2147483647; }
    .toast.on { opacity: 1; }
    /* reverse share: the page you are on, sent to a client you pick */
    .shpage { padding: 9px 10px; background: #f7f7f7; border: 1px solid #e3e3e3; margin-bottom: 11px; }
    .shpage .k { font-size: 10px;   color: #8a8a8a; }
    .shpage .t { font-size: 13px; font-weight: 600; margin-top: 2px; line-height: 1.3; word-break: break-word; }
    .ochips { display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0 4px; }
    .ochip { border: 1px solid #cccccc; background: #fff; color: #303030; cursor: pointer; font-size: 11px;
      padding: 4px 9px; line-height: 1.3; }
    .ochip:hover { background: #f7f7f7; }
    .ochip.on { background: #1F564A; color: #ffffff; border-color: #1F564A; }
    .clist { border: 1px solid #e3e3e3; max-height: clamp(220px, 38vh, 480px); overflow-y: auto; background: #fff; margin-top: 10px; }
    .cli { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; border: 0;
      background: transparent; border-bottom: 1px solid #ececec; padding: 10px 12px; cursor: pointer; }
    .cli:last-child { border-bottom: 0; }
    .cli:hover { background: #f7f7f7; }
    .cli.sel { background: #f7f7f7; }
    .cg { flex: none; min-width: 22px; height: 20px; padding: 0 5px; display: flex; align-items: center;
      justify-content: center; font-weight: 700; font-size: 10px; color: #fff; background: #616161; border-radius: 3px; }
    .cg.g-a { background: #1F564A; } .cg.g-b { background: #55606b; } .cg.g-c { background: #8a8a8a; }
    .cli .cn { flex: 1; min-width: 0; font-size: 12.5px; color: #303030; white-space: nowrap; overflow: hidden;
      text-overflow: ellipsis; }
    .cli .cx { flex: none; font-size: 10.5px; color: #8a8a8a; }
    .chosen { display: flex; align-items: center; gap: 9px; padding: 8px 10px; background: #eef3f0;
      border: 1px solid #cfe0d8; margin-top: 8px; }
    .chosen .cn { flex: 1; font-size: 13px; font-weight: 600; color: #303030; }
    .chosen .clr { border: 0; background: transparent; color: #616161; cursor: pointer; font-size: 15px; padding: 0 2px; }
    .tgl { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #303030; cursor: pointer;
      margin-top: 9px; user-select: none; }
    .tgl input { width: 15px; height: 15px; }

    /* radius harmonisation with the dashboard: 8px controls, 12px cards */
    .btn, .mini, .chip, .modebtn, .ochip, .who, input.psearch, select, textarea, .pill,
    .grade, .cg, .hg, .urg, .lnkbtn, .titem { border-radius: 8px; }
    .todo, .box, .dbox, .shpage, .tlist, .clist, .mcard, .prev, .warn, .chosen, .row,
    .toast, .bact { border-radius: 12px; }
    .tlist, .clist { overflow: hidden; }
  `;

  let host = null, root = null, open = true, inserter = null, channel = "email";
  let ctx = null, client = null; // ctx = standing context; client = active client state
  let cart = [], prodResults = [], cartBase = ""; // the working cart + last product search
  let mode = "clienteling"; // "clienteling" (client-facing) | "internal" (team coordination)
  let view = "client";      // clienteling crossbar tab: "client" | "reply" | "sell"
  let whyAll = false, noteOpen = false;   // per-client: expand the reasons list / reveal the note box
  const VIEW_SECS = { share: ["share"], client: ["client"], reply: ["tpl"], sell: ["camp", "prod", "media", "cat"] };
  let mediaResults = [], mediaQuery = "";   // the Media panel's own product search (send product photos)
  let tplQuery = "", tplSel = null;   // template search text + selected index
  let tplGreeting = true, tplSignoff = true;   // include the salutation / the closing when inserting
  let tplRecent = [];   // the associate's last-used template names (chrome.storage.sync)
  let threadReader = null;            // surface-supplied () => [{from,text}] of the visible chat
  let draftInstr = "";                // the associate's optional "what to say" note
  let draft = null;                   // { text, source, busy, error, aiAvailable }
  let draftStart = 0, draftClock = null; // brief-in-progress timer (pixel-grid loader elapsed)
  let suggest = null;                 // { picks:[{...,on}], busy, error, empty }
  let suggestNote = "";               // optional steer for what the associate is looking for
  let animKey = "";                   // last client key animated (so we fade in only on a new client)
  const folded = new Set();           // collapsed section names, persisted
  const contactHist = {};   // cid -> last outreach {at,by,action,note} | null | "pending"
  // Reverse share (storefront surface): the page being shared, the client picked for it, and the
  // draft. Mirrors the iOS HaliaShare card — a page kind picks the openers, a client picks the number.
  let share = null;                   // { url, title, kind } | null (null everywhere but the storefront)
  let shareClient = null;             // the chosen client {cid,name,grade,phone}
  let shareOpener = 0;                // index into the current kind's openers
  let shareGreeting = true;           // prepend "Dear <first>,"
  let shareDraft = null;              // the editable message; null until built from opener + link
  let clientResults = null;           // last client search: [] | null (not searched) | "busy" | "err"
  let clientQuery = "";
  let sharePinned = false;            // have we landed the panel on the Share view yet

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function money(v) { return "£" + Number(v || 0).toLocaleString(); }
  // Greeting / sign-off toggles: strip the salutation or the closing from a template when the
  // associate is already mid-conversation. Shared with the on-any-page composer via the same keys.
  const GREET_RE = /^(dear|dearest|hi|hello|hey|good\s+(morning|afternoon|evening)|greetings)\b/i;
  const SIGN_LINE = /^(warm(est)?\s+(regards|wishes)|kind(est)?\s+regards|best(\s+(regards|wishes))?|very\s+best|all\s+the\s+best|with\s+(love|thanks|gratitude|appreciation|warm\s+wishes|warmth)|many\s+thanks|thank\s+you|thanks|yours(\s+(sincerely|truly|faithfully))?|sincerely|warmly|speak\s+soon|see\s+you\s+soon|regards|cheers|love|xx)[.,!]*(\s+[A-Z][\w'’.-]*(\s+[A-Z][\w'’.-]*)?)?$/i;
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
  function withToggles(text) {
    let t = String(text || "");
    if (!tplGreeting) t = stripGreeting(t);
    if (!tplSignoff) t = stripSignoff(t);
    return t;
  }
  // Ease a number up from 0 to its value on a fresh client — a small "alive" flourish. Preserves a
  // leading £ and re-formats with thousands separators; leaves non-numeric values (e.g. "High") alone.
  function countUp(el) {
    try { if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return; } catch (e) { /* ignore */ }
    const raw = (el.textContent || "").trim();
    const cur = raw[0] === "£";
    const target = parseFloat(raw.replace(/[^0-9.]/g, ""));
    if (!isFinite(target) || target <= 0) return;
    const fmt = (v) => (cur ? "£" : "") + Math.round(v).toLocaleString("en-GB");
    const dur = 700, t0 = (typeof performance !== "undefined" ? performance.now() : Date.now());
    (function step(now) {
      const p = Math.min(1, ((now || Date.now()) - t0) / dur);
      el.textContent = fmt(target * (1 - Math.pow(1 - p, 3)));   // easeOutCubic
      if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(target);
    })(t0);
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
  // Load a thumbnail via the background (returns a data: URL) so it renders even where the host
  // page's CSP blocks a direct cross-origin <img src>. `w` requests a smaller Shopify render.
  function loadThumb(imgEl, url, w) {
    if (!imgEl || !url) return;
    try {
      chrome.runtime.sendMessage({ type: "halia:image", url, w: w || 0 }, (r) => {
        if (chrome.runtime.lastError || !r || !r.dataUrl) { imgEl.style.display = "none"; return; }
        imgEl.src = r.dataUrl;
      });
    } catch (e) { imgEl.style.display = "none"; }
  }
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

  // ── Reverse share openers ──────────────────────────────────────────────────
  // One heading + a set of openers per page kind, so the note fits what the associate is sharing.
  // The same sets ship on iOS; the manager can override any set from the dashboard (ctx.openers),
  // and each kind falls back to these defaults. The link follows the chosen opener.
  const SHARE_KIND = {
    product:    { title: "Product",              action: "Send this piece" },
    collection: { title: "Collection",           action: "Send this edit" },
    care:       { title: "Care",                 action: "Send this to a client" },
    returns:    { title: "Returns",              action: "Send this to a client" },
    size:       { title: "Size guide",           action: "Send this to a client" },
    about:      { title: "About the house",      action: "Send this to a client" },
    contact:    { title: "Visit and appointments", action: "Invite a client" },
    press:      { title: "A link",               action: "Send this to a client" }
  };
  // {title} is the page's own name (the product title on a product page); when the page offers no
  // usable title, {title} falls back to "this" and the sentence is re-capitalised.
  const SHARE_OPENERS = {
    product: [
      { label: "Set aside",        body: "I have set {title} aside for you, if you would like it." },
      { label: "Just in",          body: "{title} just arrived and I thought of you straight away." },
      { label: "Your taste",       body: "{title} reminded me of your taste the moment it came in." },
      { label: "What do you think", body: "I would love to know what you think of {title}." },
      { label: "Limited",          body: "We are down to the last few of {title}, and I wanted you to have first look." },
      { label: "First look",       body: "An early look at {title} for you, before it goes out more widely." },
      { label: "Back in stock",    body: "Good news, {title} is back. I can hold one for you." }
    ],
    collection: [
      { label: "An edit for you",  body: "I put together a few pieces I thought you would love." },
      { label: "New season",       body: "The new season is in. Here is a first look, chosen with you in mind." }
    ],
    care: [
      { label: "Care guide",       body: "Here is how to care for your piece, so it lasts beautifully." }
    ],
    returns: [
      { label: "Returns",          body: "Here is everything on our returns and exchanges, in case it helps." },
      { label: "Happy to help",    body: "Of course. Here are the details, and I am here if you need anything." }
    ],
    size: [
      { label: "Size guide",       body: "Our size guide, so you find the perfect fit. Tell me if you would like me to check." }
    ],
    about: [
      { label: "About us",         body: "A little about the house, and how we like to look after you." }
    ],
    contact: [
      { label: "Come see us",      body: "Come and see us whenever suits. Here are the details." },
      { label: "Book a visit",     body: "I would love to set aside some time for you. Shall we arrange a private appointment?" }
    ],
    press: [
      { label: "Thought of you",   body: "Saw this and immediately thought of you." }
    ]
  };
  function shareKind() { return (share && SHARE_KIND[share.kind]) ? share.kind : "press"; }
  function shareOpeners() {
    const k = shareKind();
    const over = ctx && ctx.openers && Array.isArray(ctx.openers[k]) && ctx.openers[k].length ? ctx.openers[k] : null;
    return over || SHARE_OPENERS[k] || SHARE_OPENERS.press;
  }
  // The page's own name, if it reads well mid-sentence: real titles only, not slogans or whole
  // sentences. Anything empty or over-long falls back to "this".
  function shareTitle() {
    const t = ((share && share.title) || "").trim();
    return (t && t.length <= 60) ? t : "";
  }
  // Fill {title} in an opener (built-in or the merchant's own custom openers alike).
  function fillOpener(body) {
    const b = String(body || "");
    if (b.indexOf("{title}") < 0) return b;
    const t = shareTitle();
    let out = b.split("{title}").join(t || "this");
    if (!t) out = out.charAt(0).toUpperCase() + out.slice(1);   // "this just arrived…" → "This…"
    return out;
  }

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
        <div class="tabs" data-a="tabs">
          <button class="tab" data-v="share" style="display:none">Share</button>
          <button class="tab" data-v="client">Client</button>
          <button class="tab" data-v="reply">Reply</button>
          <button class="tab" data-v="sell">Sell</button>
        </div>
        <div class="scroll">
          <section class="sec" data-s="share"></section>
          <section class="sec" data-s="client"></section>
          <section class="sec" data-s="team"></section>
          <section class="sec" data-s="tpl"></section>
          <section class="sec" data-s="camp"></section>
          <section class="sec" data-s="prod"></section>
          <section class="sec" data-s="media"></section>
          <section class="sec" data-s="cat"></section>
        </div>
        <div class="foot" data-a="foot"><span class="m live" style="color:#1F564A">⁂</span></div>
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
    dock.querySelector('[data-a="tabs"]').addEventListener("click", (e) => {
      const b = e.target.closest(".tab"); if (b && b.dataset.v) setView(b.dataset.v);
    });
    renderShare(); renderTemplates(); renderCampaigns(); renderProducts(); renderMedia(); renderCatalogue();
    applyMode(); applyFolds(); paintHandle();
  }

  function setMode(m, persist) {
    mode = m === "internal" ? "internal" : "clienteling";
    if (persist !== false) { try { chrome.storage.local.set({ haliaMode: mode }); } catch (e) { /* ignore */ } }
    if (root) applyMode();
  }
  function setView(v) {
    view = (v in VIEW_SECS) ? v : "client";
    // "share" is a per-page surface, not a lasting preference — don't let it become the view other
    // surfaces (WhatsApp, Gmail) restore to, where there is nothing to share.
    if (view !== "share") { try { chrome.storage.local.set({ haliaView: view }); } catch (e) { /* ignore */ } }
    if (root) applyMode();
  }
  function applyMode() {
    const internal = mode === "internal";
    const show = (name, on) => { const el = sec(name); if (el) el.style.display = on ? "" : "none"; };
    const tabs = root && root.querySelector('[data-a="tabs"]');
    if (tabs) tabs.classList.toggle("hide", internal);   // the crossbar is a clienteling concept
    // The Share tab only exists on a page there is something to share (the storefront surface).
    const shareTab = tabs && tabs.querySelector('.tab[data-v="share"]');
    if (shareTab) shareTab.style.display = share ? "" : "none";
    if (internal) {
      // Internal mode is only two blocks (client + team brief) — no crossbar needed.
      show("client", true); show("team", true);
      ["share", "tpl", "camp", "prod", "media", "cat"].forEach((n) => show(n, false));
    } else {
      // Clienteling: show ONLY the active tab's section(s), so it reads as one calm view. If "share"
      // is the view but this page has nothing to share, fall back to the client view.
      show("team", false);
      const effView = (view === "share" && !share) ? "client" : view;
      const active = VIEW_SECS[effView] || VIEW_SECS.client;
      ["share", "client", "tpl", "camp", "prod", "media", "cat"].forEach((n) => {
        const on = active.indexOf(n) >= 0; show(n, on);
        if (on) { const s2 = sec(n); if (s2) { s2.classList.remove("vin"); void s2.offsetWidth; s2.classList.add("vin"); } }
      });
      if (tabs) tabs.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.v === effView));
    }
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

  // The engine's pulse: whenever any live work is in flight (reading a client, writing a brief,
  // suggesting products, searching the book) the bar's scanline sweeps and the mark quickens.
  function updateThinking() {
    const on = !!((client && client.loading) || (draft && draft.busy) || (suggest && suggest.busy)
      || clientResults === "busy");
    const dock = root && root.querySelector(".dock");
    if (dock) dock.classList.toggle("thinking", on);
  }

  // ── REVERSE SHARE ─────────────────────────────────────────────────────────
  // The page the associate is on, sent to a client they choose. Pick an opener that fits the page,
  // pick who from the book, and message them the link. Nothing is stored; the link is the page's own.
  function shareFirst() {
    const n = shareClient && shareClient.name;
    return n ? String(n).trim().split(/\s+/)[0] : "";
  }
  function shareLink() {
    if (!share || !share.url) return "";
    const camp = ((ctx && ctx.campaigns) || []).find((c) => c.running);   // attribute to a live campaign
    if (!camp) return share.url;
    const cm = CHAN[channel] || CHAN.email;
    return appendUtm(share.url, { source: cm[0], medium: cm[1], campaign: camp.utm });
  }
  function buildShareDraft() {
    const ops = shareOpeners();
    const op = ops[shareOpener] || ops[0];
    const first = shareFirst();
    const parts = [];
    if (shareGreeting && first) parts.push("Dear " + first + ",");
    if (op && op.body) parts.push(fillOpener(op.body));
    const link = shareLink();
    if (link) parts.push(link);
    shareDraft = parts.join("\n\n");
    const ta = root && root.querySelector('[data-a="shdraft"]');
    if (ta) ta.value = shareDraft;
  }
  function paintClientList() {
    updateThinking();
    const box = root && root.querySelector('[data-a="shclients"]'); if (!box) return;
    if (clientResults === "busy") { box.innerHTML = `<div class="muted" style="padding:8px 9px">Reading your book…</div>`; return; }
    if (clientResults === "err") { box.innerHTML = `<div class="muted" style="padding:8px 9px">Couldn't reach your book.</div>`; return; }
    if (!Array.isArray(clientResults)) { box.innerHTML = ""; return; }
    if (!clientResults.length) { box.innerHTML = `<div class="muted" style="padding:8px 9px">No one by that name in your book.</div>`; return; }
    box.innerHTML = clientResults.slice(0, 60).map((c, i) => `
      <button class="cli" data-ci="${i}">
        <span class="cg ${gradeClass(c.grade)}">${esc(c.grade || "·")}</span>
        <span class="cn">${esc(c.name)}</span>
        ${c.phone ? "" : `<span class="cx">no number</span>`}
      </button>`).join("");
    box.querySelectorAll("[data-ci]").forEach((b) => b.onclick = () => {
      const c = clientResults[+b.dataset.ci]; if (c) pickClient(c);
    });
  }
  function doClientSearch(q) {
    clientQuery = q; clientResults = "busy"; paintClientList();
    try {
      chrome.runtime.sendMessage({ type: "halia:clients", q }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) { clientResults = "err"; }
        else { clientResults = r.clients || []; }
        paintClientList();
      });
    } catch (e) { clientResults = "err"; paintClientList(); }
  }
  function pickClient(c) {
    shareClient = c;
    shareDraft = null;              // rebuilt fresh for the newly chosen client
    renderShare();
    buildShareDraft();
  }
  function currentShareText() {
    const ta = root && root.querySelector('[data-a="shdraft"]');
    return (ta && ta.value) || shareDraft || "";
  }
  function digits(s) { return String(s || "").replace(/[^\d]/g, ""); }
  function sendShareWhatsApp() {
    const text = currentShareText(); if (!text) { toast("Pick an opener first"); return; }
    const d = digits(shareClient && shareClient.phone);
    const url = d ? "https://wa.me/" + d + "?text=" + encodeURIComponent(text)
                  : "https://api.whatsapp.com/send?text=" + encodeURIComponent(text);
    try { window.open(url, "_blank", "noopener"); } catch (e) { copy(text, "Copied — paste into WhatsApp"); }
    logShareContact();
  }
  function logShareContact() {
    if (!shareClient) return;
    const kind = SHARE_KIND[shareKind()];
    act({ action: "contacted", cid: shareClient.cid || "", client_name: shareClient.name,
      reason: "Shared: " + (share && share.title ? share.title : (kind ? kind.title : "a page")) },
      "Logged" + (ctx && ctx.slack ? " and told the team" : ""));
  }
  function renderShare() {
    const el = sec("share"); if (!el) return;
    if (!share) { el.innerHTML = ""; return; }
    const meta = SHARE_KIND[shareKind()];
    const ops = shareOpeners();
    el.innerHTML = `
      <div class="sh">Send this to a client</div>
      <div class="shpage">
        <div class="k">${esc(meta.title)}</div>
        <div class="t">${esc(share.title || share.url)}</div>
      </div>
      <div class="lbl">${esc(meta.action)}</div>
      <div class="ochips">
        ${ops.map((o, i) => `<button class="ochip${i === shareOpener ? " on" : ""}" data-op="${i}">${esc(o.label)}</button>`).join("")}
      </div>
      ${shareClient ? `
        <div class="chosen">
          <span class="cg ${gradeClass(shareClient.grade)}">${esc(shareClient.grade || "·")}</span>
          <span class="cn">${esc(shareClient.name)}</span>
          <button class="clr" data-a="shclear" title="Choose someone else">✕</button>
        </div>
        <textarea data-a="shdraft" rows="6" style="margin-top:9px">${esc(shareDraft || "")}</textarea>
        <label class="tgl"><input type="checkbox" data-a="shgreet"${shareGreeting ? " checked" : ""}>
          Open with “Dear ${esc(shareFirst() || "name")},”</label>
        ${digits(shareClient.phone) ? "" : `<div class="muted" style="margin-top:8px">No number on file for them — copy the message and send it your way.</div>`}
        <div class="acts">
          <button class="btn primary" data-a="shwa">${digits(shareClient.phone) ? "Message on WhatsApp" : "Open WhatsApp"}</button>
          <button class="btn" data-a="shcopy">Copy message</button>
        </div>
        <button class="lnkbtn" data-a="shlog">Log as contacted</button>
      ` : `
        <div style="display:flex;gap:6px;margin-top:8px">
          <input class="psearch" data-a="shsearch" placeholder="Search your book" value="${esc(clientQuery)}">
          <button class="btn" data-a="shgo">Find</button>
        </div>
        <div class="clist" data-a="shclients"></div>
      `}`;
    el.querySelectorAll("[data-op]").forEach((b) => b.onclick = () => {
      shareOpener = +b.dataset.op;
      el.querySelectorAll(".ochip").forEach((c) => c.classList.toggle("on", c === b));
      buildShareDraft();
    });
    if (shareClient) {
      const clr = el.querySelector('[data-a="shclear"]');
      if (clr) clr.onclick = () => { shareClient = null; renderShare(); };
      const gr = el.querySelector('[data-a="shgreet"]');
      if (gr) gr.onchange = () => { shareGreeting = gr.checked; buildShareDraft(); };
      const wa = el.querySelector('[data-a="shwa"]'); if (wa) wa.onclick = sendShareWhatsApp;
      const cp = el.querySelector('[data-a="shcopy"]');
      if (cp) cp.onclick = () => { const t = currentShareText(); if (t) { copy(t, "Message copied"); logShareContact(); } };
      const lg = el.querySelector('[data-a="shlog"]'); if (lg) lg.onclick = logShareContact;
    } else {
      const inp = el.querySelector('[data-a="shsearch"]');
      const go = () => doClientSearch((inp && inp.value) || "");
      const gb = el.querySelector('[data-a="shgo"]'); if (gb) gb.onclick = go;
      if (inp) inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } };
      paintClientList();
      if (clientResults === null) doClientSearch("");   // show the best of the book straight away
    }
  }

  // The footer shows who is signed in (the seat) with a one-click sign out; otherwise just the mark.
  function renderFoot() {
    const el = root && root.querySelector('[data-a="foot"]'); if (!el) return;
    const mark = '<span class="m live" style="color:#1F564A">⁂</span> ';
    if (ctx && ctx.seat) {
      el.innerHTML = mark + "Signed in as " + esc(ctx.seat)
        + ' · <span data-a="signout" style="cursor:pointer;text-decoration:underline">Sign out</span>';
      const so = el.querySelector('[data-a="signout"]');
      if (so) so.onclick = () => chrome.runtime.sendMessage({ type: "halia:signout" }, () => {
        ctx = null; renderFoot();
        try { window.dispatchEvent(new CustomEvent("halia:refresh")); } catch (e) { /* ignore */ }
      });
    } else {
      el.innerHTML = mark.trim();
    }
  }

  function renderClient() {
    updateThinking();
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
    const allReasons = (d.reasons || []).slice(0, 6);
    const reasons = whyAll ? allReasons : allReasons.slice(0, 3);
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
      ${d.latent ? `<div class="box"><div class="k">Latent value</div><div class="v" data-a="latentv">${esc(d.latent)}</div></div>` : ""}
      ${cart ? `<div class="box basket"><div class="k">Open basket</div>
        <div class="v">${money(cart.value)}${cart.count ? ` <span style="font-weight:400;font-size:11px;color:#616161">${esc(cart.count)} item${cart.count === 1 ? "" : "s"}</span>` : ""}</div>
        ${cart.url ? `<a class="link" href="${esc(cart.url)}" target="_blank" rel="noopener">Open checkout</a>` : ""}</div>` : ""}
      ${d.action ? `<div class="lbl">Next move</div><div class="reco">${esc(d.action)}</div>` : ""}
      ${allReasons.length ? `<div class="lbl">Why</div><ul class="reasons">${reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>${allReasons.length > 3 && !whyAll ? `<button class="lnkbtn" data-a="whymore">＋${allReasons.length - 3} more</button>` : ""}` : ""}
      <div class="acts">${acts.join("")}</div>
      ${d.cid && ctx && ctx.platform === "shopify" ? (noteOpen ? `<div class="lbl">Note</div>
        <textarea data-a="note" rows="2" placeholder="Jot a note — saved to this customer in your Shopify"></textarea>
        <div class="acts"><button class="btn" data-a="notesave">Save note</button></div>`
        : `<button class="lnkbtn" data-a="noteopen">＋ Add note</button>`) : ""}`;
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
    const wm = el.querySelector('[data-a="whymore"]');
    if (wm) wm.onclick = () => { whyAll = true; renderClient(); };
    const no = el.querySelector('[data-a="noteopen"]');
    if (no) no.onclick = () => { noteOpen = true; renderClient(); };
    if (anim) { const lv = el.querySelector('[data-a="latentv"]'); if (lv) countUp(lv); }  // a new client → the number counts up
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
          <input data-a="lreason" placeholder="Reason (optional)" value="${esc(briefLogReason())}" style="flex:1;padding:7px 9px;border:1px solid #cccccc;font-size:12.5px;color:#303030;background:#fff">
          <button class="btn primary" data-a="logc">Log</button>
        </div>` : ""}
      ${activeCid() ? `<div class="lbl">Book a visit</div>
        <div style="display:flex;gap:6px;margin-bottom:6px">
          <input data-a="apwhen" type="datetime-local" style="padding:6px 8px;border:1px solid #cccccc;font-size:12.5px;color:#303030;background:#fff">
          <input data-a="applace" placeholder="Where (optional)" style="flex:1;padding:7px 9px;border:1px solid #cccccc;font-size:12.5px;color:#303030;background:#fff">
          <button class="btn primary" data-a="apbook">Book</button>
        </div>
        <div data-a="apdone" class="muted" style="display:none;margin-bottom:13px"></div>` : ""}
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
    const apb = el.querySelector('[data-a="apbook"]');
    if (apb) apb.onclick = () => {
      const w = el.querySelector('[data-a="apwhen"]'), pl = el.querySelector('[data-a="applace"]'), done = el.querySelector('[data-a="apdone"]');
      if (!w || !w.value) { toast("Pick a date and time"); return; }
      const body = { action: "appointment", cid: activeCid(), when: new Date(w.value).toISOString(), place: (pl && pl.value) || "", client_name: cname };
      try {
        chrome.runtime.sendMessage({ type: "halia:action", body }, (r) => {
          if (chrome.runtime.lastError || !r || r.error) { toast((r && r.detail) || "Couldn't book that"); return; }
          toast("Booked");
          if (done && r.links) {
            done.style.display = "";
            done.innerHTML = `Add to your calendar: <a href="${esc(r.links.google)}" target="_blank" rel="noopener">Google</a> · <a href="${esc(r.links.outlook)}" target="_blank" rel="noopener">Outlook</a> · <a href="${esc(r.links.ics_data)}" download="appointment.ics">Apple / .ics</a>
              <div style="margin-top:6px"><button class="mini" data-a="apsend">${inserter ? "Send to client" : "Copy for the client"}</button></div>`;
            const sb = done.querySelector('[data-a="apsend"]');
            if (sb) sb.onclick = () => { if (inserter) place(r.links.message); else copy(r.links.message, "Copied"); };
          }
          if (w) w.value = ""; if (pl) pl.value = "";
        });
      } catch (e) { toast("Couldn't book that"); }
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
    draftStart = Date.now();
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
  // What to write in the shared contact log. The brief already knows what the associate is about
  // to send, so the log can say what was actually said rather than "Sent a note" — which is what a
  // colleague reading the pipeline next week actually needs. Costs nothing: no extra call.
  const _CHAN_LABEL = { whatsapp: "WhatsApp", email: "Email", admin: "Store" };
  function briefLogReason() {
    const text = (draft && draft.text) || "";
    if (!text) return "";
    const first = text.replace(/\s+/g, " ").trim().split(/(?<=[.!?])\s/)[0] || text;
    const gist = first.length > 90 ? first.slice(0, 87).trimEnd() + "…" : first;
    const via = _CHAN_LABEL[channel] || "";
    return (via ? `Replied on ${via}: ` : "Replied: ") + gist;
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
      ${busy ? `<div class="loadrow"><span class="pxgrid" aria-hidden="true">${[90,180,270,0,90,180,90,180,270].map((ms) => `<i style="animation-delay:${ms}ms"></i>`).join("")}</span><span class="shimtx">${threadReader ? "Reading this conversation" : "Reading this client"}</span><span class="elapsed" data-a="dclock">0.0s</span></div>` : ""}
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
          ${activeCid() ? `<button class="btn" data-a="dlog" title="${esc(briefLogReason())}">Log it</button>` : ""}
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
    const dl = el.querySelector('[data-a="dlog"]');
    if (dl) dl.onclick = () => logContact(activeCid(), activeName(), briefLogReason());
    // Live elapsed timer for the pixel-grid loader; self-clears when the brief resolves and the node goes away.
    if (draftClock) { clearInterval(draftClock); draftClock = null; }
    if (el.querySelector('[data-a="dclock"]')) {
      draftClock = setInterval(() => {
        const cur = el.querySelector('[data-a="dclock"]');
        if (!cur) { clearInterval(draftClock); draftClock = null; return; }
        const s = (Date.now() - draftStart) / 1000;
        cur.textContent = s < 60 ? s.toFixed(1) + "s" : Math.floor(s / 60) + "m " + (s % 60).toFixed(1) + "s";
      }, 100);
    }
  }

  function renderTemplates() {
    updateThinking();
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
    // With no search: the right ones first. "For this client" is the server's ranking for the
    // client on screen (birthday soon, open basket, gone quiet, first order, a live moment);
    // "Recent" is what this associate reaches for. Nobody scrolls forty templates.
    if (!q) {
      const byName = (names) => (names || []).map((n) => list.findIndex((t) => (t.name || "") === n))
        .filter((i) => i >= 0).map((i) => ({ t: list[i], i }));
      const sugg = byName((client && client.data && client.data.suggested) || (ctx && ctx.suggested) || []);
      const rec = byName(tplRecent).filter(({ i }) => !sugg.some((x) => x.i === i)).slice(0, 4);
      if (rec.length) groups.unshift({ cat: "Recent", items: rec });
      if (sugg.length) groups.unshift({ cat: client && client.data && client.data.found ? "For this client" : "Start here", items: sugg });
    }
    const sel = (tplSel != null && list[tplSel]) ? list[tplSel] : null;
    el.innerHTML = draftBoxHtml() + `
      <div class="sh">Templates <span class="n">${list.length}</span></div>
      <input class="psearch" data-a="tsearch" placeholder="Search templates" value="${esc(tplQuery)}" style="margin-bottom:8px">
      <div class="tlist">${groups.length
        ? groups.map((g) => `<div class="tcat">${esc(g.cat)}</div>` +
            g.items.map(({ t, i }) => `<button class="titem${i === tplSel ? " sel" : ""}" data-ti="${i}">${esc(t.name || ("Template " + (i + 1)))}</button>`).join("")).join("")
        : `<div class="muted" style="padding:10px">No templates match.</div>`}</div>
      <div style="display:flex;gap:16px;margin-top:2px">
        <label class="tgl"><input type="checkbox" data-a="tg"${tplGreeting ? " checked" : ""}>Greeting</label>
        <label class="tgl"><input type="checkbox" data-a="tso"${tplSignoff ? " checked" : ""}>Sign-off</label>
      </div>
      ${sel ? `<div class="prev">${esc(withToggles(fill(sel.body)))}</div>
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
    const saveTog = () => { try { chrome.storage.sync.set({ tplGreeting, tplSignoff }); } catch (e) { /* ignore */ } };
    const tg = el.querySelector('[data-a="tg"]'); if (tg) tg.onchange = () => { tplGreeting = tg.checked; saveTog(); renderTemplates(); };
    const tso = el.querySelector('[data-a="tso"]'); if (tso) tso.onchange = () => { tplSignoff = tso.checked; saveTog(); renderTemplates(); };
    const body = () => withToggles(fill((list[tplSel] || {}).body));
    const used = () => { const t = list[tplSel]; if (!t) return;
      tplRecent = [t.name].concat(tplRecent.filter((n) => n !== t.name)).slice(0, 6);
      try { chrome.storage.sync.set({ tplRecent }); } catch (e) { /* ignore */ } };
    const ins = el.querySelector('[data-a="tins"]'); if (ins) ins.onclick = () => { used(); place(body()); };
    const cp = el.querySelector('[data-a="tcopy"]'); if (cp) cp.onclick = () => { used(); copy(body(), "Message copied"); };
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
  function addToCart(v, ptitle, pid) {
    const ex = cart.find((i) => i.id === v.id);
    if (ex) ex.qty += 1;
    else cart.push({ id: v.id, qty: 1, price: v.price, product_id: pid || null,
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
        ${p.image ? `<img class="pth" data-pi="${pi}" alt="">` : ""}
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
    prodResults.forEach((p, pi) => {
      loadThumb(box.querySelector(`img.pth[data-pi="${pi}"]`), p.image, 120);
      const b = box.querySelector(`[data-padd="${pi}"]`);
      if (b) b.onclick = () => {
        const sel = box.querySelector(`[data-pv="${pi}"]`);
        const v = (p.variants || [])[sel ? +sel.value : 0];
        if (v) addToCart(v, p.title, p.id);
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
         ${inserter && cart.some((i) => i.id) ? `<button class="btn primary" data-a="csend">Send cart</button>` : ""}
         <button class="btn" data-a="ccat">Send catalogue</button>
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
    const cc = box.querySelector('[data-a="ccat"]'); if (cc) cc.onclick = sendCatalogue;
  }
  // The other ending: the same selection presented as a small catalogue on the merchant's own
  // domain, addressed to this client. The link carries the products; nothing is saved anywhere.
  function sendCatalogue() {
    const ids = cart.map((i) => i.product_id).filter(Boolean);
    if (!ids.length) { toast("Add something from Suggested first"); return; }
    try {
      chrome.runtime.sendMessage({ type: "halia:catalogue",
        body: { product_ids: ids, name: activeName() } }, (r) => {
        if (chrome.runtime.lastError || !r || r.error || !r.url) { toast("Couldn't build that"); return; }
        const camp = ((ctx && ctx.campaigns) || []).find((c) => c.running);
        const cm = CHAN[channel] || CHAN.email;
        const url = camp ? appendUtm(r.url, { source: cm[0], medium: cm[1], campaign: camp.utm }) : r.url;
        if (inserter) { place(url); } else { copy(url, "Catalogue link copied"); }
      });
    } catch (e) { toast("Couldn't build that"); }
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
  // ── SUGGESTIONS ───────────────────────────────────────────────────────────
  // Halia proposes a handful of pieces for the client on screen, each with a reason the associate
  // could say out loud. Pre-ticked but never sent unreviewed: ticking only fills the same cart the
  // manual search fills, so every existing control still applies.
  function runSuggest() {
    const d = (client && client.data) || {};
    suggest = { busy: true, picks: (suggest && suggest.picks) || [], error: "" };
    renderProducts();
    const body = { cid: d.cid || "", email: d.email || "", phone: d.phone || "", name: d.name || "",
      instruction: suggestNote, thread: collectThread() };
    try {
      chrome.runtime.sendMessage({ type: "halia:suggest", body }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) {
          suggest = { busy: false, picks: [], error: draftErr(r) };
        } else {
          const picks = (r.picks || []).map((p) => Object.assign({ on: true }, p));
          suggest = { busy: false, picks, error: "",
            empty: !picks.length, aiAvailable: r.ai_available };
        }
        renderProducts();
      });
    } catch (e) { suggest = { busy: false, picks: [], error: "Couldn't suggest" }; renderProducts(); }
  }
  function suggestIntoCart() {
    const on = ((suggest && suggest.picks) || []).filter((p) => p.on);
    if (!on.length) { toast("Tick something first"); return; }
    on.forEach((p) => {
      if (p.variant_id && !cart.find((i) => i.id === p.variant_id)) {
        cart.push({ id: p.variant_id, qty: 1, price: p.price, label: p.title, product_id: p.product_id });
      } else if (!p.variant_id && !cart.find((i) => i.product_id === p.product_id)) {
        // no buyable variant: still send-able as a catalogue, just not as a cart line
        cart.push({ id: null, qty: 1, price: p.price, label: p.title, product_id: p.product_id });
      }
    });
    paintCart(); toast(on.length + " added");
  }
  function suggestHtml() {
    const s = suggest || {};
    const who = activeFirst();
    const label = s.busy ? "Looking…" : (s.picks && s.picks.length ? "Suggest again"
      : (who && who !== "there" ? "Suggest for " + esc(who) : "Suggest for this client"));
    return `<div class="dbox" style="margin-bottom:10px">
      <div class="sh">Suggested</div>
      <div class="acts" style="margin-top:0">
        <button class="btn primary" data-a="sgo"${s.busy ? " disabled" : ""}>${label}</button>
      </div>
      ${s.error ? `<div class="muted" style="margin-top:7px">${esc(s.error)}</div>` : ""}
      ${s.empty ? `<div class="muted" style="margin-top:7px">Nothing in the range stood out for them. Search below.</div>` : ""}
      ${(s.picks || []).length ? `<div class="blist" style="margin-top:9px">${s.picks.map((p, i) => `
        <label class="bact" style="display:flex;gap:8px;align-items:flex-start;cursor:pointer">
          <input type="checkbox" data-sp="${i}"${p.on ? " checked" : ""} style="margin-top:3px">
          <span style="flex:1;min-width:0"><b>${esc(p.title)}${p.price ? " · " + esc(p.currency || "") + esc(p.price) : ""}</b>
          <i>${esc(p.why || "")}</i></span></label>`).join("")}</div>
        <div class="acts"><button class="btn" data-a="sadd">Add ticked to cart</button></div>` : ""}
    </div>`;
  }

  function renderProducts() {
    updateThinking();
    const el = sec("prod"); if (!el) return;
    if (!ctx || ctx.platform !== "shopify") { el.innerHTML = ""; return; }  // cart permalinks are Shopify
    el.innerHTML = `<div class="sh">Build a cart</div>
      ${activeCid() ? suggestHtml() : ""}
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
    const sgo = el.querySelector('[data-a="sgo"]'); if (sgo) sgo.onclick = runSuggest;
    const sadd = el.querySelector('[data-a="sadd"]'); if (sadd) sadd.onclick = suggestIntoCart;
    el.querySelectorAll("[data-sp]").forEach((b) => b.onchange = () => {
      const p = ((suggest && suggest.picks) || [])[+b.dataset.sp]; if (p) p.on = b.checked;
    });
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

  // ── MEDIA ─────────────────────────────────────────────────────────────────
  // Search products and send their PHOTO into the chat: "Send image" copies the picture to the
  // clipboard so the associate pastes it straight into WhatsApp / Gmail (both accept a pasted image).
  function renderMedia() {
    const el = sec("media"); if (!el) return;
    if (!ctx || ctx.platform !== "shopify") { el.innerHTML = ""; return; }   // product photos come from Shopify
    el.innerHTML = `<div class="sh">Media</div>
      <div class="muted" style="margin:-3px 0 8px">Find a product and send its photo into the chat.</div>
      <div style="display:flex;gap:6px">
        <input class="psearch" data-a="msearch" placeholder="Search products" value="${esc(mediaQuery)}">
        <button class="btn" data-a="mgo">Search</button>
      </div>
      <div data-a="mresults" style="margin-top:8px"></div>`;
    const inp = el.querySelector('[data-a="msearch"]');
    const go = () => doMediaSearch((inp && inp.value) || "");
    el.querySelector('[data-a="mgo"]').onclick = go;
    if (inp) inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } };
    paintMedia();
  }
  function doMediaSearch(q) {
    mediaQuery = q;
    const box = root && root.querySelector('[data-a="mresults"]');
    if (box) box.innerHTML = `<div class="muted">Searching…</div>`;
    try {
      chrome.runtime.sendMessage({ type: "halia:products", q }, (r) => {
        if (chrome.runtime.lastError || !r || r.error) {
          mediaResults = [];
          if (box) box.innerHTML = `<div class="muted">Couldn't load products.</div>`;
          return;
        }
        mediaResults = (r.products || []).filter((p) => p.image);   // media = products that HAVE a photo
        if (!mediaResults.length && box) box.innerHTML = `<div class="muted">No product photos found.</div>`;
        else paintMedia();
      });
    } catch (e) { /* ignore */ }
  }
  function paintMedia() {
    const box = root && root.querySelector('[data-a="mresults"]'); if (!box) return;
    if (!mediaResults.length) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="mgrid">` + mediaResults.slice(0, 12).map((p, i) => {
      const price = (p.variants && p.variants[0] && p.variants[0].price) ? " · £" + esc(p.variants[0].price) : "";
      return `<div class="mcard">
        <img class="mimg" data-mi="${i}" alt="">
        <div class="mtt">${esc(p.title)}${price}</div>
        <div class="macts">
          <button class="btn primary" data-mcopy="${i}">Send image</button>
          ${inserter ? `<button class="btn" data-mlink="${i}">Insert link</button>`
            : `<button class="btn" data-mlinkc="${i}">Copy link</button>`}
        </div></div>`;
    }).join("") + `</div>`;
    mediaResults.forEach((p, i) => {
      loadThumb(box.querySelector(`img.mimg[data-mi="${i}"]`), p.image, 300);
      const cp = box.querySelector(`[data-mcopy="${i}"]`); if (cp) cp.onclick = () => copyImage(p.image);
      const lk = box.querySelector(`[data-mlink="${i}"]`); if (lk) lk.onclick = () => place(p.image);
      const lc = box.querySelector(`[data-mlinkc="${i}"]`); if (lc) lc.onclick = () => copy(p.image, "Image link copied");
    });
  }
  // Put the product photo on the clipboard as a PNG so it can be pasted into the chat. Draws through a
  // canvas (Shopify's CDN sends CORS headers, so it isn't tainted); falls back to copying the URL.
  function copyImage(url) {
    if (!url) return;
    try {
      chrome.runtime.sendMessage({ type: "halia:image", url }, (r) => {
        const dataUrl = r && r.dataUrl;
        if (chrome.runtime.lastError || !dataUrl) { copy(url, "Image link copied"); return; }
        const img = new Image();   // a data: URL isn't page-CSP-blocked and keeps the canvas untainted
        img.onload = () => {
          try {
            const c = document.createElement("canvas");
            c.width = img.naturalWidth || 800; c.height = img.naturalHeight || 800;
            c.getContext("2d").drawImage(img, 0, 0);
            c.toBlob((blob) => {
              if (!blob || !navigator.clipboard || !window.ClipboardItem) { copy(url, "Image link copied"); return; }
              navigator.clipboard.write([new ClipboardItem({ "image/png": blob })])
                .then(() => toast("Image copied — paste to send"))
                .catch(() => copy(url, "Image link copied"));
            }, "image/png");
          } catch (e) { copy(url, "Image link copied"); }
        };
        img.onerror = () => copy(url, "Image link copied");
        img.src = dataUrl;
      });
    } catch (e) { copy(url, "Image link copied"); }
  }

  const API = {
    mount() {
      ensure();
      try {
        chrome.storage.local.get(["panelOpen", "haliaMode", "haliaView", "folded"], (r) => {
          if (r && typeof r.panelOpen === "boolean") setOpen(r.panelOpen);
          if (r && r.haliaMode) setMode(r.haliaMode);
          if (r && r.haliaView && !sharePinned) setView(r.haliaView);   // don't knock a storefront off Share
          if (r && Array.isArray(r.folded)) { r.folded.forEach((n) => folded.add(n)); applyFolds(); }
        });
        chrome.storage.sync.get(["tplGreeting", "tplSignoff", "tplRecent"], (r) => {
          if (Array.isArray(r.tplRecent)) tplRecent = r.tplRecent;
          if (r && typeof r.tplGreeting === "boolean") tplGreeting = r.tplGreeting;
          if (r && typeof r.tplSignoff === "boolean") tplSignoff = r.tplSignoff;
          if (root) renderTemplates();
        });
      } catch (e) { /* ignore */ }
    },
    setContext(c) {
      ctx = c && !c.error ? c : null;
      if (root) { renderShare(); renderTemplates(); renderCampaigns(); renderProducts(); renderMedia(); renderCatalogue(); renderTeam(); renderFoot(); }
    },
    // The storefront surface hands the toolbar the page to share (url + title + kind). The Share tab
    // appears and, the first time, becomes the active view. Passing null clears it.
    setShare(info) {
      const prevKind = share && share.kind;
      share = (info && info.url) ? { url: info.url, title: info.title || "", kind: info.kind || "press" } : null;
      if (share && share.kind !== prevKind) { shareOpener = 0; shareDraft = null; }
      if (!root) return;
      if (share && !sharePinned) { sharePinned = true; setView("share"); }   // land on Share once
      renderShare();
      if (share && shareClient) buildShareDraft();
      applyMode();
    },
    setClient(state) {
      client = state; // null | {loading,name} | {found,data} | {notfound,name} | {error}
      if (state && state.found) client = { data: state.data };
      // A fresh client means a fresh draft and a fresh shortlist; never carry either over.
      draft = null; draftInstr = "";
      suggest = null; suggestNote = "";
      whyAll = false; noteOpen = false;   // reset the card's expanders for the new client
      // renderProducts too: the Suggest block is addressed to whoever is on screen, so it has to
      // be rebuilt when they change, not just when the standing context reloads.
      if (root) { renderClient(); renderTemplates(); renderCampaigns(); renderProducts();
        renderTeam(); paintHandle(); }
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
