const $ = (id) => document.getElementById(id);
const DEFAULT_BASE = "https://haliascore.com";

function setStatus(el, msg, ok) {
  el.textContent = msg || "";
  el.className = "status" + (msg ? (ok ? " ok" : " bad") : "");
}

// ── two modes: a stepped wizard until connected, a plain settings page after ──
let step = 1;
function showStep(n) {
  step = Math.max(1, Math.min(4, n));
  document.querySelectorAll(".step").forEach((s) => s.classList.toggle("on", +s.dataset.step === step));
  document.querySelectorAll(".dots i").forEach((d) => d.classList.toggle("on", +d.dataset.d <= step));
}
function setMode(settled) {
  document.body.className = settled ? "settled" : "wizard";
  if (!settled) showStep(step);
}

async function load() {
  const { haliaBase, haliaToken, haliaName, radarOff, lookupEverywhere } = await chrome.storage.sync.get(
    ["haliaBase", "haliaToken", "haliaName", "radarOff", "lookupEverywhere"]);
  $("token").value = haliaToken || "";
  $("base").value = haliaBase || DEFAULT_BASE;
  const sl = $("supportlink");
  if (sl) sl.href = (haliaBase || DEFAULT_BASE).replace(/\/+$/, "") + "/contact?chat=open";
  $("name").value = haliaName || "";
  loadProfile(haliaBase || DEFAULT_BASE, haliaToken);
  $("radar").checked = !radarOff;
  $("everywhere").checked = !!lookupEverywhere;
  renderStores();
  setMode(!!haliaToken);
  if (haliaToken) setStatus($("connstatus"), "Connected ✓", true);
}

async function persist() {
  const base = ($("base").value.trim() || DEFAULT_BASE).replace(/\/+$/, "");
  await chrome.storage.sync.set({
    haliaToken: $("token").value.trim(),
    haliaBase: base,
    haliaName: $("name").value.trim().slice(0, 80),
    radarOff: !$("radar").checked,
  });
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
  await persist();
  setStatus($("status"), "Testing…", true);
  // A harmless lookup: a valid token returns found:false for an unknown address; a bad token 401s.
  const r = await ask({ email: "connection-check@halia.invalid" });
  if (r && r.error === "unauthorized") return setStatus($("status"), "Token not recognised", false);
  if (r && r.error === "no-token") return setStatus($("status"), "Connect first", false);
  if (r && r.error === "network") return setStatus($("status"), "Could not reach Halia", false);
  return setStatus($("status"), "Connected", true);
}

// ── the one-click path ──
$("openhalia").onclick = () => {
  const base = ($("base").value || "").trim() || DEFAULT_BASE;
  chrome.tabs.create({ url: base.replace(/\/$/, "") + "/app" });
  setStatus($("connstatus"), "Waiting for you to press Connect in Halia…", true);
};

// The dashboard bridge stores the token in the background; move forward the moment it lands.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "sync" || !changes.haliaToken) return;
  const v = changes.haliaToken.newValue || "";
  $("token").value = v;
  if (changes.haliaName && changes.haliaName.newValue) $("name").value = changes.haliaName.newValue;
  setStatus($("connstatus"), v ? "Connected ✓" : "", true);
  if (v && document.body.className === "wizard" && step === 1) showStep(2);
});

// the token fallback: save, prove it works, then continue
$("tokenconnect").onclick = async () => {
  await persist();
  setStatus($("connstatus"), "Checking…", true);
  const r = await ask({ email: "connection-check@halia.invalid" });
  if (r && (r.error === "unauthorized" || r.error === "no-token"))
    return setStatus($("connstatus"), "Token not recognised", false);
  if (r && r.error === "network") return setStatus($("connstatus"), "Could not reach Halia", false);
  setStatus($("connstatus"), "Connected ✓", true);
  if (document.body.className === "wizard") showStep(2);
};

// ── wizard navigation ──
document.querySelectorAll("[data-next]").forEach((b) => b.onclick = async () => { await persist(); showStep(step + 1); });
document.querySelectorAll("[data-skip]").forEach((b) => b.onclick = () => showStep(step + 1));
document.querySelectorAll("[data-finish]").forEach((b) => b.onclick = async () => {
  await persist();
  setMode(true);
  setStatus($("status"), "Saved", true);
});

