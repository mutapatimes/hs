// Drive the toolbar (extension/ui/badge.js) through every view in jsdom with canned replies from
// the background worker, and report anything that throws plus a set of checks on what rendered.
// Prints one JSON line and exits 0. Used by tests/test_extension_js.py.
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..", "..", "extension");
const shape = fs.readFileSync(path.join(root, "content", "shape.js"), "utf8");
const badge = fs.readFileSync(path.join(root, "ui", "badge.js"), "utf8");

const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window;
const errors = [], calls = [], inserted = [];

const CTX = {
  platform: "shopify", seat: "Ana", slack: true, catalog: "https://shop.example/a/catalogue",
  templates: [
    { name: "Thank you", category: "After a purchase", body: "Dear {first_name},\n\nThank you for today.\n\nWarm regards,\nAna" },
    { name: "Birthday", category: "Moments", body: "Hi {first_name}, happy birthday from all of us." },
  ],
  suggested: ["Birthday"],
  campaigns: [{ id: "c1", name: "Winter edit", running: true, utm: "winter", starts: "1 Nov", ends: "1 Dec", members: 3 }],
  todos: [{ text: "Call Grace back", cid: "9", name: "Grace Ladoja" }],
  openers: {},
};
const GRACE = {
  found: true, cid: "9", name: "Grace Ladoja", email: "grace@example.com", phone: "+447700900123", grade: "A",
  ordersCount: 4, spend: 5200, last: "2 Sep", playLabel: "Gone quiet", hidden: true,
  action: "Invite her to the private view on Thursday.", reasons: ["Bought twice in a month", "Lives near the boutique"],
  orders: [{ date: "2026-09-02", amount: 1200, titles: ["Wool coat"] }],
  cart: { value: 900, count: 2, url: "https://shop.example/checkout" },
  templates: [], suggested: ["Thank you"], adminUrl: "https://admin.example/customers/9", dashboard: "https://haliascore.com/app#c9",
};

function respond(msg) {
  calls.push(msg.type);
  switch (msg.type) {
    case "halia:context": return CTX;
    case "halia:lookup": return GRACE;
    case "halia:clients": return { clients: [{ cid: "9", name: "Grace Ladoja", grade: "A", phone: "+447700900123" }, { cid: "10", name: "Ines Moreau", grade: "B" }] };
    case "halia:brief": return { summary: "She bought a coat last month and went quiet.", reply: "Dear Grace,\n\nThe private view is on Thursday.",
      actions: [{ kind: "pipeline", label: "Add to the pipeline", why: "Nobody is looking after her" }, { kind: "catalogue", label: "Send the catalogue" }, { kind: "visit", label: "Book a visit" }],
      source: "ai", ai_available: true, read_thread: 2 };
    case "halia:history": return { last_contact: { at: new Date(Date.now() - 3600e3).toISOString(), by: "Ben", action: "contacted" } };
    case "halia:action": return msg.body && msg.body.action === "appointment"
      ? { ok: true, links: { google: "https://g", outlook: "https://o", ics_data: "data:text/calendar,x", message: "See you Thursday at 3." } }
      : { ok: true };
    case "halia:products": return { products: [{ id: "p1", title: "Wool coat", image: "https://img.example/1.jpg", variants: [{ id: "v1", title: "Default Title", price: "1200" }] }],
      ids: ["p1"], facets: { collections: ["Coats"], sizes: ["S", "M"] }, cart_base: "https://shop.example" };
    case "halia:suggest": return { picks: [{ product_id: "p1", variant_id: "v1", title: "Wool coat", price: "1200", currency: "£", why: "She likes wool" }], ai_available: true };
    case "halia:catalogue": return { url: "https://shop.example/a/catalogue?c=1" };
    case "halia:image": return { dataUrl: "data:image/png;base64,AAAA" };
    case "halia:burst": return { template: "Thank you", clients: [{ cid: "9", name: "Grace Ladoja", first: "Grace", grade: "A", phone: "447700900123",
      email: "grace@example.com", message: "Dear Grace, thank you.", consent: { email: "subscribed", sms: "unknown" }, warn: [] }], skipped: [] };
    default: return { ok: true };
  }
}
w.chrome = {
  runtime: { lastError: null, sendMessage: (msg, cb) => { let r; try { r = respond(msg); } catch (e) { errors.push("respond " + msg.type + ": " + e.message); }
    if (cb) { try { cb(r); } catch (e) { errors.push("callback " + msg.type + ": " + (e.stack || e.message)); } } } },
  storage: { local: { get: (k, cb) => cb && cb({}), set: () => {}, remove: () => {} },
    sync: { get: (k, cb) => cb && cb({}), set: () => {} }, onChanged: { addListener: () => {} } },
};
Object.defineProperty(w.navigator, "clipboard", { value: { writeText: () => Promise.resolve(), write: () => Promise.resolve() } });
w.eval(shape);
w.eval(badge);

const P = w.HaliaPanel;
const checks = {};
const step = (name, fn) => { try { const v = fn(); if (v !== undefined) checks[name] = v; } catch (e) { errors.push(name + ": " + (e.stack || e.message)); checks[name] = false; } };
let sr, $, body, text, click;

