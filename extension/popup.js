const state = document.getElementById("state");

chrome.runtime.sendMessage({ type: "halia:config" }, (c) => {
  if (chrome.runtime.lastError || !c) {
    state.textContent = "Could not read settings.";
    state.className = "state bad";
    return;
  }
  if (c.hasToken) {
    state.textContent = "Connected to " + c.base.replace(/^https?:\/\//, "");
    state.className = "state ok";
  } else {
    state.textContent = "Not connected yet. Add your Halia token in settings.";
    state.className = "state bad";
  }
});

document.getElementById("open").onclick = () => {
  chrome.runtime.openOptionsPage();
  window.close();
};
