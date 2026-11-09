/* 悬浮目录：默认「只看我说」，点击条目直接跳转到那条发言。
   数据由 src/build_site.py 生成为 window.NAV_USER / window.NAV_ALL。 */
(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  var panel = $('#toc'), toggle = $('#tocToggle'), list = $('#tocList');
  var search = $('#tocSearch'), only = $('#onlyMine');
  var tab = 'user', currentId = '', items = [];

  var NAV = { user: window.NAV_USER || [], all: window.NAV_ALL || [] };
  $('#tocCount').textContent = NAV.user.length;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function render() {
    var q = search.value.trim().toLowerCase();
    var src = NAV[tab].filter(function (it) {
      return !q || (it.full || it.text || '').toLowerCase().indexOf(q) >= 0;
    });
    items = src;
    if (!src.length) { list.innerHTML = '<div class="nav-empty">没有匹配的发言</div>'; return; }
    var html = '', date = '';
    src.forEach(function (it) {
      if (it.date !== date) {
        date = it.date;
        html += '<div class="nav-date">' + esc(date) + '</div>';
      }
      var who = tab === 'all' ? '<span class="who">' + esc(it.who || '') + '</span>' : '';
      html += '<button class="nav-item' + (it.id === currentId ? ' active' : '') +
        '" type="button" data-id="' + esc(it.id) + '" title="' + esc((it.full || '').slice(0, 160)) + '">' +
        '<span class="num">#' + it.n + '</span>' + who + '<span>' + esc(it.text) + '</span></button>';
    });
    list.innerHTML = html;
  }

  function markActive(id) {
    currentId = id;
    Array.prototype.forEach.call(list.querySelectorAll('.nav-item'), function (el) {
      el.classList.toggle('active', el.dataset.id === id);
    });
    var act = list.querySelector('.nav-item.active');
    if (act && act.scrollIntoView) act.scrollIntoView({ block: 'nearest' });
  }

  function jump(id) {
    var el = document.getElementById(id);
    if (!el) return;
    history.replaceState(null, '', '#' + id);
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.classList.remove('flash');
    void el.offsetWidth;
    el.classList.add('flash');
    setTimeout(function () { el.classList.remove('flash'); }, 1800);
    markActive(id);
  }

  function step(dir) {
    var ids = NAV.user.map(function (x) { return x.id; });
    if (!ids.length) return;
    var pos = -1;
    ids.forEach(function (id, i) { if (id === currentId) pos = i; });
    if (pos < 0) {
      var y = window.scrollY + 100;
      ids.forEach(function (id, i) {
        var el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top + window.scrollY <= y) pos = i;
      });
    }
    var next = Math.min(ids.length - 1, Math.max(0, pos + dir));
    jump(ids[next]);
  }

  toggle.addEventListener('click', function () {
    var open = panel.classList.toggle('open');
    toggle.classList.toggle('active', open);
    if (open) { render(); search.focus(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { panel.classList.remove('open'); toggle.classList.remove('active'); }
  });
  document.addEventListener('click', function (e) {
    if (!panel.classList.contains('open')) return;
    if (panel.contains(e.target) || toggle.contains(e.target)) return;
    panel.classList.remove('open'); toggle.classList.remove('active');
  });

  Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
    b.addEventListener('click', function () {
      Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (x) { x.classList.remove('active'); });
      b.classList.add('active');
      tab = b.dataset.tab;
      render();
    });
  });
  search.addEventListener('input', render);
  only.addEventListener('change', function () { document.body.classList.toggle('only-mine', only.checked); });
  list.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('.nav-item') : null;
    if (b) jump(b.dataset.id);
  });
  $('#jumpPrev').addEventListener('click', function () { step(-1); });
  $('#jumpNext').addEventListener('click', function () { step(1); });

  window.addEventListener('load', function () {
    render();
    if (location.hash) setTimeout(function () { jump(decodeURIComponent(location.hash.slice(1))); }, 80);
  });
})();
