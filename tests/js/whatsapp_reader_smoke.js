// Exercise the WhatsApp thread reader (extension/content/whatsapp.js) against jsdom fixtures shaped
// like WhatsApp Web's real chat markup. Prints one JSON line and exits 0. Used by
// tests/test_extension_js.py.
//
// WhatsApp churns its class names, so the reader anchors on div.copyable-text[data-pre-plain-text]
// (the wrapper WhatsApp's own copy uses, stable for years) and only falls back to .message-in/-out
// rows. This test proves the reader survives a page where the old direction classes are gone from
// the bubbles, which is what silently broke the brief on WhatsApp.
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const dir = path.join(__dirname, "..", "..", "extension");
const core = fs.readFileSync(path.join(dir, "content", "core.js"), "utf8");
const wa = fs.readFileSync(path.join(dir, "content", "whatsapp.js"), "utf8");

const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only" });
const w = dom.window;
w.chrome = { runtime: { sendMessage: () => {}, lastError: null } };
let reader = null;
w.HaliaPanel = {
  mount: () => {}, setClient: () => {}, setContext: () => {},
  setChannel: () => {}, setInserter: () => {}, setThreadReader: (fn) => { reader = fn; },
};
w.eval(core);        // defines window.Halia
w.eval(wa);          // registers the WhatsApp readThread via setThreadReader

const results = {};

// 1. The stable anchor: bubbles carry div.copyable-text[data-pre-plain-text]; direction is on the
//    .message-out row ancestor. The timestamp sits in a sibling, outside copyable-text, so it must
//    not leak into the message text.
w.document.body.innerHTML = `
  <div id="main">
    <div class="message-in _row">
      <div class="bubble">
        <div class="copyable-text" data-pre-plain-text="[10:01, 26/07/2026] Client: ">
          <div><span class="selectable-text copyable-text"><span>Is the trench back in a 38?</span></span></div>
        </div>
        <div class="meta"><span>10:01</span></div>
      </div>
    </div>
    <div class="message-out _row">
      <div class="bubble">
        <div class="copyable-text" data-pre-plain-text="[10:04, 26/07/2026] Me: ">
          <div><span class="selectable-text copyable-text"><span>Let me hold one for you.</span></span></div>
        </div>
        <div class="meta"><span>10:04 ✓✓</span></div>
      </div>
    </div>
  </div>`;
results.stable = reader();

// 2. Class churn: the .message-in/-out classes are gone from every node, only the copyable-text
//    anchor remains. The reader must still read the text (direction degrades to "them", never empty).
w.document.body.innerHTML = `
  <div id="main">
    <div class="_x1"><div class="_x2">
      <div class="copyable-text" data-pre-plain-text="[09:00, 26/07/2026] Client: ">
        <div><span class="selectable-text"><span>Are you open Sunday?</span></span></div>
      </div>
      <div class="meta">09:00</div>
    </div></div>
  </div>`;
results.churned = reader();

// 3. Legacy fallback: no copyable-text anchor at all, only the old .message-in/.message-out rows.
w.document.body.innerHTML = `
  <div id="main">
    <div class="message-in"><span class="selectable-text">Do you deliver to Paris?</span></div>
    <div class="message-out"><span class="selectable-text">We do, next-day.</span></div>
  </div>`;
results.legacy = reader();

// 4. No open chat is an empty list, never a throw.
w.document.body.innerHTML = `<div>no #main here</div>`;
results.empty = reader();

console.log(JSON.stringify(results));
// whatsapp.js starts a MutationObserver + setInterval via Halia.observe, which keeps Node's event
// loop alive; exit explicitly so the harness terminates.
process.exit(0);
