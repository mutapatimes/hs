// Halia storefront surface — the reverse share flow, on the merchant's own website. Wherever the
// associate browses their store (a product, a collection, a care or returns page, the about page),
// the toolbar offers "Send this to a client": pick who from the book, choose an opener that fits the
// page, and message them the link. The mirror of the iOS HaliaShare card. Reads live; stores nothing.
(function () {
  // Leave the admin surfaces to admin.js — this script is for the shopper-facing storefront only.
  const path = location.pathname.toLowerCase();
  if (path.indexOf("/admin") === 0 || path.indexOf("/wp-admin") === 0) return;
  if (/^(admin|www\.haliascore|haliascore)\./.test(location.hostname)) return;

  // What kind of page is this? Same classes the iOS card uses, so the openers match across both.
  function pageKind(raw) {
    const u = String(raw || "").toLowerCase();
    const any = (words) => words.some((w) => u.indexOf(w) >= 0);
    if (u.indexOf("/products/") >= 0) return "product";
    if (u.indexOf("/collections/") >= 0) return "collection";
    if (any(["care-guide", "product-care", "garment-care", "/care"])) return "care";
    if (any(["return", "refund", "exchange"])) return "returns";
    if (any(["size-guide", "size-chart", "sizing", "/size"])) return "size";
    if (any(["/about", "our-story", "the-house", "heritage", "/story"])) return "about";
    if (any(["contact", "find-us", "/stores", "location", "/visit", "appointment", "/book"])) return "contact";
    return "press";
  }

  // The cleanest link to share: the page's canonical URL when it declares one, else the address bar
  // without tracking query junk.
  function shareUrl() {
    const canon = document.querySelector('link[rel="canonical"]');
    const href = (canon && canon.href) || location.href;
    try {
      const u = new URL(href);
      u.search = ""; u.hash = "";
      return u.toString();
    } catch (e) {
      return href.split("?")[0].split("#")[0];
    }
  }

  // A human name for what they are looking at: the product/collection title, not the site name.
  function pageTitle() {
    const og = document.querySelector('meta[property="og:title"]');
    if (og && og.content) return og.content.trim();
    const h1 = document.querySelector("h1");
    if (h1 && h1.textContent.trim()) return h1.textContent.trim();
    return (document.title || "").split(/[|–—\-·]/)[0].trim() || document.title || "";
  }

  function announce() {
    if (!window.HaliaPanel) return;
    HaliaPanel.setShare({ url: shareUrl(), title: pageTitle(), kind: pageKind(shareUrl()) });
  }

  // Mount the toolbar and load the standing context (templates, campaigns) without ever looking up a
  // client — there is no client on a storefront page. Then hand it what to share.
  Halia.observe(() => null);
  announce();

  // Single-page storefronts (Shopify, Hydrogen) swap pages without a reload; re-announce on nav so the
  // page kind and title stay in step with what is on screen.
  let lastHref = location.href;
  function onNav() { if (location.href !== lastHref) { lastHref = location.href; setTimeout(announce, 500); } }
  ["pushState", "replaceState"].forEach((m) => {
    const orig = history[m];
    history[m] = function () { const r = orig.apply(this, arguments); onNav(); return r; };
  });
  window.addEventListener("popstate", onNav);
  setInterval(onNav, 1500);
})();
