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
    state.textContent = "Not connected yet. Add your Halia token in settings.";
    state.className = "state bad";
  }
});

document.getElementById("open").onclick = () => {
  chrome.runtime.openOptionsPage();
  window.close();
};
