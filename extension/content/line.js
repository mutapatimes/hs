// Halia badge on LINE's Official Account web chat (chat.line.biz) — where Japanese boutique
// staff answer clients, the way UK staff sit in web.whatsapp.com.
//
// An honest limit, stated up front: LINE shows only the client's display name here. No phone, no
// email, and display names are often not real names, so identification is a name match against
// the book, or the copied-client flow when that misses. The LINE-identity capture planned for the
// Official Account integration is what makes this strong; until then the badge says who it THINKS
// this is and never pretends to be sure.
//
// Selectors are written defensively: the console is an SPA whose markup we cannot pin down from
// outside, so everything is queried at call time and a miss degrades to the panel with no client,
// never to an error.
(function () {
  // The chat header carries the client's display name. Try the ARIA-ish candidates first, then
  // the visible header text, and give up quietly.
  function headerName() {
    var el =
      document.querySelector('[data-testid="chatroom-header"] [data-testid="name"]') ||
      document.querySelector('[class*="chatroomHeader"] [class*="name"]') ||
      document.querySelector('header [class*="userName"], header [class*="displayName"]');
    if (el && el.textContent && el.textContent.trim()) return el.textContent.trim();
    // Fallback: the selected row in the chat list is highlighted; its name matches the open chat.
    var row = document.querySelector('[aria-selected="true"] [class*="name"], [class*="selected"] [class*="userName"]');
    return row && row.textContent ? row.textContent.trim() : "";
  }

  function extract() {
    var name = headerName();
    if (!name) return null;
    return { name: name };
  }

  // The reply box. LINE's console uses a textarea; some builds a contenteditable.
  function composer() {
    return (
      document.querySelector('textarea[name="message"], textarea[class*="input"], footer textarea') ||
      document.querySelector('[contenteditable="true"][class*="input"], footer [contenteditable="true"]')
    );
  }

  function insert(text) {
    return Halia.insertInto(composer(), text);
  }

  // Recent turns for the brief. Message bubbles sit in rows marked by side; read the innermost
  // text nodes and take the me/them hint from the row.
  function readThread() {
    var root = document.querySelector('[class*="messageList"], [class*="chatroomContent"], main');
    if (!root) return [];
    return Halia.readMessages(root,
      '[class*="messageText"], [class*="bubble"] [class*="text"], [class*="Message"] p',
      '[class*="right"], [class*="sent"], [class*="mine"], [class*="outgoing"]', 6);
  }

  HaliaPanel.setChannel("line");
  HaliaPanel.setInserter(insert);
  HaliaPanel.setThreadReader(readThread);
  Halia.observe(extract);
})();
