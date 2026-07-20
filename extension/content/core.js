// Halia content core — shared by every surface. Mounts the persistent toolbar, loads the standing
// context (templates, running campaigns, catalogue), and keeps the toolbar's "client" section in
// step with whoever the page is showing. A surface script calls Halia.observe(extract), where
// extract() returns an identity {cid|email|phone|name} for the current client, or null.

(function () {
  if (window.Halia) return;

  function send(type, query) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type, query }, (resp) => {
          if (chrome.runtime.lastError) return resolve({ error: "network" });
          resolve(resp || { error: "empty" });
        });
      } catch (e) {
        resolve({ error: "context" });
      }
    });
  }
  const lookup = (query) => send("halia:lookup", query);

  function loadContext() {
    send("halia:context").then((resp) => HaliaPanel.setContext(resp && !resp.error ? resp : null));
  }

  function keyOf(id) {
    if (!id) return "";
    return ["cid:" + (id.cid || ""), "e:" + (id.email || ""), "p:" + (id.phone || ""),
      "n:" + (id.name || "")].join("|");
  }
  const friendly = {
    "no-token": "Add your Halia token in the extension options to start.",
    "unauthorized": "Your Halia token is not recognised. Re-generate it in Settings.",
    "network": "Could not reach Halia. Check the address in the options."
  };

  function observe(extract) {
    HaliaPanel.mount();
    loadContext();
    window.addEventListener("halia:refresh", loadContext);

    let last = "";
    let inflight = 0;

    async function tick() {
      let id = null;
      try { id = extract(); } catch (e) { id = null; }
      const key = id ? keyOf(id) : "";
      if (!key) {
        if (last) { last = ""; HaliaPanel.setClient(null); }
        return;
      }
      if (key === last) return;
      last = key;
      const mine = ++inflight;
      const label = (id.name || id.email || "this client");
      HaliaPanel.setClient({ loading: true, name: label });
      const resp = await lookup(id);
      if (mine !== inflight || last !== key) return; // a newer client took over
      if (resp && resp.error) {
        HaliaPanel.setClient(friendly[resp.error] ? { error: friendly[resp.error] } : null);
        return;
      }
      if (!resp || !resp.found) { HaliaPanel.setClient({ notfound: true, name: label }); return; }
      HaliaPanel.setClient({ found: true, data: resp });
    }

    const debounced = (() => {
      let t = null;
      return () => { clearTimeout(t); t = setTimeout(tick, 400); };
    })();

    let lastUrl = location.href;
    const onNav = () => { if (location.href !== lastUrl) { lastUrl = location.href; debounced(); } };
    ["pushState", "replaceState"].forEach((m) => {
      const orig = history[m];
      history[m] = function () { const r = orig.apply(this, arguments); onNav(); return r; };
    });
    window.addEventListener("popstate", onNav);
    setInterval(onNav, 1200);

    const mo = new MutationObserver(debounced);
    mo.observe(document.documentElement, { childList: true, subtree: true });

    debounced();
  }

  // Insert text into a composer, preserving line breaks. Plain execCommand("insertText") with "\n"
  // collapses newlines in contenteditable editors (WhatsApp, Gmail, Slack), so split on newlines and
  // emit a real line break between lines. Textareas (Instagram) keep "\n" natively.
  function insertInto(el, text) {
    if (!el || !text) return false;
    el.focus();
    const t = String(text);
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const proto = el.tagName === "TEXTAREA"
        ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, (el.value || "") + t);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    }
    const lines = t.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      if (i > 0) document.execCommand("insertLineBreak");
      if (lines[i]) document.execCommand("insertText", false, lines[i]);
    }
    return true;
  }

  window.Halia = { observe, lookup, insertInto };
})();
