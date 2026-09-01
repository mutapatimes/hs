// Exercise the house shaping rules (web/site/static/halia-shape.js) — the code every Halia surface
// runs on a template before it goes into a chat or an email. Prints one JSON line and exits 0.
// Used by tests/test_extension_js.py.
const path = require("path");
const shape = require(path.join(__dirname, "..", "..", "web", "site", "static", "halia-shape.js"));

const cases = [];
function check(name, got, want) { cases.push({ name, ok: got === want, got, want }); }

// ── the name ──
check("fills the token", shape.fillName("Dear {first_name}, hello", "Grace"),
  "Dear Grace, hello");
check("no name falls back rather than leaving a hole", shape.fillName("Hi {first_name}, hello", ""),
  "Hi there, hello");
check("fills every occurrence", shape.fillName("{first_name} — {first_name}", "Grace"),
  "Grace — Grace");

// ── the greeting ──
check("drops a greeting on its own line",
  shape.stripGreeting("Dear Grace,\n\nThe coat is in."), "The coat is in.");
check("drops an inline greeting up to the comma",
  shape.stripGreeting("Hi Grace, the coat is in."), "the coat is in.");
check("drops a short own-line greeting with no comma",
  shape.stripGreeting("Hello\nThe coat is in."), "The coat is in.");
// A longer salutation is still a salutation: everything up to the comma goes.
check("drops a salutation of more than one word",
  shape.stripGreeting("Hello and welcome back, the coat is in."), "the coat is in.");
// But with no comma and no early line break there is nothing to cut, so the body survives whole.
check("leaves a body that merely opens with a greeting word",
  shape.stripGreeting("Hello there is news about the coat you asked for"),
  "Hello there is news about the coat you asked for");
check("leaves text with no greeting alone",
  shape.stripGreeting("The coat is in."), "The coat is in.");

// ── the sign-off ──
check("cuts from the closing line",
  shape.stripSignoff("The coat is in.\n\nWarm regards,\nSarah"), "The coat is in.");
check("cuts a closing that carries a name",
  shape.stripSignoff("The coat is in.\n\nSarah Bloom"), "The coat is in.\n\nSarah Bloom");
check("never mistakes body text for a closing",
  shape.stripSignoff("Thanks for your patience.\n\nThe coat is in on Tuesday and I have held it."),
  "Thanks for your patience.\n\nThe coat is in on Tuesday and I have held it.");
check("leaves text with no closing alone",
  shape.stripSignoff("The coat is in."), "The coat is in.");

// ── both toggles together, which is what every surface actually calls ──
check("both on is the whole template",
  shape.shape("Dear {first_name},\n\nThe coat is in.\n\nWarmly,\nSarah", "Grace", true, true),
  "Dear Grace,\n\nThe coat is in.\n\nWarmly,\nSarah");
check("both off is the middle only",
  shape.shape("Dear {first_name},\n\nThe coat is in.\n\nWarmly,\nSarah", "Grace", false, false),
  "The coat is in.");
check("greeting off keeps the closing",
  shape.shape("Dear {first_name},\n\nThe coat is in.\n\nWarmly,\nSarah", "Grace", false, true),
  "The coat is in.\n\nWarmly,\nSarah");

// A link-led template must survive: stripping used to mangle these in the Swift copy.
check("a template that opens with a link is untouched",
  shape.shape("https://x.example/coat\n\nThought of you.", "Grace", false, false),
  "https://x.example/coat\n\nThought of you.");

const failed = cases.filter((c) => !c.ok);
process.stdout.write(JSON.stringify({ total: cases.length, failed }) + "\n");