(async () => {
  step("mount", () => {
    P.setInserter((t) => { inserted.push(t); return true; });
    P.setThreadReader(() => [{ from: "them", text: "Is the coat back?" }]);
    P.setChannel("whatsapp");
    P.mount();
    P.setContext(CTX);
    sr = w.document.getElementById("halia-badge-host").shadowRoot;
    $ = (s) => sr.querySelector(s);
    body = () => $('[data-a="body"]');
    text = () => body().textContent;
    click = (s) => { const el = $(s); if (!el) throw new Error("no element " + s); el.click(); };
    return /Open a chat or an email/.test(text()) && !$(".dock").classList.contains("open");
  });
  step("loading", () => { P.setClient({ loading: true, name: "Grace" }); return !!$(".sk"); });
  step("home", () => {
    P.setClient({ found: true, data: GRACE });
    return $(".dock").classList.contains("open") && /Grace Ladoja/.test(text()) && /Next move/.test(text())
      && /Invite her/.test(text()) && /Contacted/.test(text()) && /Open basket/.test(text()) && !!$('[data-a="reply"]');
  });
  step("handle", () => $(".handle .hg").textContent === "A");
  step("reply", () => {
    click('[data-a="reply"]');
    const ta = $('[data-a="dtext"]');
    const ok = !!ta && /Dear Grace/.test(ta.value) && /Worth doing/.test(text());
    click('[data-a="dins"]');
    click("[data-ba=\"0\"]");
    return ok && inserted.length === 1 && calls.indexOf("halia:action") >= 0;
  });
  step("back", () => { click('[data-a="back"]'); return !!$('[data-a="reply"]'); });
  step("templates", () => {
    click('[data-q="templates"]');
    const items = sr.querySelectorAll("[data-ti]");
    click('[data-ti="0"]');
    const ok = items.length === 2 && /For Grace/.test(text()) && /Dear Grace/.test($(".prev").textContent);
    click('[data-a="tins"]');
    return ok && inserted.length === 2;
  });
  step("book", () => {
    click('[data-a="back"]'); click('[data-q="book"]');
    $('[data-a="apwhen"]').value = "2026-10-01T15:00";
    click('[data-a="apbook"]');
    const ok = /Booked/.test(text());
    click('[data-a="apsend"]');
    return ok && inserted[inserted.length - 1] === "See you Thursday at 3.";
  });
  step("sell", () => {
    click('[data-a="back"]'); click('[data-q="sell"]');
    const loaded = !!$(".prow") && /Wool coat/.test(text());
    click('[data-a="sgo"]');
    click('[data-a="sadd"]');
    const inCart = /1 piece/.test(text());
    click('[data-a="csend"]');
    const cartLink = /shop\.example\/cart\/v1:1/.test(inserted[inserted.length - 1]);
    click('[data-a="ccat"]');
    const cat = /catalogue\?c=1/.test(inserted[inserted.length - 1]);
    click('[data-a="catsend"]');
    return loaded && inCart && cartLink && cat && /a\/catalogue/.test(inserted[inserted.length - 1]);
  });
  step("more", () => {
    click('[data-a="back"]'); click('[data-q="more"]');
    const ok = /Why they surfaced/.test(text()) && /Previous orders/.test(text()) && /Add to the pipeline/.test(text());
    click('[data-a="pipe"]');
    click('[data-lr="Called"]');
    click('[data-a="logc"]');
    click('[data-a="noteopen"]');
    $('[data-a="note"]').value = "Prefers mornings";
    click('[data-a="notesave"]');
    return ok;
  });
  step("team", () => {
    click('[data-a="back"]'); click('[data-a="menu"]'); click('[data-m="team"]');
    return /Mark Grace as contacted/.test(text()) && /Call Grace back/.test(text());
  });
  step("several", () => {
    click('[data-a="back"]'); click('[data-a="menu"]'); click('[data-m="several"]');
    click('[data-a="bopen"]');
    click('[data-bi="0"]');
    $('[data-a="btpl"]').value = "Thank you";
    click('[data-a="bgo"]');
    const stepper = /1 of 1/.test(text()) && !!$('[data-a="bins"]');
    click('[data-a="bins"]');
    click('[data-a="bsent"]');
    const done = /1 sent/.test(text());
    click('[data-a="bfin"]');
    return stepper && done && !!$('[data-a="reply"]');
  });
  step("search", () => {
    const q = $('[data-a="q"]'); q.value = "gr"; q.dispatchEvent(new w.Event("input", { bubbles: true }));
  });
  await new Promise((r) => setTimeout(r, 350));
  step("search-results", () => {
    const ok = /Your book/.test(text()) && sr.querySelectorAll(".litem").length === 2;
    click('[data-i="1"]');
    return ok && /Grace Ladoja/.test(text()) && !!$('[data-a="unpin"]');
  });
  step("unpin", () => { click('[data-a="unpin"]'); return /Open a chat or an email/.test(text()); });
  step("notfound", () => { P.setClient({ notfound: true, name: "Bob Ray" }); return /Not in your book yet/.test(text()); });
  step("error", () => { P.setClient({ error: "Could not reach Halia." }); return /Could not reach Halia/.test(text()); });
  step("share", () => {
    P.setClient(null);
    P.setShare({ url: "https://shop.example/products/coat", title: "Wool coat", kind: "product" });
    const chips = sr.querySelectorAll(".chip").length >= 5;
    click('[data-ci="0"]');
    const ta = $('[data-a="shdraft"]');
    const ok = !!ta && /Dear Grace/.test(ta.value) && /Wool coat/.test(ta.value);
    click('[data-a="shcopy"]');
    P.setShare(null);
    return chips && ok && /Open a chat or an email/.test(text());
  });
  step("team-surface", () => { P.setMode("internal", false); return /Tell the team/.test(text()); });
  step("signout", () => { click('[data-a="menu"]'); click('[data-m="signout"]'); return calls.indexOf("halia:signout") >= 0; });
  step("no-native-dialogs", () => !/\bconfirm\(|\bprompt\(|\balert\(/.test(badge));
  step("type-floor", () => !/font-size:\s*(1[01](\.\d+)?|[0-9])px/.test(badge));
  step("no-idle-motion", () => !/infinite/.test(badge));

  console.log(JSON.stringify({ errors, checks, inserted: inserted.length }));
})();
