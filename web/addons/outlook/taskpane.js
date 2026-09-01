// The Halia desk inside Outlook. Same idea as the Messages desk, with one real advantage: an email
// add-in is told who the message is addressed to, so the client is identified without anyone typing
// a name.
//
// Two modes, both first-class. Composing, actions land at the cursor. READING — where triage
// actually happens — every action opens a reply already written, via displayReplyForm; the pane can
// be pinned and re-identifies each message as the associate walks the inbox.
//
// Served from the same origin as the API, so every call below is same-origin and needs no CORS
// grant. Template shaping comes from window.HaliaShape (/static/halia-shape.js), the one copy every
// Halia surface shares.
(function () {
  "use strict";

  var BASE = "";                       // same origin as this page
  var KEY = "halia_seat";
  var token = "";
  var client = null;                   // {name, cid, email, phone, suggested, cart, ...standing}
  var templates = [];
  var products = [], viewIds = [], chosen = {};
  var lastLinks = null;                // the last booking's calendar links
  var moveId = null;                   // a visit being moved rather than newly booked
  var visits = [];                     // this client's upcoming appointments
  var openTpl = -1;                    // which template row is expanded
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

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function relday(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var days = Math.floor((new Date().setHours(0, 0, 0, 0) - d.getTime()) / 86400000) + 1;
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 7) return "on " + d.toLocaleDateString("en-GB", { weekday: "long" });
    return "on " + d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }

  // ── the mailbox ───────────────────────────────────────────────────────────
  function item() { return Office.context.mailbox.item; }

  function isAppointment() {
    try {
      return !!item() && item().itemType === Office.MailboxEnums.ItemType.Appointment;
    } catch (e) { return false; }
  }

  // Compose items carry a writable body; read items do not. This one test decides how every
  // action lands: at the cursor, or as a reply that opens already written.
  function isCompose() {
    var it = item();
    return !!(it && it.body && it.body.setSelectedDataAsync);
  }

  function firstOf(list) {
    return (list && list.length)
      ? { email: list[0].emailAddress, name: list[0].displayName } : null;
  }

  function recipient() {
    return new Promise(function (resolve) {
      var it = item();
      if (!it) return resolve(null);
      // A meeting being organised: the client is the attendee. Reading one: the organiser.
      if (it.requiredAttendees && it.requiredAttendees.getAsync) {
        it.requiredAttendees.getAsync(function (res) { resolve(firstOf(res && res.value)); });
        return;
      }
      if (it.requiredAttendees && it.requiredAttendees.length) {
        return resolve(firstOf(it.requiredAttendees));
      }
      // Compose hands back a Recipients object with getAsync, and the client is who it is going
      // to. Reading a message, `to` is a plain array and it is US, so the client is the sender.
      if (it.to && it.to.getAsync) {
        it.to.getAsync(function (res) { resolve(firstOf(res && res.value)); });
        return;
      }
      var f = it.organizer || it.from || it.sender;
      if (f) return resolve({ email: f.emailAddress, name: f.displayName });
      if (it.to && it.to.length) return resolve(firstOf(it.to));
      resolve(null);
    });
  }

  // Reading a message: the whole body as text, for the brief and for Remember this.
  function bodyText() {
    return new Promise(function (resolve, reject) {
      var it = item();
      if (!it || !it.body || !it.body.getAsync) return reject(new Error("No message open."));
      it.body.getAsync(Office.CoercionType.Text, function (res) {
        if (res && res.status === Office.AsyncResultStatus.Succeeded) resolve(res.value || "");
        else reject(new Error("Could not read the message."));
      });
    });
  }

  // The server reads a conversation as short turns, so a long email travels as consecutive
  // pieces rather than being cut off at the first one.
  function asThread(text) {
    var t = String(text || "").replace(/\r/g, "").trim().slice(0, 4500);
    var out = [];
    while (t && out.length < 6) {
      out.push({ from: "them", text: t.slice(0, 780) });
      t = t.slice(780);
    }
    return out;
  }

  // ── putting words in front of the client ──────────────────────────────────
  // Composing: at the cursor, matching the message's own format. Reading: a reply opens with the
  // words already in it, which is the point of being inside the mail client.
  function deliver(text, html) {
    var it = item();
    if (it && it.body && it.body.setSelectedDataAsync) {
      return new Promise(function (resolve, reject) {
        it.body.getTypeAsync(function (t) {
          var isHtml = t && t.value === Office.CoercionType.Html;
          var payload = isHtml ? (html || String(text).replace(/\n/g, "<br>")) : text;
          it.body.setSelectedDataAsync(
            payload, { coercionType: isHtml ? Office.CoercionType.Html : Office.CoercionType.Text },
            function (res) {
              if (res && res.status === Office.AsyncResultStatus.Failed) {
                reject(new Error((res.error && res.error.message) || "Could not add that."));
              } else { resolve("inserted"); }
            });
        });
      });
    }
    if (it && it.displayReplyForm) {
      try {
        it.displayReplyForm(html || esc(String(text)).replace(/\n/g, "<br>"));
        return Promise.resolve("replied");
      } catch (e) { /* fall through */ }
    }
    return Promise.reject(new Error("Open a message first."));
  }

  var insert = deliver;                // the old name, used throughout

  function verb() { return isCompose() ? "Put it in the message" : "Reply with this"; }

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
    var it = item();
    if (!it) return;
    var name = (client && client.name) || "";
    var title = name ? "Appointment with " + name : "Appointment";
    try {
      if (it.subject && it.subject.setAsync) it.subject.setAsync(title);
      if (it.location && it.location.setAsync && el("place").value.trim()) {
        it.location.setAsync(el("place").value.trim());
      }
      say("apptMsg", "Filled in. Add anything else, then send it.");
    } catch (e) {
      say("apptMsg", "Could not fill that in.", true);
    }
  }

  function saveMeeting() {
    var it = item();
    if (!client || !client.cid) { say("apptMsg", "They need to be in your book first.", true); return; }
    say("apptMsg", "Saving…");
    Promise.all([apptField(it.start), apptField(it.end), apptField(it.location)])
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

  // ── who this is for ───────────────────────────────────────────────────────
  function identify() {
    return recipient().then(function (to) {
      if (!to || !to.email) {
        el("who").textContent = isCompose() ? "No recipient yet" : "No message open";
        el("whoDetail").innerHTML = "";
        el("addBook").className = "hide";
        return null;
      }
      el("who").textContent = to.name || to.email;
      say("whoNote", "Looking them up…");
      return api("/v1/extension/lookup", { method: "POST", body: { email: to.email } })
        .then(function (d) {
          client = { name: d.name || to.name || "", cid: d.cid || null, email: to.email,
                     phone: d.phone || "", suggested: d.suggested || [],
                     cart: (d.cart && d.cart.count) || 0, cartUrl: (d.cart && d.cart.url) || "",
                     reasons: d.reasons || [], play: d.action || d.reco || "",
                     orders: d.orders || [], found: !!d.found };
          el("who").textContent = client.name || to.email;
          var g = el("grade");
          g.textContent = d.grade || "";
          g.className = d.grade ? "grade" : "grade hide";
          say("whoNote", client.found
            ? (client.cart ? client.cart + " in an open basket" : "In your book")
            : "Not in the book yet.");
          el("addBook").className = client.found ? "hide" : "";
          renderStanding();
          renderTemplates();
          if (client.cid) { loadHistory(); loadVisits(); } else { renderVisits(); }
          return client;
        })
        .catch(function (e) { say("whoNote", e.message, true); return null; });
    });
  }

  function firstName() {
    return client && client.name ? String(client.name).split(" ")[0] : "";
  }

  // The standing, in data rather than sentences: why they are graded as they are, the move worth
  // making, and what they last bought. Deliberately no latent value anywhere on this surface.
  function renderStanding() {
    var lines = [];
    if (client.reasons.length) lines.push(esc(client.reasons.slice(0, 2).join(" · ")));
    if (client.play) lines.push(esc(client.play));
    client.orders.slice(0, 2).forEach(function (o) {
      var when = o.date ? new Date(o.date).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "";
      var what = (o.titles || []).slice(0, 2).join(", ");
      if (when || what) lines.push('<span class="sub2">' + esc(when) + (what ? " · " + esc(what) : "") + "</span>");
    });
    el("whoDetail").innerHTML = lines.map(function (l) {
      return '<div class="note">' + l + "</div>";
    }).join("");
  }

  function loadHistory() {
    api("/v1/extension/history?cid=" + encodeURIComponent(client.cid))
      .then(function (d) {
        var lc = d.last_contact;
        if (!lc || !lc.at) return;
        var line = (lc.by || "Someone") + " wrote to them " + relday(lc.at) + ".";
        el("whoDetail").insertAdjacentHTML(
          "beforeend", '<div class="warn">' + esc(line) + "</div>");
      })
      .catch(function () { /* the card is still useful without it */ });
  }

  function loadVisits() {
    api("/v1/extension/appointments?days=90")
      .then(function (d) {
        visits = (d.appointments || []).filter(function (a) {
          return String(a.cid) === String(client.cid);
        });
        if (visits.length) {
          var w = new Date(visits[0].when);
          el("whoDetail").insertAdjacentHTML(
            "beforeend", '<div class="note">Visit booked ' +
            esc(w.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
                + ", " + w.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })) + "</div>");
        }
        renderVisits();
      })
      .catch(function () { visits = []; renderVisits(); });
  }

  // New enquiries arrive by email before they exist anywhere else. One tap puts the sender in
  // the book through the same capture path as the shop floor: dedupe, consent handling, scoring,
  // alerts, all already built.
  function addToBook() {
    if (!client || !client.email) return;
    var parts = String(client.name || "").trim().split(/\s+/);
    say("whoNote", "Adding…");
    api("/v1/capture", { method: "POST",
        body: { first_name: parts[0] || "", last_name: parts.slice(1).join(" "),
                email: client.email, channel: "outlook" } })
      .then(function () { return identify(); })
      .catch(function (e) { say("whoNote", e.message, true); });
  }

  // ── the brief: read what they wrote, answer it in one tap ─────────────────
  function brief() {
    say("briefMsg", "Reading…");
    el("briefOut").innerHTML = "";
    bodyText()
      .then(function (text) {
        return api("/v1/extension/brief", { method: "POST",
          body: { email: (client && client.email) || "", name: (client && client.name) || "",
                  channel: "email", thread: asThread(text) } });
      })
      .then(function (d) {
        say("briefMsg", "");
        var bits = [];
        if (d.summary) bits.push('<div class="note">' + esc(d.summary) + "</div>");
        (d.actions || []).forEach(function (a) {
          if (a && a.label) bits.push('<div class="note">· ' + esc(a.label) + "</div>");
        });
        if (d.reply) {
          bits.push('<div class="reply">' + esc(d.reply).replace(/\n/g, "<br>") + "</div>");
          if (d.english && d.english !== d.reply) {
            bits.push('<div class="note">In English: ' + esc(d.english) + "</div>");
          }
          bits.push('<button class="primary" id="briefReply">Open a reply</button>');
        }
        el("briefOut").innerHTML = bits.join("");
        var b = el("briefReply");
        if (b) b.onclick = function () {
          deliver(d.reply).catch(function (e) { say("briefMsg", e.message, true); });
        };
      })
      .catch(function (e) { say("briefMsg", e.message, true); });
  }

  // What they told us lands on their record: sizes, occasions, the things worth remembering.
  function rememberThis() {
    if (!client || !client.email) { say("briefMsg", "They need to be in your book first.", true); return; }
    say("briefMsg", "Reading…");
    bodyText()
      .then(function (text) {
        return api("/v1/extension/remember", { method: "POST",
          body: { email: client.email, cid: client.cid || "", text: String(text).slice(0, 4000) } });
      })
      .then(function (d) {
        say("briefMsg", d.summary ? "Saved: " + d.summary : "Nothing new to save.");
      })
      .catch(function (e) { say("briefMsg", e.message, true); });
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

  function shaped(t) {
    return window.HaliaShape.shape(t.body || t.subject || "", firstName(),
                                   el("greeting").checked, el("signoff").checked);
  }

  // A row expands to the full note before anything is sent: choosing a template should mean
  // reading it, not firing it blind into a client's email.
  function renderTemplates() {
    var cat = el("cat").value;
    var wanted = (client && client.suggested) || [];
    var list = templates.filter(function (t) { return !cat || t.category === cat; });
    var topCount = 0;
    if (!cat && wanted.length) {
      var top = list.filter(function (t) { return wanted.indexOf(t.name) >= 0; });
      var rest = list.filter(function (t) { return wanted.indexOf(t.name) < 0; });
      list = top.concat(rest);
      topCount = top.length;
    }
    var rows = [];
    list.forEach(function (t, i) {
      if (i === 0 && topCount) {
        rows.push('<div class="head">For ' + esc(firstName() || "this client") + "</div>");
      }
      if (i === topCount && topCount) rows.push('<div class="head">Everything</div>');
      var open = i === openTpl;
      rows.push('<div class="item' + (open ? " open" : "") + '" data-tpl="' + i + '"><span><b>'
        + esc(t.name) + "</b>"
        + (open
          ? '<span class="full">' + esc(shaped(t)).replace(/\n/g, "<br>") + "</span>"
            + '<button class="primary" data-use="' + i + '">' + esc(verb()) + "</button>"
          : '<span class="sub">' + esc(shaped(t).replace(/\n+/g, " ").slice(0, 90)) + "</span>")
        + "</span></div>");
    });
    el("tplList").innerHTML = rows.length ? rows.join("")
      : '<div class="item"><span class="sub">No templates synced yet.</span></div>';
    Array.prototype.forEach.call(el("tplList").querySelectorAll("[data-tpl]"), function (row) {
      row.onclick = function (e) {
        if (e.target && e.target.dataset && e.target.dataset.use !== undefined) return;
        var i = +row.dataset.tpl;
        openTpl = openTpl === i ? -1 : i;
        renderTemplates();
      };
    });
    Array.prototype.forEach.call(el("tplList").querySelectorAll("[data-use]"), function (b) {
      b.onclick = function () {
        var t = list[+b.dataset.use];
        deliver(shaped(t))
          .then(function (how) {
            if (how === "inserted") fillSubject(t);
          })
          .catch(function (e) { say("whoNote", e.message, true); });
      };
    });
  }

  // Templates carry subjects; an empty draft may as well take one.
  function fillSubject(t) {
    var it = item();
    if (!t.subject || !it || !it.subject || !it.subject.getAsync || !it.subject.setAsync) return;
    it.subject.getAsync(function (r) {
      if (r && r.status === Office.AsyncResultStatus.Succeeded && !String(r.value || "").trim()) {
        it.subject.setAsync(window.HaliaShape.fillName(t.subject, firstName()));
      }
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
          var price = p.variants && p.variants[0] && p.variants[0].price;
          return '<div class="item" data-p="' + i + '"><input type="checkbox" data-cb="' + i + '">'
            + (p.image ? '<img class="thumb" src="' + esc(p.image) + '" alt="">' : "")
            + "<span><b>" + esc(p.title) + "</b>"
            + (price ? '<span class="sub">£' + esc(price) + "</span>" : "")
            + "</span></div>";
        }).join("") : '<div class="item"><span class="sub">Nothing in this view.</span></div>';
        Array.prototype.forEach.call(el("prodList").querySelectorAll("[data-cb]"), function (cb) {
          cb.onchange = function () {
            chosen[products[+cb.dataset.cb].id] = cb.checked;
            if (!cb.checked) delete chosen[products[+cb.dataset.cb].id];
            count();
          };
        });
        el("all").textContent = viewIds.length ? "All " + viewIds.length : "All";
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
        return deliver(line + ": " + d.url,
                       line + ': <a href="' + esc(d.url) + '">check out here</a>.');
      })
      .then(function () { say("piecesMsg", "Done."); })
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
        return deliver(line + ": " + d.url,
                       line + ': <a href="' + esc(d.url) + '">have a look</a>.');
      })
      .then(function () { say("piecesMsg", "Done."); })
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
  function inviteMeeting(links) {
    if (!Office.context.mailbox.displayNewAppointmentForm) {
      say("bookMsg", "Booked. Use the button to send the line.");
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
                     + "line instead.");
    } catch (e) {
      say("bookMsg", "Booked. Use the button to send the line.");
    }
  }

  // What is already in the diary for this client, with the two things a diary needs: move it, or
  // let it go.
  function renderVisits() {
    var box = el("bookList"); if (!box) return;
    box.innerHTML = visits.map(function (a, i) {
      var w = new Date(a.when);
      return '<div class="item"><span class="grow"><b>'
        + esc(w.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
              + ", " + w.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })) + "</b>"
        + (a.place ? '<span class="sub">' + esc(a.place) + "</span>" : "")
        + '</span><button data-mv="' + i + '">Move</button>'
        + '<button data-cx="' + i + '">Cancel</button></div>';
    }).join("");
    Array.prototype.forEach.call(box.querySelectorAll("[data-mv]"), function (b) {
      b.onclick = function () {
        var a = visits[+b.dataset.mv];
        moveId = a.id;
        var w = new Date(a.when);
        el("when").value = new Date(w.getTime() - w.getTimezoneOffset() * 60000)
          .toISOString().slice(0, 16);
        el("mins").value = String(a.minutes || 45);
        el("bookPlace").value = a.place || "";
        el("bookGo").textContent = "Move the visit";
        say("bookMsg", "Pick the new time, then move it.");
      };
    });
    Array.prototype.forEach.call(box.querySelectorAll("[data-cx]"), function (b) {
      b.onclick = function () {
        var a = visits[+b.dataset.cx];
        api("/v1/extension/action", { method: "POST",
            body: { action: "appointment_cancel", cid: client.cid, id: a.id } })
          .then(function () { say("bookMsg", "Cancelled."); loadVisits(); })
          .catch(function (e) { say("bookMsg", e.message, true); });
      };
    });
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
          if (moveId && c.id === moveId) return;   // the visit being moved is not its own clash
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
    say("bookMsg", moveId ? "Moving…" : "Booking…");
    var body = { action: moveId ? "appointment_move" : "appointment",
                 cid: client.cid, when: new Date(when).toISOString(),
                 minutes: +el("mins").value, place: el("bookPlace").value.trim(),
                 client_name: client.name, client_email: client.email };
    if (moveId) body.id = moveId;
    api("/v1/extension/action", { method: "POST", body: body })
      .then(function (d) {
        var moved = !!moveId;
        moveId = null;
        el("bookGo").textContent = "Book and send the invitation";
        lastLinks = (d && d.links) || null;
        loadVisits();
        if (!lastLinks) { say("bookMsg", "Done, but the invitation did not come back."); return; }
        el("bookSend").className = "";
        if (moved) {
          // A move updates the entry the client already holds; the fresh line says the new time.
          say("bookMsg", "Moved. Send them the new invitation with the button.");
        } else {
          inviteMeeting(lastLinks);
        }
      })
      .catch(function (e) { say("bookMsg", e.message, true); });
  }

  // ── polish: the associate's own words, in the house voice ─────────────────
  function polish() {
    var it = item();
    if (!it || !it.getSelectedDataAsync) { say("logMsg", "Select some text first.", true); return; }
    it.getSelectedDataAsync(Office.CoercionType.Text, function (res) {
      var text = res && res.status === Office.AsyncResultStatus.Succeeded
        ? String(res.value && res.value.data !== undefined ? res.value.data : res.value || "").trim() : "";
      if (!text) { say("logMsg", "Select the sentences to polish first.", true); return; }
      say("logMsg", "Polishing…");
      api("/v1/extension/polish", { method: "POST",
          body: { text: text, email: (client && client.email) || "", channel: "email",
                  greeting: false, signoff: false } })
        .then(function (d) {
          if (!d.text) { say("logMsg", "Nothing to change."); return; }
          return deliver(d.text).then(function () { say("logMsg", "Polished."); });
        })
        .catch(function (e) { say("logMsg", e.message, true); });
    });
  }

  // ── wiring ────────────────────────────────────────────────────────────────
  function showDesk(on) {
    el("connect").className = on ? "card hide" : "card";
    var desk = el("desk");
    desk.className = on ? "" : "hide";
    desk.style.display = on ? "flex" : "none";
  }

  function resetForItem() {
    client = null; chosen = {}; lastLinks = null; moveId = null; visits = []; openTpl = -1;
    el("whoDetail").innerHTML = "";
    el("grade").className = "grade hide";
    el("briefOut").innerHTML = "";
    say("briefMsg", ""); say("bookMsg", ""); say("bookWarn", ""); say("logMsg", "");
    el("bookGo").textContent = "Book and send the invitation";
    start();
  }

  function watchItem() {
    // Pinned, the pane stays open while the associate walks the inbox; each message brings its
    // own client. Compose panes learn the recipient as it is typed. Both are feature-detected:
    // on a host without the event, the pane simply behaves as before.
    try {
      Office.context.mailbox.addHandlerAsync(Office.EventType.ItemChanged, resetForItem);
    } catch (e) { /* not offered here */ }
    try {
      var it = item();
      if (it && it.addHandlerAsync && isCompose()) {
        var t = null;
        it.addHandlerAsync(Office.EventType.RecipientsChanged, function () {
          clearTimeout(t); t = setTimeout(identify, 600);
        });
      }
    } catch (e) { /* not offered here */ }
  }

  function start() {
    showDesk(true);
    if (isAppointment()) {
      el("tabs").className = "tabs hide";
      el("briefCard").className = "hide";
      Array.prototype.forEach.call(document.querySelectorAll("[data-panel]"), function (p) {
        p.className = "card hide";
      });
      el("apptPanel").className = "card";
      el("fillMeeting").onclick = fillMeeting;
      el("saveMeeting").onclick = saveMeeting;
      identify();
      return;
    }
    el("apptPanel").className = "card hide";
    el("tabs").className = "tabs";
    var reading = !isCompose();
    el("briefCard").className = reading ? "card" : "card hide";
    el("polish").className = reading ? "hide" : "";
    el("bookSend").textContent = reading ? "Reply with the line instead" : "Put it in the message instead";
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
        // Roaming settings travel with the mailbox and are what the on-send auto-log reads,
        // because the classic-Windows event runtime has no localStorage.
        try {
          Office.context.roamingSettings.set(KEY, t);
          Office.context.roamingSettings.saveAsync(function () {});
        } catch (e) { /* not offered here */ }
        say("connectMsg", "");
        start();
        watchItem();
      })
      .catch(function (e) { token = ""; say("connectMsg", e.message, true); });
  }

  Office.onReady(function () {
    el("connectGo").onclick = connect;
    el("tok").onkeydown = function (e) { if (e.key === "Enter") connect(); };
    el("signout").onclick = function () {
      try { localStorage.removeItem(KEY); } catch (e) { /* nothing to clear */ }
      try {
        Office.context.roamingSettings.remove(KEY);
        Office.context.roamingSettings.saveAsync(function () {});
      } catch (e) { /* nothing to clear */ }
      token = ""; showDesk(false);
    };
    Array.prototype.forEach.call(document.querySelectorAll("[data-tab]"), function (b) {
      b.onclick = function () {
        Array.prototype.forEach.call(document.querySelectorAll("[data-tab]"), function (o) {
          o.setAttribute("aria-selected", String(o === b));
        });
        Array.prototype.forEach.call(document.querySelectorAll("[data-panel]"), function (p) {
          var on = p.dataset.panel === b.dataset.tab;
          p.className = "card" + (on && p.dataset.panel !== "book" ? " fill" : "") + (on ? "" : " hide");
        });
      };
    });
    el("cat").onchange = function () { openTpl = -1; renderTemplates(); };
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
      deliver(lastLinks.message)
        .then(function () { say("bookMsg", "Their invitation is on its way."); })
        .catch(function (e) { say("bookMsg", e.message, true); });
    };
    el("briefGo").onclick = brief;
    el("rememberGo").onclick = rememberThis;
    el("addBook").onclick = addToBook;
    el("polish").onclick = polish;
    el("logged").onclick = function () {
      if (!client || !client.cid) { say("logMsg", "They are not in your book.", true); return; }
      api("/v1/extension/action", { method: "POST",
          body: { action: "contacted", cid: client.cid, client_name: client.name,
                  reason: "Emailed via Halia" } })
        .then(function () { say("logMsg", "Logged."); })
        .catch(function (e) { say("logMsg", e.message, true); });
    };

    try { token = localStorage.getItem(KEY) || ""; } catch (e) { token = ""; }
    if (!token) {
      try { token = String(Office.context.roamingSettings.get(KEY) || ""); } catch (e) { /* none */ }
    }
    if (token) { start(); watchItem(); } else { showDesk(false); }
  });
})();
