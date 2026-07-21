// Halia Concierge in Microsoft Teams. Teams is an internal team surface, so the toolbar opens in
// Internal mode by default (team to-dos + premade messages to paste into a channel). No per-client
// lookup runs; the message-insert drops text into the Teams composer.

(function () {
  function insert(text) {
    const box = document.querySelector(
      'div[contenteditable="true"][role="textbox"], .ck-editor__editable[contenteditable="true"], ' +
      'div[data-tid="ckeditor"] [contenteditable="true"]');
    return Halia.insertInto(box, text);
  }

  HaliaPanel.mount();
  HaliaPanel.setChannel("admin");
  HaliaPanel.setInserter(insert);
  HaliaPanel.setMode("internal", false);
  Halia.observe(() => null);
})();