// ── settings-mode actions ──
async function signOut() {
  await new Promise((res) => chrome.runtime.sendMessage({ type: "halia:signout" }, () => res()));
  $("token").value = "";
  $("name").value = "";
  setStatus($("connstatus"), "", true);
  step = 1;
  setMode(false);
}
$("test").onclick = test;
$("signout").onclick = signOut;
$("base").onchange = persist;
$("name").onchange = () => { persist(); saveProfile(); };
["pemail", "ptitle", "psignoff"].forEach((id) => { const el = $(id); if (el) el.onchange = saveProfile; });

// ── the associate's profile lives on their seat (server); the extension edits it ──
async function profileHeaders() {
  const { haliaBase, haliaToken } = await chrome.storage.sync.get(["haliaBase", "haliaToken"]);
  const base = (haliaBase || DEFAULT_BASE).replace(/\/+$/, "");
  return { base, headers: { "X-Halia-Ext-Token": haliaToken || "", "Content-Type": "application/json" } };
}
async function loadProfile(base, token) {
  if (!token) return;
  try {
    const r = await fetch(base.replace(/\/+$/, "") + "/v1/extension/profile", { headers: { "X-Halia-Ext-Token": token } });
    if (!r.ok) return;
    const d = await r.json(); const p = (d && d.profile) || {};
    if (p.name && !$("name").value) $("name").value = p.name;
    if ($("pemail")) $("pemail").value = p.email || "";
    if ($("ptitle")) $("ptitle").value = p.title || "";
    if ($("psignoff")) $("psignoff").value = p.default_signoff ? "" : (p.signoff || "");
    if ($("psignoff") && !$("psignoff").value) $("psignoff").placeholder = p.signoff || $("psignoff").placeholder;
  } catch (_) { /* offline: keep what is on screen */ }
}
async function saveProfile() {
  const { base, headers } = await profileHeaders();
  if (!headers["X-Halia-Ext-Token"]) return;
  const body = { name: $("name").value.trim(), email: ($("pemail") || {}).value || "",
                 title: ($("ptitle") || {}).value || "", signoff: ($("psignoff") || {}).value || "" };
  try {
    const r = await fetch(base + "/v1/extension/profile", { method: "POST", headers, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) return setStatus($("pstatus"), d.detail || "Could not save your details.", false);
    setStatus($("pstatus"), "Saved", true);
  } catch (_) { setStatus($("pstatus"), "Could not reach Halia.", false); }
}
$("radar").onchange = persist;

// ── look up on any page: needs a broad host grant, so it is a deliberate opt-in ──
async function toggleEverywhere() {
  const on = $("everywhere").checked;
  if (on) {
    let granted = false;
    try { granted = await chrome.permissions.request({ origins: ["*://*/*"] }); } catch (e) { granted = false; }
    if (!granted) {
      $("everywhere").checked = false;
      return setStatus($("everywherestatus"), "Access not granted", false);
    }
    await chrome.storage.sync.set({ lookupEverywhere: true });
    chrome.runtime.sendMessage({ type: "halia:select-sync" });
    setStatus($("everywherestatus"), "On", true);
  } else {
    await chrome.storage.sync.set({ lookupEverywhere: false });
    chrome.runtime.sendMessage({ type: "halia:select-sync" });
    try { await chrome.permissions.remove({ origins: ["*://*/*"] }); } catch (e) { /* keep going */ }
    setStatus($("everywherestatus"), "Off", true);
  }
}
$("everywhere").onchange = toggleEverywhere;

// ── your store website: grant one site, register the panel inside it ──
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
  if (!origin) return setStatus($("woostatus"), "Enter the full address", false);
  let granted = false;
  try { granted = await chrome.permissions.request({ origins: [origin + "/*"] }); } catch (e) { granted = false; }
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
  try { await chrome.permissions.remove({ origins: [origin + "/*"] }); } catch (e) { /* keep going */ }
  chrome.runtime.sendMessage({ type: "halia:woo-sync" });
  renderStores();
}
$("addwoo").onclick = addStore;

load();
