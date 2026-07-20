// Halia extension — service worker. The only place the token lives at request time and the only
// place that talks to the Halia API, so page scripts never see the token and there is no page-origin
// CORS to fight (the fetch runs from the extension, which holds host_permissions for the API).

const DEFAULT_BASE = "https://haliascore.com";

async function config() {
  const { haliaBase, haliaToken } = await chrome.storage.sync.get(["haliaBase", "haliaToken"]);
  return { base: (haliaBase || DEFAULT_BASE).replace(/\/+$/, ""), token: haliaToken || "" };
}

async function lookup(query) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  let res;
  try {
    res = await fetch(base + "/v1/extension/lookup", {
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

async function context() {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  let res;
  try {
    res = await fetch(base + "/v1/extension/context", {
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

async function action(body) {
  const { base, token } = await config();
  if (!token) return { error: "no-token" };
  let res;
  try {
    res = await fetch(base + "/v1/extension/action", {
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
  if (msg && msg.type === "halia:config") {
    config().then((c) => sendResponse({ base: c.base, hasToken: !!c.token }));
    return true;
  }
  if (msg && msg.type === "halia:woo-sync") {
    syncWooScripts().then(() => sendResponse({ ok: true }));
    return true;
  }
});
