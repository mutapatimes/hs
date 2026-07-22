// Halia Concierge in Gorgias. When an agent opens a ticket, recognise the customer by their email
// so support knows at a glance whether it is an A* client, and can reply in the right register.
// Matched by the ticket's customer email. Nothing is stored.

(function () {
  function extract() {
    // Scope to the customer / contact panel where Gorgias shows the requester, then fall back to
    // the whole ticket view. mailto-first inside the scope keeps us on the customer, not the agent.
    const scope = document.querySelector(
      '[class*="customer" i], [class*="contact" i], [class*="Sidebar" i], [class*="ticket" i]') || document;
    const email = Halia.pageEmail(scope);
    return email && email.indexOf("@") >= 0 ? { email } : null;
  }

  function insert(text) {
    const box = document.querySelector(
      '[data-testid*="editor" i] [contenteditable="true"], .public-DraftEditor-content, ' +
      'div[role="textbox"][contenteditable="true"], textarea');
    return Halia.insertInto(box, text);
  }

  // The ticket's recent messages, so the brief answers the actual complaint rather than the
  // client's grade alone. Agent replies carry an outgoing/agent hint in their markup; everything
  // else is treated as the customer. Read live; nothing is stored.
  function readThread() {
    const scope = document.querySelector('[class*="ticket" i], [class*="conversation" i], main') ||
      document;
    return Halia.readMessages(scope, '[class*="message" i], [class*="MessageBody" i]',
      /outgoing|agent|sent-by-us|from-agent|internal/i, 6);
  }

  HaliaPanel.setChannel("email");
  HaliaPanel.setInserter(insert);
  HaliaPanel.setThreadReader(readThread);
  Halia.observe(extract);
})();
