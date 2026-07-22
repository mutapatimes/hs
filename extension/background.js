// Halia extension — service worker. The only place the token lives at request time and the only
// place that talks to the Halia API, so page scripts never see the token and there is no page-origin
// CORS to fight (the fetch runs from the extension, which holds host_permissions for the API).

const DEFAULT_BASE = "https://haliascore.com";

async function config() {
  const { haliaBase, haliaToken } = await chrome.storage.sync.get(["haliaBase", "haliaToken"]);
  return { base: (haliaBase || DEFAULT_BASE).replace(/\/+$/, ""), token: haliaToken || "" };
}

// fetch with a hard timeout, so a slow or unreachable Halia fails fast instead of hanging forever.
async function hfetch(url, init, ms) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms || 20000);
  try {
    return await fetch(url, Object.assign({}, init, { signal: c.signal }));
  } finally {
    clearTimeout(t);
  }
}

async function lookup(query) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  let res;
  try {
    res = await hfetch(base + "/v1/extension/lookup", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Halia-Ext-Token": token },
      body: JSON.stringify(query || {})
    });
  } catch (e) {
    return { error: "network" };
  }
  if (res.status === 401) return { error: "unauthorized" };
  if (res.status === 422) return { error: "bad-query" };
  if (!res.ok) return { error: "http-" + res.status };
  try {
    return await res.json();
  } catch (e) {
    return { error: "parse" };
  }
}

// WooCommerce admin lives on the merchant's own domain, unknown at build time. The options page
// grants access to that one site and stores it; here we register the badge inside its wp-admin.
async function syncWooScripts() {
  const { wooOrigins = [] } = await chrome.storage.sync.get("wooOrigins");
  try {
    const existing = await chrome.scripting.getRegisteredContentScripts({ ids: ["halia-woo"] });
    if (existing.length) await chrome.scripting.unregisterContentScripts({ ids: ["halia-woo"] });
  } catch (e) { /* nothing registered yet */ }
  const matches = [];
  for (const o of wooOrigins) {
    const origin = o.replace(/\/+$/, "") + "/*";
    try {
      if (await chrome.permissions.contains({ origins: [origin] })) {
        matches.push(o.replace(/\/+$/, "") + "/wp-admin/*");
      }
    } catch (e) { /* skip */ }
  }
  if (!matches.length) return;
  try {
    await chrome.scripting.registerContentScripts([{
      id: "halia-woo",
      matches,
      js: ["ui/badge.js", "content/core.js", "content/admin.js"],
      runAt: "document_idle",
      persistAcrossSessions: true
    }]);
  } catch (e) { /* ignore */ }
}

chrome.runtime.onInstalled.addListener(syncWooScripts);
chrome.runtime.onStartup.addListener(syncWooScripts);

// ── Right-click "Look up in Halia" — works on any page, on selected text ──────
function ensureMenu() {
  try {
    chrome.contextMenus.removeAll(() => {
      chrome.contextMenus.create({
        id: "halia-lookup", title: "Look up “%s” in Halia", contexts: ["selection"]
      });
    });
  } catch (e) { /* ignore */ }
}
chrome.runtime.onInstalled.addListener(ensureMenu);
chrome.runtime.onStartup.addListener(ensureMenu);

function queryFor(text) {
  const t = (text || "").trim();
  if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(t)) return { email: t };
  if (/^\+?[\d][\d\s\-()]{6,}$/.test(t)) return { phone: t.replace(/[^\d+]/g, "") };
  return { name: t };
}

const notifUrl = {};   // notification id -> url to open on click
function notify(id, title, message, url) {
  notifUrl[id] = url || "";
  try {
    chrome.notifications.create(id, {
      type: "basic", iconUrl: "icons/icon128.png", title: String(title).slice(0, 90),
      message: String(message || "").slice(0, 220), priority: 1
    });
  } catch (e) { /* ignore */ }
}
if (chrome.notifications && chrome.notifications.onClicked) {
  chrome.notifications.onClicked.addListener((id) => {
    if (notifUrl[id]) chrome.tabs.create({ url: notifUrl[id] });
    chrome.notifications.clear(id);
  });
}

