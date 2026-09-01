// The on-send auto-log. When a message to someone in the book is sent, the contact lands on their
// record with no tap; the server logs at most once per client per day, so a back-and-forth thread
// does not flood the record.
//
// This file runs in Outlook's event runtime, which on classic Windows is JavaScript with no page
// around it, so it must stand alone: no DOM, no other scripts, nothing assumed. Two rules are
// absolute here. The handler must ALWAYS call event.completed with allowEvent true, whatever
// happens, because nothing Halia does is ever a reason to hold up someone's mail. And it must be
// quick, or Outlook shows the user a "taking longer than expected" dialog: one bounded request,
// then done.
(function () {
  "use strict";

  var KEY = "halia_seat";

  // The sign-in is written to roaming settings when the associate signs in on the pane, because
  // the classic-Windows event runtime has no localStorage. localStorage is the fallback for the
  // browser-based hosts. No sign-in means no log, never an error.
  function token() {
    try {
      var t = Office.context.roamingSettings.get(KEY);
      if (t) return String(t);
    } catch (e) { /* no roaming settings in this runtime */ }
    try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; }
  }

  function recipients(item, cb) {
    var out = [], waiting = 0, fired = false;
    function done() { if (!fired) { fired = true; cb(out); } }
    ["to", "cc"].forEach(function (field) {
      if (item[field] && item[field].getAsync) {
        waiting++;
        item[field].getAsync(function (res) {
          ((res && res.value) || []).forEach(function (r) {
            if (r && r.emailAddress) out.push(r.emailAddress);
          });
          if (--waiting === 0) done();
        });
      }
    });
    if (!waiting) done();
    setTimeout(done, 1500);                        // never wait on a stuck getAsync
  }

  function haliaOnSend(event) {
    var finish = function () {
      try { event.completed({ allowEvent: true }); } catch (e) { /* already completed */ }
    };
    try {
      var t = token();
      var item = Office.context.mailbox.item;
      if (!t || !item) return finish();
      recipients(item, function (emails) {
        if (!emails.length) return finish();
        var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
        var timer = setTimeout(function () {
          if (ctrl) ctrl.abort();
          finish();                                // the mail matters more than the log
        }, 2000);
        fetch("__BASE__/v1/extension/emailed", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Halia-Ext-Token": t },
          body: JSON.stringify({ emails: emails.slice(0, 5) }),
          signal: ctrl ? ctrl.signal : undefined
        }).then(function () { clearTimeout(timer); finish(); },
                function () { clearTimeout(timer); finish(); });
      });
    } catch (e) {
      finish();
    }
  }

  if (typeof Office !== "undefined" && Office.actions && Office.actions.associate) {
    Office.actions.associate("haliaOnSend", haliaOnSend);
  }
  // Classic Outlook on Windows looks the handler up as a global.
  if (typeof window !== "undefined") window.haliaOnSend = haliaOnSend;
})();
