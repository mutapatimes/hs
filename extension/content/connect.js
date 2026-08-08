// Halia connect bridge — runs ONLY on the Halia dashboard (haliascore.com).
//
// Lets the signed-in dashboard hand THIS browser's extension its store token in one click, so a
// merchant never types or pastes a token. The token is minted by the authenticated dashboard, only
// ever travels inside the haliascore.com page (which the merchant is logged in to), and is stored by
// the extension's background worker exactly as a pasted token would be. No other site runs this
// script, so no other origin can reach it.
(function () {
  var ORIGIN = location.origin;

  // Announce presence so the dashboard shows "Connect this browser" instead of the token fallback.
  function announce() {
    try { window.postMessage({ source: "halia-ext", type: "present" }, ORIGIN); } catch (e) { /* ignore */ }
  }
  announce();

  window.addEventListener("message", function (e) {
    if (e.origin !== ORIGIN) return;                 // only trust our own page
    var d = e.data;
    if (!d || d.source !== "halia-dashboard") return;

    if (d.type === "ping") { announce(); return; }    // re-announce if the dashboard asks

    if (d.type === "connect" && d.token) {
      chrome.runtime.sendMessage(
        { type: "halia:connect", token: String(d.token), base: d.base || ORIGIN, name: d.name || "" },
        function (r) {
          var ok = !chrome.runtime.lastError && r && r.ok;
          window.postMessage({ source: "halia-ext", type: "connected", ok: !!ok }, ORIGIN);
        }
      );
    }
  });
})();