if (chrome.contextMenus && chrome.contextMenus.onClicked) {
  chrome.contextMenus.onClicked.addListener(async (info) => {
    if (info.menuItemId !== "halia-lookup") return;
    const text = (info.selectionText || "").trim();
    if (!text) return;
    const r = await lookup(queryFor(text));
    if (r && r.error) {
      notify("halia-lu", "Halia", r.error === "no-token"
        ? "Add your Halia token in the extension options first." : "Could not reach Halia.");
      return;
    }
    if (!r || !r.found) { notify("halia-lu", "Halia", "No signal for “" + text + "”."); return; }
    const bits = [];
    if (r.latent) bits.push("Latent " + r.latent);
    if (r.playLabel) bits.push(r.playLabel);
    if (r.action) bits.push(r.action);
    notify("halia-lu", (r.name || text) + " · " + (r.grade || ""),
      bits.join(" · ") || "In your book", r.dashboard);
  });
}

async function context() {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  let res;
  try {
    res = await hfetch(base + "/v1/extension/context", {
      headers: { "X-Halia-Ext-Token": token }
    });
  } catch (e) {
    return { error: "network" };
  }
  if (res.status === 401) return { error: "unauthorized" };
  if (!res.ok) return { error: "http-" + res.status };
  try {
    return await res.json();
  } catch (e) {
    return { error: "parse" };
  }
}

async function events() {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  try {
    const res = await hfetch(base + "/v1/extension/events", { headers: { "X-Halia-Ext-Token": token } });
    if (!res.ok) return { error: "http-" + res.status };
    return await res.json();
  } catch (e) {
    return { error: "network" };
  }
}

// ── Proactive VIC radar: poll the live alert feed and fire a desktop notification for each new
// high-grade order, wherever the associate is. First run is silent (seeds "seen") so installing
// doesn't blast a backlog.
async function pollRadar() {
  const { radarOff } = await chrome.storage.sync.get(["radarOff"]);
  if (radarOff) return;
  const { base, token } = await config();
  if (!token) return;
  const r = await events();
  if (!r || r.error || !Array.isArray(r.events)) return;
  const idOf = (e) => String(e.order_id || e.when || "");
  const ids = r.events.map(idOf).filter(Boolean);
  const st = await chrome.storage.local.get(["seenEvents", "radarInit"]);
  if (!st.radarInit) {                     // first run: remember, don't notify
    await chrome.storage.local.set({ seenEvents: ids.slice(-200), radarInit: true });
    return;
  }
  const seen = new Set(st.seenEvents || []);
  const fresh = r.events.filter((e) => idOf(e) && !seen.has(idOf(e)));
  for (const e of fresh.slice(0, 5)) {
    const bits = [];
    if (e.spend) bits.push("£" + Number(e.spend).toLocaleString());
    if (e.signals && e.signals.length) bits.push(e.signals.join(" · "));
    notify("halia-ev-" + idOf(e), "New " + (e.grade || "VIC") + " order · " + (e.name || "a client"),
      bits.join(" · ") || "A high-grade client just ordered.", base + "/app");
  }
  const merged = Array.from(new Set([...(st.seenEvents || []), ...ids])).slice(-300);
  await chrome.storage.local.set({ seenEvents: merged });
}

function armRadar() {
  try { chrome.alarms.create("halia-radar", { periodInMinutes: 2, delayInMinutes: 0.2 }); } catch (e) { /* ignore */ }
}
chrome.runtime.onInstalled.addListener(armRadar);
chrome.runtime.onStartup.addListener(armRadar);
if (chrome.alarms && chrome.alarms.onAlarm) {
  chrome.alarms.onAlarm.addListener((a) => { if (a.name === "halia-radar") pollRadar(); });
}

