const $ = (id) => document.getElementById(id);
const DEFAULT_BASE = "https://haliascore.com";

function setStatus(el, msg, ok) {
  el.textContent = msg || "";
  el.className = "status" + (msg ? (ok ? " ok" : " bad") : "");
}

async function load() {
  const { haliaBase, haliaToken, haliaName } = await chrome.storage.sync.get(
    ["haliaBase", "haliaToken", "haliaName"]);
  $("token").value = haliaToken || "";
  $("base").value = haliaBase || DEFAULT_BASE;
  $("name").value = haliaName || "";
  renderStores();
}

async function save() {
  const token = $("token").value.trim();
  const name = $("name").value.trim().slice(0, 80);
  let base = ($("base").value.trim() || DEFAULT_BASE).replace(/\/+$/, "");
  await chrome.storage.sync.set({ haliaToken: token, haliaBase: base, haliaName: name });
  setStatus($("status"), "Saved", true);
}

function ask(query) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "halia:lookup", query }, (r) => {
      if (chrome.runtime.lastError) return resolve({ error: "network" });
      resolve(r || { error: "empty" });
    });
  });
}

async function test() {
  await save();
  setStatus($("status"), "Testing…", true);
  // A harmless lookup: a valid token returns found:false for an unknown address; a bad token 401s.
  const r = await ask({ email: "connection-check@halia.invalid" });
  if (r && r.error === "unauthorized") return setStatus($("status"), "Token not recognised", false);
  if (r && r.error === "no-token") return setStatus($("status"), "Paste your token first", false);
  if (r && r.error === "network") return setStatus($("status"), "Could not reach Halia", false);
  if (r && (r.error === "bad-query")) return setStatus($("status"), "Connected", true);
  return setStatus($("status"), "Connected", true);
}

// ── WooCommerce: grant this one site, then register the badge inside its wp-admin ──
function normOrigin(v) {
  try {
    const u = new URL(v.trim());
    return u.protocol + "//" + u.host;
  } catch (e) {
    return "";
  }
}

async function renderStores() {
  const { wooOrigins = [] } = await chrome.storage.sync.get("wooOrigins");
  const ul = $("stores");
  ul.innerHTML = "";
  wooOrigins.forEach((o) => {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = o;
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = "Remove";
    btn.onclick = () => removeStore(o);
    li.appendChild(span);
    li.appendChild(btn);
    ul.appendChild(li);
  });
}

async function addStore() {
  const origin = normOrigin($("woo").value);
  if (!origin) return setStatus($("woostatus"), "Enter a full address like https://yourstore.com", false);
  let granted;
  try {
    granted = await chrome.permissions.request({ origins: [origin + "/*"] });
  } catch (e) {
    granted = false;
  }
  if (!granted) return setStatus($("woostatus"), "Access not granted", false);
  const { wooOrigins = [] } = await chrome.storage.sync.get("wooOrigins");
  if (!wooOrigins.includes(origin)) wooOrigins.push(origin);
  await chrome.storage.sync.set({ wooOrigins });
  chrome.runtime.sendMessage({ type: "halia:woo-sync" });
  $("woo").value = "";
  setStatus($("woostatus"), "Added", true);
  renderStores();
}

async function removeStore(origin) {
  const { wooOrigins = [] } = await chrome.storage.sync.get("wooOrigins");
  await chrome.storage.sync.set({ wooOrigins: wooOrigins.filter((o) => o !== origin) });
  try { await chrome.permissions.remove({ origins: [origin + "/*"] }); } catch (e) {}
  chrome.runtime.sendMessage({ type: "halia:woo-sync" });
  renderStores();
}

$("save").onclick = save;
$("test").onclick = test;
$("addwoo").onclick = addStore;
load();
