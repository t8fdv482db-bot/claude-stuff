/* Keenroll theme JS: small, dependency-free */
(function () {
  'use strict';

  // Mobile menu
  document.querySelectorAll('[data-menu-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var nav = document.getElementById(btn.getAttribute('aria-controls'));
      var open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      nav.classList.toggle('is-open', !open);
    });
  });

  // Product gallery thumbnails
  document.querySelectorAll('[data-gallery]').forEach(function (g) {
    var main = g.querySelector('[data-gallery-main]');
    g.querySelectorAll('[data-gallery-thumb]').forEach(function (t) {
      t.addEventListener('click', function () {
        main.src = t.getAttribute('data-src');
        main.alt = t.getAttribute('data-alt') || '';
        g.querySelectorAll('[data-gallery-thumb]').forEach(function (o) { o.setAttribute('aria-current', 'false'); });
        t.setAttribute('aria-current', 'true');
      });
    });
  });

  // Bundle selector -> update visible price + sticky bar
  document.querySelectorAll('[data-bundles]').forEach(function (fs) {
    var priceEl = document.querySelector('[data-main-price]');
    var stickyTitle = document.querySelector('[data-sticky-variant]');
    var stickyPrice = document.querySelector('[data-sticky-price]');
    function update() {
      var c = fs.querySelector('input:checked');
      if (!c) return;
      if (priceEl) priceEl.innerHTML = c.getAttribute('data-price-html');
      if (stickyTitle) stickyTitle.textContent = c.getAttribute('data-label');
      if (stickyPrice) stickyPrice.textContent = c.getAttribute('data-price');
    }
    fs.addEventListener('change', update);
    update();
  });

  // Sticky add-to-cart: show once the main button scrolls out of view
  var mainBtn = document.querySelector('[data-main-atc]');
  var sticky = document.querySelector('[data-sticky-atc]');
  if (mainBtn && sticky && 'IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) {
      var e = entries[0];
      var below = e.boundingClientRect.top < 0; // scrolled past it
      sticky.classList.toggle('is-visible', !e.isIntersecting && below);
    }).observe(mainBtn);
  }

  // Honest delivery estimate, driven by theme settings (business days)
  document.querySelectorAll('[data-delivery-estimate]').forEach(function (el) {
    var min = parseInt(el.getAttribute('data-min'), 10) || 8;
    var max = parseInt(el.getAttribute('data-max'), 10) || 15;
    function addBusinessDays(d, n) {
      var r = new Date(d);
      while (n > 0) { r.setDate(r.getDate() + 1); var w = r.getDay(); if (w !== 0 && w !== 6) n--; }
      return r;
    }
    var fmt = { month: 'short', day: 'numeric' };
    var now = new Date();
    el.textContent = addBusinessDays(now, min).toLocaleDateString('en-US', fmt) + ' – ' + addBusinessDays(now, max).toLocaleDateString('en-US', fmt);
  });

  // Track order: send tracking numbers to a public tracker
  document.querySelectorAll('[data-tracking-form]').forEach(function (f) {
    f.addEventListener('submit', function (ev) {
      ev.preventDefault();
      var n = (f.querySelector('input[name=tracking]').value || '').trim();
      if (!n) return;
      window.open('https://t.17track.net/en#nums=' + encodeURIComponent(n), '_blank', 'noopener');
    });
  });
})();
