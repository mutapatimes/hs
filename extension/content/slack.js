// Halia toolbar on Slack. Slack is an internal team surface, so the toolbar opens in Internal mode
// by default (team to-dos + premade messages to paste into the channel). There is no "client" on a
// Slack page, so no per-conversation lookup runs; the message-insert drops text into the composer.

(function () {
  // Insert into Slack's message composer (a contenteditable rich-text box).
  function insert(text) {
    const box = document.querySelector(
      'div[data-qa="message_input"] div[contenteditable="true"], .ql-editor[contenteditable="true"], ' +
      'div[role="textbox"][contenteditable="true"]');
    if (!box || !text) return false;
    box.focus();
    return document.execCommand("insertText", false, text) !== false;
  }

  HaliaPanel.mount();
  HaliaPanel.setChannel("admin");        // links tagged as internal/referral, not a client channel
  HaliaPanel.setInserter(insert);
  HaliaPanel.setMode("internal", false); // default to team mode here without overwriting the stored pref

  // Load the standing context (to-dos, Slack status) without any client lookup.
  Halia.observe(() => null);
})();
