// Halia toolbar on Google Calendar. When an event is open, match a guest's email to a client and
// show their brief — grade, latent value, reasons, next move — so you walk into the appointment
// knowing exactly who they are. Matched by email (reliable). Nothing is stored.

(function () {
  function accountEmail() {
    const el = document.querySelector('a[aria-label*="@"], [aria-label*="Google Account"]');
    if (el) {
      const m = (el.getAttribute("aria-label") || "").match(/[\w.+-]+@[\w.-]+\.\w+/);
      if (m) return m[0].toLowerCase();
    }
    return "";
  }

  function extract() {
    // Only when an event's detail is open (a dialog), so we never grab a stray address.
    const dlg = document.querySelector('[role="dialog"]');
    if (!dlg) return null;
    let emails = Array.prototype.slice.call(dlg.querySelectorAll("[data-email]"))
      .map((e) => e.getAttribute("data-email"));
    if (!emails.length) emails = (dlg.textContent || "").match(/[\w.+-]+@[\w.-]+\.\w+/g) || [];
    const me = accountEmail();
    const other = emails.map((e) => (e || "").toLowerCase()).find((e) => e && e !== me);
    if (!other) return null;
    return { email: other };
  }

  HaliaPanel.setChannel("email");
  Halia.observe(extract);   // no composer on Calendar, so templates offer copy only
})();
