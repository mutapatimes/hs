// The house shaping rules: fill the client's name into a template, and honour the greeting and
// sign-off toggles. Mid-conversation an associate rarely wants either, so every Halia surface lets
// them switch them off, and every surface has to agree on what that means.
//
// THIS FILE IS THE ONE COPY. It is served at /static/halia-shape.js for the Outlook task pane, and
// `scripts/sync_shape.py` writes an identical copy to extension/content/shape.js because MV3
// forbids a content script from loading remote code. tests/test_shape_sync.py fails the build if
// the two ever drift; tests/js/shape_smoke.js covers the behaviour.
//
// Attaches to window.HaliaShape. No dependencies, no DOM, pure string in / string out.
(function () {
  var GREET_RE = /^(dear|dearest|hi|hello|hey|good\s+(morning|afternoon|evening)|greetings)\b/i;
  var SIGN_LINE = /^(warm(est)?\s+(regards|wishes)|kind(est)?\s+regards|best(\s+(regards|wishes))?|very\s+best|all\s+the\s+best|with\s+(love|thanks|gratitude|appreciation|warm\s+wishes|warmth)|many\s+thanks|thank\s+you|thanks|yours(\s+(sincerely|truly|faithfully))?|sincerely|warmly|speak\s+soon|see\s+you\s+soon|regards|cheers|love|xx)[.,!]*(\s+[A-Z][\w'’.-]*(\s+[A-Z][\w'’.-]*)?)?$/i;

  // The server leaves {first_name} as a literal so each surface can fill it per client. With no
  // name we say "there" rather than leaving a hole in the sentence.
  function fillName(body, first) {
    return String(body || "").split("{first_name}").join(first || "there");
  }

  // Remove the leading salutation clause up to its comma (handles "Dear X,\n\n…" and inline
  // "Hi X, …"), or a short own-line greeting with no comma.
  function stripGreeting(text) {
    var t = String(text || "").replace(/^\s+/, "");
    if (!GREET_RE.test(t)) return String(text || "");
    var comma = t.indexOf(","), nl = t.indexOf("\n");
    if (comma >= 0 && (nl < 0 || comma < nl)) {
      return t.slice(comma + 1).replace(/^[ \t]*\n+/, "").replace(/^[ \t]+/, "");
    }
    if (nl >= 0 && nl <= 24) return t.slice(nl + 1).replace(/^\s+/, "");
    return String(text || "");
  }

  // Cut from the closing line to the end. Only the last few lines are considered, and a line counts
  // as a closing only when it is essentially just a sign-off phrase (optionally a name), so body
  // text like "Thanks for your patience." is never mistaken for one.
  function stripSignoff(text) {
    var lines = String(text || "").split("\n");
    var nonEmpty = [];
    for (var k = 0; k < lines.length; k++) if (lines[k].trim()) nonEmpty.push(k);
    if (!nonEmpty.length) return String(text || "");
    var tail = nonEmpty.slice(-4);
    var cut = -1;
    for (var j = 0; j < tail.length; j++) {
      if (SIGN_LINE.test(lines[tail[j]].trim())) { cut = tail[j]; break; }
    }
    if (cut < 0) return String(text || "");
    var out = lines.slice(0, cut);
    while (out.length && !out[out.length - 1].trim()) out.pop();
    return out.join("\n");
  }

  function shape(body, first, greeting, signoff) {
    var t = fillName(body, first);
    if (!greeting) t = stripGreeting(t);
    if (!signoff) t = stripSignoff(t);
    return t;
  }

  var api = { fillName: fillName, stripGreeting: stripGreeting, stripSignoff: stripSignoff,
              shape: shape };
  if (typeof window !== "undefined") window.HaliaShape = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // tests/js
})();
