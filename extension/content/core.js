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

  // Insert text into a composer, preserving line breaks. execCommand("insertText") collapses "\n"
  // and Lexical editors (WhatsApp) ignore insertLineBreak, so for contenteditable we dispatch a
  // synthetic paste: the editor's own paste handler inserts the text with its line breaks intact.
  // Textareas (Instagram) keep "\n" natively via the value setter.
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
    try {
      const dt = new DataTransfer();
      dt.setData("text/plain", t);
      el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
      return true;
    } catch (e) {
      // Older engines: line-by-line with a real line break between paragraphs.
      const lines = t.split(/\r?\n/);
      for (let i = 0; i < lines.length; i++) {
        if (i > 0) document.execCommand("insertLineBreak");
        if (lines[i]) document.execCommand("insertText", false, lines[i]);
      }
      return true;
    }
  }

  // Find the customer's email within a scope (a helpdesk ticket panel, a profile header). Prefers a
  // mailto link (the reliable signal), then the first email-looking string. Scope tightly to avoid
  // grabbing an agent's own address or a footer.
  function pageEmail(scope) {
    const r = scope || document;
    const a = r.querySelector('a[href^="mailto:"]');
    if (a) return decodeURIComponent((a.getAttribute("href") || "").slice(7).split("?")[0]).trim();
    const m = (r.textContent || "").match(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/i);
    return m ? m[0].toLowerCase() : "";
  }

  // Read a best-effort message list out of a thread, for the brief. Each node matching `sel`
  // becomes one message; a node is attributed to "me" when `mine` matches its class / aria-label /
  // test id, and to the client otherwise (the safer default, since the client's words are what a
  // reply has to answer). Nested matches are collapsed to the innermost node, so a loose selector
  // like [class*="message"] doesn't return the same text several times over.
  function readMessages(root, sel, mine, limit) {
    const stop = root || document;
    // The text lives on the innermost node, but the which-side hint is usually on an ancestor
    // (the message row), so read the hint from the node plus a few levels up.
    function hintOf(n) {
      let h = "", cur = n;
      for (let i = 0; i < 4 && cur && cur !== stop; i++, cur = cur.parentElement) {
        h += " " + String(cur.className || "") + " " + (cur.getAttribute("aria-label") || "") +
          " " + (cur.getAttribute("data-test-id") || "") + " " + (cur.getAttribute("data-testid") || "");
      }
      return h;
    }
    const all = Array.prototype.slice.call(stop.querySelectorAll(sel)).slice(-60);
    const leaves = all.filter((n) => !all.some((o) => o !== n && n.contains(o)));
    const out = [];
    leaves.forEach((n) => {
      const text = (n.innerText || n.textContent || "").trim();
      if (!text) return;
      out.push({ from: mine && mine.test(hintOf(n)) ? "me" : "them", text: text.slice(0, 1200) });
    });
    return out.slice(-(limit || 6));
  }

  window.Halia = { observe, lookup, insertInto, pageEmail, readMessages };
})();
