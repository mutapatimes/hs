// Halia Concierge in Zendesk (agent workspace). On an open ticket, recognise the requester by their
// email so support can prioritise and personalise for high-grade clients. Matched by email. Nothing
// is stored.

(function () {
  function extract() {
    if (!/\/agent\//.test(location.pathname)) return null;   // only in the agent workspace
    const scope = document.querySelector(
      '[data-test-id*="requester" i], [data-garden-id*="requester" i], [class*="requester" i], ' +
      '[class*="customer" i]') || document;
    const email = Halia.pageEmail(scope);
    return email && email.indexOf("@") >= 0 ? { email } : null;
  }

  function insert(text) {
    const box = document.querySelector(
      '[data-test-id*="editor" i] [contenteditable="true"], .zendesk-editor--rich-text-comment, ' +
      'div[role="textbox"][contenteditable="true"], textarea[name="comment"]');
    return Halia.insertInto(box, text);
  }

  HaliaPanel.setChannel("email");
  HaliaPanel.setInserter(insert);
  Halia.observe(extract);
})();
