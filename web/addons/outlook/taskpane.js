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
  function isAppointment() {
    var item = Office.context.mailbox.item;
    try {
      return !!item && item.itemType === Office.MailboxEnums.ItemType.Appointment;
    } catch (e) { return false; }
  }

  function firstOf(list) {
    return (list && list.length)
      ? { email: list[0].emailAddress, name: list[0].displayName } : null;
  }

  function recipient() {
    return new Promise(function (resolve) {
      var item = Office.context.mailbox.item;
      if (!item) return resolve(null);
      // A meeting being organised: the client is the attendee. Reading one: the organiser.
      if (item.requiredAttendees && item.requiredAttendees.getAsync) {
        item.requiredAttendees.getAsync(function (res) { resolve(firstOf(res && res.value)); });
        return;
      }
      if (item.requiredAttendees && item.requiredAttendees.length) {
        return resolve(firstOf(item.requiredAttendees));
      }
      // Compose hands back a Recipients object with getAsync, and the client is who it is going
      // to. Reading a message, `to` is a plain array and it is US, so the client is the sender.
      if (item.to && item.to.getAsync) {
        item.to.getAsync(function (res) { resolve(firstOf(res && res.value)); });
        return;
      }
      var f = item.organizer || item.from || item.sender;
      if (f) return resolve({ email: f.emailAddress, name: f.displayName });
      if (item.to && item.to.length) return resolve(firstOf(item.to));
      resolve(null);
    });
  }

  // ── the appointment window ────────────────────────────────────────────────
  // A visit is as often agreed in the calendar as in an email. When Halia is opened on a meeting
  // rather than a message it fills the meeting in and writes it to the client's record, so the
  // calendar-first path lands in the book like any other booking.
  function apptField(field) {
    return new Promise(function (resolve) {
      if (!field || !field.getAsync) return resolve(null);
      field.getAsync(function (r) { resolve(r && r.value); });
    });
  }

  function fillMeeting() {
    var item = Office.context.mailbox.item;
    if (!item) return;
    var name = (client && client.name) || "";
    var title = name ? "Appointment with " + name : "Appointment";
    try {
      if (item.subject && item.subject.setAsync) item.subject.setAsync(title);
      if (item.location && item.location.setAsync && el("place").value.trim()) {
        item.location.setAsync(el("place").value.trim());
      }
      say("apptMsg", "Filled in. Add anything else, then send it.");
    } catch (e) {
      say("apptMsg", "Could not fill that in.", true);
    }
  }

  function saveMeeting() {
    var item = Office.context.mailbox.item;
    if (!client || !client.cid) { say("apptMsg", "They need to be in your book first.", true); return; }
    say("apptMsg", "Saving…");
    Promise.all([apptField(item.start), apptField(item.end), apptField(item.location)])
      .then(function (v) {
        var start = v[0] ? new Date(v[0]) : null;
        if (!start) throw new Error("This meeting has no time yet.");
        var mins = v[1] ? Math.round((new Date(v[1]) - start) / 60000) : 45;
        return api("/v1/extension/action", { method: "POST",
          body: { action: "appointment", cid: client.cid, when: start.toISOString(),
                  minutes: mins > 0 ? mins : 45, place: v[2] || "",
                  client_name: client.name, client_email: client.email } });
      })
      .then(function () { say("apptMsg", "On their record."); })
      .catch(function (e) { say("apptMsg", e.message, true); });
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
          var g = el("grade");
          g.textContent = d.grade || "";
          g.className = d.grade ? "grade" : "grade hide";
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
  function count() { el("sendSel").textContent = "Send a selection (" + picked().length + ")"; }

  function sendBasket() {
    var ids = picked();
    if (!ids.length) { say("piecesMsg", "Tick something first.", true); return; }
    say("piecesMsg", "Building…");
    api("/v1/extension/cart_link", { method: "POST", body: { product_ids: ids } })
      .then(function (d) {
        var line = "I have put these aside in a basket for you";
        return insert(line + ": " + d.url,
                      line + ': <a href="' + esc(d.url) + '">check out here</a>.');
      })
      .then(function () { say("piecesMsg", "Added."); })
      .catch(function () { say("piecesMsg", "Nothing here has a buyable variant.", true); });
  }

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
  // Every other Halia surface can only hand the client a link to a page where they add the visit
  // to their own calendar, because nowhere else is Halia sitting in a calendar client. Here it is.
  // Outlook's own appointment window opens filled in, the client on it as an attendee, and the
  // associate presses Send: a real invitation, in both calendars, that Outlook then reschedules
  // and cancels natively.
  //
  // Halia books first, because displayNewAppointmentForm tells us nothing about whether the
  // associate actually sent it, so there is no later moment to record. If they close the window
  // the visit is still on the client's record, which is right — a time was agreed — and Cancel is
  // one tap. The status line says so rather than leaving it a surprise.
  var lastLinks = null;

  function inviteMeeting(links) {
    if (!Office.context.mailbox.displayNewAppointmentForm) {
      say("bookMsg", "Booked. Add the invitation to the message below.");
      return;
    }
    try {
      Office.context.mailbox.displayNewAppointmentForm({
        requiredAttendees: client && client.email ? [client.email] : [],
        start: new Date(links.start),
        end: new Date(links.end),
        subject: links.title,
        location: links.location || "",
        body: links.message || ""
      });
      say("bookMsg", "Booked. Send the invitation Outlook just opened, or close it and use the "
                     + "line below instead.");
    } catch (e) {
      say("bookMsg", "Booked. Add the invitation to the message below.");
    }
  }

  // Asked as the time changes, so a warning arrives while another time can still be picked.
  function checkTime() {
    var when = el("when").value;
    if (!when || !token) { say("bookWarn", ""); return; }
    var q = "?when=" + encodeURIComponent(new Date(when).toISOString())
          + "&minutes=" + (+el("mins").value || 45)
          + "&cid=" + encodeURIComponent((client && client.cid) || "");
    api("/v1/extension/check_time" + q)
      .then(function (d) {
        var bits = [];
        if (d.outside_hours) bits.push(d.outside_hours);
        (d.clash || []).forEach(function (c) {
          bits.push(c.why === "you"
            ? "You already have " + (c.name || "someone") + " then."
            : (c.name || "They") + " is already booked then.");
        });
        say("bookWarn", bits.join(" "));
      })
      .catch(function () { say("bookWarn", ""); });
  }

  function book() {
    if (!client || !client.cid) { say("bookMsg", "They need to be in your book first.", true); return; }
    var when = el("when").value;
    if (!when) { say("bookMsg", "Pick a date and time.", true); return; }
    say("bookMsg", "Booking…");
    api("/v1/extension/action", { method: "POST",
        body: { action: "appointment", cid: client.cid, when: new Date(when).toISOString(),
                minutes: +el("mins").value, place: el("bookPlace").value.trim(),
                client_name: client.name, client_email: client.email } })
      .then(function (d) {
        lastLinks = (d && d.links) || null;
        if (!lastLinks) { say("bookMsg", "Booked, but the invitation did not come back."); return; }
        el("bookSend").className = "";
        inviteMeeting(lastLinks);
      })
      .catch(function (e) { say("bookMsg", e.message, true); });
  }

  // ── wiring ────────────────────────────────────────────────────────────────
  function showDesk(on) {
    el("connect").className = on ? "card hide" : "card";
    var desk = el("desk");
    desk.className = on ? "" : "hide";
    desk.style.display = on ? "flex" : "none";
  }

  function start() {
    showDesk(true);
    if (isAppointment()) {
      el("tabs").className = "tabs hide";
      Array.prototype.forEach.call(document.querySelectorAll("[data-panel]"), function (p) {
        p.className = "card hide";
      });
      el("apptPanel").className = "card";
      el("fillMeeting").onclick = fillMeeting;
      el("saveMeeting").onclick = saveMeeting;
      loadContext().catch(function () { /* templates are not needed on a meeting */ });
      identify();
      return;
    }
    var d = new Date(Date.now() + 3600000); d.setMinutes(0, 0, 0);
    el("when").value = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 16);
    loadContext().catch(function (e) { say("whoNote", e.message, true); });
    identify();
    search();
  }

  function connect() {
    var t = el("tok").value.trim();
    var mail = el("mail").value.trim().toLowerCase();
    if (!t || !mail) { say("connectMsg", "Both, please.", true); return; }
    token = t;
    say("connectMsg", "Checking…");
    api("/v1/extension/profile")
      .then(function (d) {
        // The sign-in identifies the seat on its own; the address is checked against it so a
        // token pasted from someone else's message does not quietly sign you in as them.
        var mine = ((d.profile && d.profile.email) || "").toLowerCase();
        if (mine && mine !== mail) {
          throw new Error("That sign-in belongs to a different address.");
        }
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
    el("sendCart").onclick = sendBasket;
    el("bookGo").onclick = book;
    el("when").onchange = checkTime;
    el("mins").onchange = checkTime;
    el("bookSend").onclick = function () {
      if (!lastLinks || !lastLinks.message) return;
      insert(lastLinks.message)
        .then(function () { say("bookMsg", "Their invitation is in the message."); })
        .catch(function (e) { say("bookMsg", e.message, true); });
    };
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