async function history(cid) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  try {
    const res = await hfetch(base + "/v1/extension/history?cid=" + encodeURIComponent(cid || ""),
      { headers: { "X-Halia-Ext-Token": token } });
    if (!res.ok) return { error: "http-" + res.status };
    return await res.json();
  } catch (e) {
    return { error: "network" };
  }
}

async function products(q) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  const url = base + "/v1/extension/products?limit=20&q=" + encodeURIComponent(q || "");
  let res;
  try {
    res = await hfetch(url, { headers: { "X-Halia-Ext-Token": token } });
  } catch (e) {
    return { error: "network" };
  }
  if (res.status === 401) return { error: "unauthorized" };
  if (!res.ok) return { error: "http-" + res.status };
  try {
    return await res.json();
  } catch (e) {
    return { error: "parse" };
  }
}

async function batch(body) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  let res;
  try {
    res = await hfetch(base + "/v1/extension/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Halia-Ext-Token": token },
      body: JSON.stringify(body || {})
    });
  } catch (e) {
    return { error: "network" };
  }
  if (!res.ok) return { error: "http-" + res.status };
  try {
    return await res.json();
  } catch (e) {
    return { error: "parse" };
  }
}

async function action(body) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  body = body || {};
  if (!body.actor) {
    const { haliaName } = await chrome.storage.sync.get(["haliaName"]);
    if (haliaName) body.actor = haliaName;          // attribute team logs to the associate
  }
  let res;
  try {
    res = await hfetch(base + "/v1/extension/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Halia-Ext-Token": token },
      body: JSON.stringify(body || {})
    });
  } catch (e) {
    return { error: "network" };
  }
  if (res.status === 401) return { error: "unauthorized" };
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch (e) { /* ignore */ }
    return { error: "http-" + res.status, detail };
  }
  try {
    return await res.json();
  } catch (e) {
    return { error: "parse" };
  }
}

async function draft(body) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  let res;
  try {
    res = await hfetch(base + "/v1/extension/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Halia-Ext-Token": token },
      body: JSON.stringify(body || {})
    }, 30000);   // a model call is slower than a lookup, so give it more room
  } catch (e) {
    return { error: "network" };
  }
  if (res.status === 401) return { error: "unauthorized" };
  if (!res.ok) return { error: "http-" + res.status };
  try {
    return await res.json();
  } catch (e) {
    return { error: "parse" };
  }
}

// The conversation brief: summary + recommended actions + a ready-to-send reply, in one call.
async function brief(body) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  let res;
  try {
    res = await hfetch(base + "/v1/extension/brief", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Halia-Ext-Token": token },
      body: JSON.stringify(body || {})
    }, 45000);   // a structured model call is the slowest thing the toolbar does
  } catch (e) {
    return { error: "network" };
  }
  if (res.status === 401) return { error: "unauthorized" };
  if (!res.ok) return { error: "http-" + res.status };
  try {
    return await res.json();
  } catch (e) {
    return { error: "parse" };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "halia:lookup") {
    lookup(msg.query).then(sendResponse);
    return true; // keep the channel open for the async response
  }
  if (msg && msg.type === "halia:context") {
    context().then(sendResponse);
    return true;
  }
  if (msg && msg.type === "halia:action") {
    action(msg.body).then(sendResponse);
    return true;
  }
  if (msg && msg.type === "halia:batch") {
    batch(msg.body).then(sendResponse);
    return true;
  }
  if (msg && msg.type === "halia:products") {
    products(msg.q).then(sendResponse);
    return true;
  }
  if (msg && msg.type === "halia:history") {
    history(msg.cid).then(sendResponse);
    return true;
  }
  if (msg && msg.type === "halia:draft") {
    draft(msg.body).then(sendResponse);
    return true;
  }
  if (msg && msg.type === "halia:brief") {
    brief(msg.body).then(sendResponse);
    return true;
  }
  if (msg && msg.type === "halia:config") {
    config().then((c) => sendResponse({ base: c.base, hasToken: !!c.token }));
    return true;
  }
  if (msg && msg.type === "halia:woo-sync") {
    syncWooScripts().then(() => sendResponse({ ok: true }));
    return true;
  }
});
