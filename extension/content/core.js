// Halia content core — shared by every surface. A surface script calls Halia.observe(extract),
// where extract() returns an identity {cid|email|phone|name} for whatever client the page is
// currently showing, or null. The core watches the (single-page) app for navigation and DOM
// changes, debounces, de-dupes by identity, and drives the badge. One lookup per distinct client.

(function () {
  if (window.Halia) return;

  function lookup(query) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type: "halia:lookup", query }, (resp) => {
          if (chrome.runtime.lastError) return resolve({ error: "network" });
          resolve(resp || { error: "empty" });
        });
      } catch (e) {
        resolve({ error: "context" });
      }
    });
  }

  function keyOf(id) {
    if (!id) return "";
    return ["cid:" + (id.cid || ""), "e:" + (id.email || ""), "p:" + (id.phone || ""),
      "n:" + (id.name || "")].join("|");
  }

  function observe(extract) {
    let last = "";
    let inflight = 0;

    async function tick() {
      let id = null;
      try { id = extract(); } catch (e) { id = null; }
      const key = id ? keyOf(id) : "";
      if (!key) {
        if (last) { last = ""; HaliaBadge.hide(); }
        return;
      }
      if (key === last) return;
      last = key;
      const mine = ++inflight;
      HaliaBadge.loading(id);
      const resp = await lookup(id);
      if (mine !== inflight || last !== key) return; // a newer client took over while we waited
      if (resp && resp.error) {
        if (resp.error === "no-token" || resp.error === "unauthorized" || resp.error === "network") {
          HaliaBadge.error(resp.error);
        } else {
          HaliaBadge.hide();
        }
        return;
      }
      if (!resp || !resp.found) { HaliaBadge.notFound(id); return; }
      HaliaBadge.mount(resp);
    }

    const debounced = (() => {
      let t = null;
      return () => { clearTimeout(t); t = setTimeout(tick, 400); };
    })();

    // URL changes (SPA nav) — patch history + poll as a backstop.
    let lastUrl = location.href;
    const onNav = () => { if (location.href !== lastUrl) { lastUrl = location.href; debounced(); } };
    ["pushState", "replaceState"].forEach((m) => {
      const orig = history[m];
      history[m] = function () { const r = orig.apply(this, arguments); onNav(); return r; };
    });
    window.addEventListener("popstate", onNav);
    setInterval(onNav, 1200);

    // DOM changes (content swaps without a URL change, e.g. opening a chat/email).
    const mo = new MutationObserver(debounced);
    mo.observe(document.documentElement, { childList: true, subtree: true });

    debounced(); // first run
  }

  window.Halia = { observe, lookup };
})();
