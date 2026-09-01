// The Halia desk inside Outlook. Same idea as the Messages desk, with one real advantage: an email
// add-in is told who the message is addressed to, so the client is identified without anyone typing
// a name.
//
// Served from the same origin as the API, so every call below is same-origin and needs no CORS
// grant. Template shaping comes from window.HaliaShape (/static/halia-shape.js), the one copy every
// Halia surface shares.
(function () {
  "use strict";

  var BASE = "";                       // same origin as this page
  var KEY = "halia_seat";
  var token = "";
  var client = null;                   // {name, cid, email, phone, suggested, cart}
  var templates = [];
  var products = [], viewIds = [], chosen = {};
  var el = function (id) { return document.getElementById(id); };

  // ── transport ─────────────────────────────────────────────────────────────
  function api(path, opts) {
    opts = opts || {};
    var init = { method: opts.method || "GET", headers: { "X-Halia-Ext-Token": token } };
    if (opts.body) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(BASE + path, init).then(function (r) {
      return r.text().then(function (t) {
        var d = {};
        try { d = t ? JSON.parse(t) : {}; } catch (e) { d = {}; }
        if (r.status === 401) throw new Error("Sign-in not recognised. Ask for a new one.");
        if (r.status === 402) throw new Error("This store needs a plan for the add-in.");
        if (!r.ok) throw new Error((d && d.detail) || ("Halia returned " + r.status));
        return d;
      });
    });
  }

  function say(id, text, bad) {
    var n = el(id); if (!n) return;
    n.textContent = text || "";
    n.className = bad ? "err" : "note";
  }

  // ── the mailbox ───────────────────────────────────────────────────────────
  // In compose we want who it is going TO; reading an email, who it came FROM.
  function recipient() {
    return new Promise(function (resolve) {
      var item = Office.context.mailbox.item;
      if (!item) return resolve(null);
      if (item.to && item.to.getAsync) {
        item.to.getAsync(function (res) {
          var list = (res && res.value) || [];
          resolve(list.length ? { email: list[0].emailAddress, name: list[0].displayName } : null);
        });
        return;
      }
      var f = item.from || item.sender;
      resolve(f ? { email: f.emailAddress, name: f.displayName } : null);
    });
  }

  // Put text where the cursor is. Match the message's own format, or HTML tags arrive as tags.
  function insert(text, html) {
    var item = Office.context.mailbox.item;
    if (!item || !item.body || !item.body.setSelectedDataAsync) {
      return Promise.reject(new Error("Open a reply first."));
    }
    return new Promise(function (resolve, reject) {
      item.body.getTypeAsync(function (t) {
        var isHtml = t && t.value === Office.CoercionType.Html;
        var payload = isHtml ? (html || String(text).replace(/\n/g, "<br>")) : text;
        item.body.setSelectedDataAsync(
          payload, { coercionType: isHtml ? Office.CoercionType.Html : Office.CoercionType.Text },
          function (res) {
            if (res && res.status === Office.AsyncResultStatus.Failed) {
              reject(new Error((res.error && res.error.message) || "Could not add that."));
            } else { resolve(); }
          });
      });
    });
  }

  // ── who this is for ───────────────────────────────────────────────────────
  function identify() {
    return recipient().then(function (to) {
      if (!to || !to.email) {
        el("who").textContent = "No recipient yet";
        say("whoNote", "Address the message, then reopen Halia.");
        return null;
      }
      el("who").textContent = to.name || to.email;
      say("whoNote", "Looking them up…");
      return api("/v1/extension/lookup", { method: "POST", body: { email: to.email } })
        .then(function (d) {
          client = { name: d.name || to.name || "", cid: d.cid || null, email: to.email,
                     phone: d.phone || "", suggested: d.suggested || [],
                     cart: (d.cart && d.cart.count) || 0 };
          el("who").textContent = client.name || to.email;
          // Deliberately no grade: an inbox is forwarded and screen-shared far more than a chat.
          say("whoNote", d.found
            ? (client.cart ? client.cart + " in an open basket" : "In your book")
            : "Not in the book yet. You can still write to them.");
          renderTemplates();
          return client;
        })
        .catch(function (e) { say("whoNote", e.message, true); return null; });
    });
  }

  function firstName() {
    return client && client.name ? String(client.name).split(" ")[0] : "";
  }

  // ── templates ─────────────────────────────────────────────────────────────
  function loadContext() {
    return api("/v1/extension/context").then(function (d) {
      templates = d.templates || [];
      var cats = [], seen = {};
      templates.forEach(function (t) {
        if (t.category && !seen[t.category]) { seen[t.category] = 1; cats.push(t.category); }
      });
      cats.sort();
      el("cat").innerHTML = '<option value="">All</option>' +
        cats.map(function (c) { return '<option>' + esc(c) + '</option>'; }).join("");
      renderTemplates();
    });
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function shaped(t) {
    return window.HaliaShape.shape(t.body || t.subject || "", firstName(),
                                   el("greeting").checked, el("signoff").checked);
  }

  function renderTemplates() {
    var cat = el("cat").value;
    var wanted = (client && client.suggested) || [];
    var list = templates.filter(function (t) { return !cat || t.category === cat; });
    if (!cat && wanted.length) {                       // what Halia ranked for them, first
      var top = list.filter(function (t) { return wanted.indexOf(t.name) >= 0; });
      var rest = list.filter(function (t) { return wanted.indexOf(t.name) < 0; });
      list = top.concat(rest);
    }
    el("tplList").innerHTML = list.length ? list.map(function (t, i) {
      return '<div class="item" data-tpl="' + i + '"><span><b>' + esc(t.name) + '</b>' +
             '<span class="sub">' + esc(shaped(t).replace(/\n+/g, " ").slice(0, 90)) + '</span></span></div>';
    }).join("") : '<div class="item"><span class="sub">No templates synced yet.</span></div>';
    Array.prototype.forEach.call(el("tplList").querySelectorAll("[data-tpl]"), function (row) {
      row.onclick = function () {
        var t = list[+row.dataset.tpl];
        insert(shaped(t)).catch(function (e) { say("whoNote", e.message, true); });
      };
    });
  }

  // ── draft ─────────────────────────────────────────────────────────────────
  var ANGLES = [["Warm hello", "a warm hello, nothing to sell"],
                ["New in", "tell them what has just come in"],
                ["Their size", "something in their size is back"],
                ["Invite in", "invite them in to see it"],
                ["Follow up", "follow up on our last conversation"]];

  function renderAngles() {
    el("angles").innerHTML = ANGLES.map(function (a, i) {
      return '<button data-angle="' + i + '">' + esc(a[0]) + '</button>';
    }).join("");
    Array.prototype.forEach.call(el("angles").querySelectorAll("[data-angle]"), function (b) {
      b.onclick = function () { el("ask").value = ANGLES[+b.dataset.angle][1]; write(); };
    });
  }

  function write() {
    var ask = el("ask").value.trim();
    if (!ask) { say("draftMsg", "Say what to write, or pick an angle.", true); return; }
    if (!client || !client.email) { say("draftMsg", "Address the message first.", true); return; }
    say("draftMsg", "Writing…");
    api("/v1/extension/draft", { method: "POST",
        body: { email: client.email, channel: "email", instruction: ask } })
      .then(function (d) {
        el("draftText").value = d.draft || "";
        say("draftMsg", d.draft ? "" : "Nothing came back. Try saying it another way.");
      })
      .catch(function (e) { say("draftMsg", e.message, true); });
  }

  // ── pieces ────────────────────────────────────────────────────────────────
  function search() {
    var q = encodeURIComponent(el("q").value.trim());
    var c = encodeURIComponent(el("fcol").value), s = encodeURIComponent(el("fsize").value);
    say("piecesMsg", "Looking…");
    api("/v1/extension/products?limit=40&q=" + q + "&collection=" + c + "&size=" + s)
      .then(function (d) {
        products = d.products || []; viewIds = d.ids || []; chosen = {};
        var f = d.facets || {};
        fillFacet("fcol", f.collections, "All collections", el("fcol").value);
        fillFacet("fsize", f.sizes, "All sizes", el("fsize").value);
        el("prodList").innerHTML = products.length ? products.map(function (p, i) {
          return '<div class="item" data-p="' + i + '"><input type="checkbox" data-cb="' + i +
                 '"><span><b>' + esc(p.title) + '</b></span></div>';
        }).join("") : '<div class="item"><span class="sub">Nothing in this view.</span></div>';
        Array.prototype.forEach.call(el("prodList").querySelectorAll("[data-cb]"), function (cb) {
          cb.onchange = function () {
            chosen[products[+cb.dataset.cb].id] = cb.checked;
            if (!cb.checked) delete chosen[products[+cb.dataset.cb].id];
            count();
          };
        });
        say("piecesMsg", ""); count();
      })
      .catch(function (e) { say("piecesMsg", e.message, true); });
  }

  function fillFacet(id, values, any, keep) {
    if (!values || !values.length) return;
    el(id).innerHTML = '<option value="">' + any + "</option>" +
      values.map(function (v) {
        return '<option' + (v === keep ? " selected" : "") + ">" + esc(v) + "</option>";
      }).join("");
  }

  function picked() { return Object.keys(chosen); }
  function count() { el("sendSel").textContent = "Add selection (" + picked().length + ")"; }

  function sendSelection() {
    var ids = picked();
    if (!ids.length) { say("piecesMsg", "Tick something first.", true); return; }
    say("piecesMsg", "Building…");
    api("/v1/extension/catalogue", { method: "POST",
        body: { product_ids: ids, name: (client && client.name) || "",
                email: (client && client.email) || "", phone: (client && client.phone) || "" } })
      .then(function (d) {
        // Email does not unfurl a preview card the way a chat does, so the link goes in as a
        // sentence with a real anchor rather than a bare URL hoping to become a card.
        var line = "I have put a few pieces aside for you to look through";
        return insert(line + ": " + d.url,
                      line + ': <a href="' + esc(d.url) + '">have a look</a>.');
      })
      .then(function () { say("piecesMsg", "Added."); })
      .catch(function (e) { say("piecesMsg", e.message, true); });
  }

  // ── book ──────────────────────────────────────────────────────────────────
  function book() {
    if (!client || !client.cid) { say("bookMsg", "They need to be in your book first.", true); return; }
    var when = el("when").value;
    if (!when) { say("bookMsg", "Pick a date and time.", true); return; }
    say("bookMsg", "Booking…");
    api("/v1/extension/action", { method: "POST",
        body: { action: "appointment", cid: client.cid, when: new Date(when).toISOString(),
                minutes: +el("mins").value, place: el("place").value.trim(),
                client_name: client.name, client_email: client.email } })
      .then(function (d) {
        var msg = (d.links && d.links.message) || "";
        if (!msg) { say("bookMsg", "Booked, but the invitation did not come back."); return; }
        return insert(msg).then(function () { say("bookMsg", "Booked, and their invitation is in."); });
      })
      .catch(function (e) { say("bookMsg", e.message, true); });
  }

  // ── wiring ────────────────────────────────────────────────────────────────
  function showDesk(on) {
    el("connect").className = on ? "card hide" : "card";
    el("desk").className = on ? "" : "hide";
  }

  function start() {
    showDesk(true);
    renderAngles();
    var d = new Date(Date.now() + 3600000); d.setMinutes(0, 0, 0);
    el("when").value = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 16);
    loadContext().catch(function (e) { say("whoNote", e.message, true); });
    identify();
    search();
  }

  function connect() {
    var t = el("tok").value.trim();
    if (!t) return;
    token = t;
    say("connectMsg", "Checking…");
    api("/v1/extension/profile")
      .then(function () {
        try { localStorage.setItem(KEY, t); } catch (e) { /* private mode: this session only */ }
        say("connectMsg", "");
        start();
      })
      .catch(function (e) { token = ""; say("connectMsg", e.message, true); });
  }

  Office.onReady(function () {
    el("connectGo").onclick = connect;
    el("tok").onkeydown = function (e) { if (e.key === "Enter") connect(); };
    el("signout").onclick = function () {
      try { localStorage.removeItem(KEY); } catch (e) { /* nothing to clear */ }
      token = ""; showDesk(false);
    };
    Array.prototype.forEach.call(document.querySelectorAll("[data-tab]"), function (b) {
      b.onclick = function () {
        Array.prototype.forEach.call(document.querySelectorAll("[data-tab]"), function (o) {
          o.setAttribute("aria-selected", String(o === b));
        });
        Array.prototype.forEach.call(document.querySelectorAll("[data-panel]"), function (p) {
          p.className = "card" + (p.dataset.panel === b.dataset.tab ? "" : " hide");
        });
      };
    });
    el("cat").onchange = renderTemplates;
    el("greeting").onchange = renderTemplates;
    el("signoff").onchange = renderTemplates;
    el("write").onclick = write;
    el("ask").onkeydown = function (e) { if (e.key === "Enter") write(); };
    el("insertDraft").onclick = function () {
      insert(el("draftText").value)
        .then(function () { say("draftMsg", "Added."); })
        .catch(function (e) { say("draftMsg", e.message, true); });
    };
    el("search").onclick = search;
    el("q").onkeydown = function (e) { if (e.key === "Enter") search(); };
    el("fcol").onchange = search;
    el("fsize").onchange = search;
    el("all").onclick = function () {
      var on = picked().length !== viewIds.length;
      chosen = {};
      if (on) viewIds.forEach(function (id) { chosen[id] = true; });
      Array.prototype.forEach.call(el("prodList").querySelectorAll("[data-cb]"), function (cb) {
        cb.checked = !!chosen[products[+cb.dataset.cb].id];
      });
      count();
    };
    el("sendSel").onclick = sendSelection;
    el("bookGo").onclick = book;
    el("logged").onclick = function () {
      if (!client || !client.cid) { say("logMsg", "They are not in your book.", true); return; }
      api("/v1/extension/action", { method: "POST",
          body: { action: "contacted", cid: client.cid, client_name: client.name,
                  reason: "Emailed via Halia" } })
        .then(function () { say("logMsg", "Logged."); })
        .catch(function (e) { say("logMsg", e.message, true); });
    };

    try { token = localStorage.getItem(KEY) || ""; } catch (e) { token = ""; }
    if (token) { start(); } else { showDesk(false); }
  });
})();
