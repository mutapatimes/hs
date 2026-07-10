// Load a rendered dashboard HTML file in jsdom, run its script, and report any runtime error
// plus whether the Overview/Clients actually rendered. Prints one JSON line and exits 0.
// Used by tests/test_dashboard_render.py. Catches the class of bug a `new Function()` syntax
// check can't — e.g. a temporal-dead-zone ReferenceError that aborts init and blanks the page.
const { JSDOM } = require("jsdom");
const fs = require("fs");

const file = process.argv[2];
const html = fs.readFileSync(file, "utf8");
const errors = [];
const noop = () => {};

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  beforeParse(w) {
    // Stubs for browser APIs jsdom lacks — a real browser provides these, so their absence
    // must not masquerade as a dashboard bug.
    w.HTMLCanvasElement.prototype.getContext = () => ({
      fillRect: noop, clearRect: noop, beginPath: noop, arc: noop, fill: noop, moveTo: noop,
      lineTo: noop, stroke: noop, save: noop, restore: noop, translate: noop, setTransform: noop,
      measureText: () => ({ width: 0 }), createLinearGradient: () => ({ addColorStop: noop }),
    });
    w.matchMedia = () => ({ matches: false, addEventListener: noop, removeEventListener: noop, addListener: noop, removeListener: noop });
    w.scrollTo = noop;
    w.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    w.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve("{}"), blob: () => Promise.resolve({}) });
    if (w.URL) w.URL.createObjectURL = () => "blob:x";
    w.addEventListener("error", (e) => errors.push(String((e.error && e.error.stack) || e.message)));
    w.onerror = (m, s, l, c, e) => { errors.push(String((e && e.stack) || m)); };
  },
});

// Let async init settle, then report what rendered.
setTimeout(() => {
  const d = dom.window.document;
  const ovDonut = ((d.getElementById("ovDonut") || {}).innerHTML || "").length;
  const rows = ((d.getElementById("rows") || {}).innerHTML || "").length;
  console.log(JSON.stringify({ errors, ovDonut, rows }));
  process.exit(0);
}, 800);
