// Exercise Halia.readMessages (extension/content/core.js) against jsdom fixtures shaped like the
// helpdesk and DM markup it has to survive. Prints one JSON line and exits 0.
// Used by tests/test_extension_js.py. The identity matchers on those surfaces are best-effort
// against obfuscated DOMs, so the piece worth testing is the reader's own logic: collapsing nested
// matches to the innermost node, attributing each side, and skipping empty nodes.
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const core = fs.readFileSync(
  path.join(__dirname, "..", "..", "extension", "content", "core.js"), "utf8");

const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only" });
const w = dom.window;
w.chrome = { runtime: { sendMessage: () => {}, lastError: null } };
w.HaliaPanel = { mount: () => {}, setClient: () => {}, setContext: () => {} };
w.eval(core);
const read = w.Halia.readMessages;

const results = {};
const set = (html) => { w.document.body.innerHTML = html; return w.document.body; };

// 1. Nested matches collapse to the innermost node — a loose [class*="message"] selector must not
//    return the outer wrapper's concatenated text as well as each message.
results.nested = read(
  set(`<div class="message-list">
         <div class="message-row"><div class="message-body">Is the coat back?</div></div>
         <div class="message-row outgoing"><div class="message-body">Let me check.</div></div>
       </div>`),
  '[class*="message" i]', /outgoing/i, 6);

// 2. Side attribution reads class, aria-label and test ids; unknown defaults to the client.
results.sides = read(
  set(`<div role="row" aria-label="You sent a message">Thanks, ordered.</div>
       <div role="row">Do you have it in a 38?</div>
       <div role="row" data-test-id="agent-comment">We do, holding one for you.</div>`),
  'div[role="row"]', /you sent|agent/i, 6);

// 3. Empty and whitespace-only nodes are dropped; the tail is kept when over the limit.
results.limit = read(
  set(`<p class="c">one</p><p class="c">   </p><p class="c">two</p>
       <p class="c">three</p><p class="c"></p><p class="c">four</p>`),
  ".c", null, 2);

// 4. No matches is an empty list, never a throw.
results.none = read(set("<div>nothing here</div>"), ".missing", null, 6);

console.log(JSON.stringify(results));
