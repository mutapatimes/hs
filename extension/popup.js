const state = document.getElementById("state");
const head = document.getElementById("head");
const dot = document.getElementById("dot");

chrome.runtime.sendMessage({ type: "halia:config" }, (c) => {
  head.classList.remove("checking");
  if (chrome.runtime.lastError || !c) {
    state.textContent = "Could not read settings.";
    state.className = "state bad";
    return;
  }
  if (c.hasToken) {
    state.textContent = "Watching for clients on " + c.base.replace(/^https?:\/\//, "") + ".";
    state.className = "state ok";
    dot.classList.add("ok");
  } else {
    state.textContent = "Not connected yet. Open Halia, on the web or from your Shopify admin's Apps menu, and press Connect this browser in Settings.";
    state.className = "state bad";
    const open = document.getElementById("open");
    open.textContent = "Open Halia →";
    open.onclick = () => {
      chrome.tabs.create({ url: (c.base || "https://haliascore.com").replace(/\/$/, "") + "/app" });
      window.close();
    };
    return;
  }
});

document.getElementById("open").onclick = () => {
  chrome.runtime.openOptionsPage();
  window.close();
};

document.getElementById("support").onclick = (e) => {
  e.preventDefault();
  chrome.runtime.sendMessage({ type: "halia:config" }, (c) => {
    const base = ((c && c.base) || "https://haliascore.com").replace(/\/$/, "");
    chrome.tabs.create({ url: base + "/contact?chat=open" });
    window.close();
  });
};
