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
