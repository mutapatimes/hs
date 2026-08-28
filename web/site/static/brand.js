/* Halia shared brand behaviour, loaded on every page:
     1. the top-logo asterism spins as the page scrolls (rotation tracks the
        vertical scroll offset). Subtle, header-only, and off when reduced
        motion is preferred.
     2. the footer newsletter form posts to /subscribe. */
(function () {

  function initSpin() {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var marks = document.querySelectorAll('header .brand > span:first-child');
    if (!marks.length) return;
    var queued = false;
    function paint() {
      queued = false;
      var y = window.pageYOffset || document.documentElement.scrollTop || 0;
      var deg = y * 0.4;   // ~one full turn per 900px of scroll — nice and subtle
      for (var i = 0; i < marks.length; i++) {
        marks[i].style.transform = 'rotate(' + deg.toFixed(1) + 'deg)';
      }
    }
    window.addEventListener('scroll', function () {
      if (!queued) { queued = true; requestAnimationFrame(paint); }
    }, { passive: true });
    paint();   // honour any restored scroll position on load
  }

  function initNews() {
    var nf = document.getElementById('newsForm');
    if (!nf || nf.dataset.bound) return;   // guard against double-binding
    nf.dataset.bound = '1';
    nf.addEventListener('submit', function (e) {
      e.preventDefault();
      var el = document.getElementById('newsEmail');
      var em = ((el && el.value) || '').trim();
      if (!/.+@.+\..+/.test(em)) return;
      var b = nf.querySelector('button');
      if (b) { b.disabled = true; b.textContent = '…'; }
      var done = function () { nf.innerHTML = '<span class="ok">Thank you. You are on the list.</span>'; };
      fetch('/subscribe', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email: em })
      }).then(done).catch(done);
    });
  }

  function initHeroFallback() {
    // The hero background is a muted autoplay video. Mobile browsers often block
    // that (iOS Low Power Mode, data saver, flaky connections) and leave a static
    // poster. When the video can't play, swap in an animated GIF instead. The GIF
    // is only fetched when actually needed (data-src), so capable devices that
    // play the video never download it.
    var v = document.getElementById('heroVid');
    var g = document.getElementById('heroGif');
    if (!v || !g) return;
    var used = false;
    function useGif() {
      if (used) return;
      used = true;
      if (g.dataset.src) g.src = g.dataset.src;
      if (v.parentNode) v.parentNode.classList.add('use-gif');
    }
    v.addEventListener('error', useGif, true);
    var p = v.play && v.play();
    if (p && typeof p.then === 'function') p.catch(useGif);   // autoplay rejected
    setTimeout(function () {                                   // safety net
      if (v.paused && v.currentTime === 0) useGif();
    }, 2500);
  }

  function init() { initSpin(); initNews(); initHeroFallback(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

// Live chat: the Brevo Conversations bubble, on when HALIA_BREVO_CHAT_ID is configured.
// A ?chat=open in the URL opens the conversation straight away (used by the extension and iOS app).
(function () {
  fetch('/v1/chat-config').then(function (r) { return r.json(); }).then(function (c) {
    if (!c || !c.id) return;
    window.BrevoConversationsID = c.id;
    window.BrevoConversations = window.BrevoConversations || function () {
      (window.BrevoConversations.q = window.BrevoConversations.q || []).push(arguments);
    };
    if (new URLSearchParams(location.search).get('chat') === 'open') {
      window.BrevoConversations('openChat', true);
    }
    var s = document.createElement('script');
    s.async = true; s.src = 'https://conversations-widget.brevo.com/brevo-conversations.js';
    document.head.appendChild(s);
  }).catch(function () {});
})();

// Book a walkthrough (Cal.com) and a WhatsApp line: both appear only once configured.
(function () {
  fetch('/v1/chat-config').then(function (r) { return r.json(); }).then(function (c) {
    var cals = document.querySelectorAll('[data-cal]');
    if (c && c.cal) {
      var link = 'https://cal.com/' + c.cal;
      cals.forEach(function (el) {
        el.hidden = false; el.removeAttribute('hidden'); el.style.display = '';
        if (el.tagName === 'A') { el.href = link; el.target = '_blank'; el.rel = 'noopener'; }
        el.setAttribute('data-cal-link', c.cal);
        el.setAttribute('data-cal-config', '{"layout":"month_view","theme":"light"}');
      });
      (function (C, A, L) { var p = function (a, ar) { a.q.push(ar); }; var d = C.document;
        C.Cal = C.Cal || function () { var cal = C.Cal, ar = arguments; if (!cal.loaded) { cal.ns = {}; cal.q = cal.q || [];
          d.head.appendChild(d.createElement('script')).src = A; cal.loaded = true; }
          if (ar[0] === L) { var api = function () { p(api, arguments); }; var ns = ar[1]; api.q = api.q || [];
            typeof ns === 'string' ? (cal.ns[ns] = api) && p(api, ar) : p(cal, ar); return; } p(cal, ar); }; })
        (window, 'https://app.cal.com/embed/embed.js', 'init');
      window.Cal('init', { origin: 'https://cal.com' });
      window.Cal('ui', { theme: 'light', hideEventTypeDetails: false, layout: 'month_view' });
    } else {
      cals.forEach(function (el) { el.style.display = 'none'; });
    }
    if (c && c.whatsapp) {
      var a = document.createElement('a');
      a.href = 'https://wa.me/' + c.whatsapp + '?text=' + encodeURIComponent('Hello Halia, ');
      a.target = '_blank'; a.rel = 'noopener'; a.setAttribute('aria-label', 'Message us on WhatsApp');
      a.style.cssText = 'position:fixed;right:22px;bottom:' + (c.id ? '96px' : '22px') + ';z-index:2147483000;width:52px;height:52px;border-radius:50%;background:#1a1a1d;color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 24px rgba(0,0,0,.18);text-decoration:none';
      a.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5.1-1.3A10 10 0 1 0 12 2zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.3-.4.2-.4.7-1.3.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.8 12 12 0 0 0 4.6 4c.6.3 1.1.4 1.5.5.6.2 1.2.2 1.6.1.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.1-1.2l-.5-.3z"/></svg>';
      document.body.appendChild(a);
    }
  }).catch(function () {});
})();

// System status in the footer, read from the same checks the status page shows.
(function () {
  var bot = document.querySelector('.hf-bot');
  if (!bot) return;
  fetch('/status.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
    var ok = d && (d.ok === true || d.status === 'ok' || d.overall === 'ok' ||
      (Array.isArray(d.checks) && d.checks.length > 0 && d.checks.every(function (c) { return c.ok !== false && c.status !== 'down'; })));
    var a = document.createElement('a');
    a.href = '/status';
    a.style.cssText = 'display:inline-flex;align-items:center;gap:8px;margin-left:18px;color:inherit;text-decoration:none';
    a.innerHTML = '<span style="width:7px;height:7px;border-radius:50%;background:' + (ok ? '#7fae9d' : '#b8a56a') + ';display:inline-block"></span>' +
      (ok ? 'All systems normal' : 'Some systems degraded');
    bot.appendChild(a);
  }).catch(function () {});
})();
