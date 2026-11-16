/* Group Chat Market: small dependency-free front end (theme, toasts, local times,
   bet panel with live preview, and SVG charts). */
(function () {
  'use strict';
  var COLORS = ['#5b6cff', '#16a37f', '#e5484d', '#f5a524', '#a855f7', '#06b6d4', '#f97316', '#84cc16', '#ec4899', '#64748b'];
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* ---- theme toggle ---- */
  var tt = $('#theme-toggle');
  if (tt) tt.addEventListener('click', function () {
    var cur = document.documentElement.dataset.theme ||
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (e) { /* private mode */ }
  });

  /* ---- toasts ---- */
  $$('.toast').forEach(function (t, i) {
    setTimeout(function () { t.classList.add('hide'); }, 4200 + i * 400);
    t.addEventListener('click', function () { t.classList.add('hide'); });
  });

  /* ---- UTC timestamps -> viewer's local time ---- */
  $$('time[data-utc]').forEach(function (el) {
    var d = new Date(el.dataset.utc);
    if (isNaN(d)) return;
    var prefix = el.textContent.match(/^[^A-Z0-9]*/)[0];
    el.textContent = prefix + d.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  });

  /* ---- confirm dialogs on destructive forms ---- */
  $$('form[data-confirm]').forEach(function (f) {
    f.addEventListener('submit', function (e) { if (!confirm(f.dataset.confirm)) e.preventDefault(); });
  });

  /* ---- copy buttons ---- */
  $$('[data-copy]').forEach(function (b) {
    b.addEventListener('click', function () {
      var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(done); else { window.prompt('Copy this link:', b.dataset.copy); }
    });
  });

  /* ---- new-market form: show the fields for the chosen type, send tz offset ---- */
  var nm = $('#new-market');
  if (nm) {
    $('#tz_offset').value = new Date().getTimezoneOffset();
    var sync = function () {
      var k = ($('input[name=kind]:checked', nm) || {}).value;
      $$('[data-kind]', nm).forEach(function (el) { el.hidden = el.dataset.kind !== k; });
    };
    $$('input[name=kind]', nm).forEach(function (r) { r.addEventListener('change', sync); });
    sync();
  }

  /* ---- bet panel ---- */
  function fmt(n) { return '$' + Number(n).toFixed(2); }
  var buy = $('#buy-form');
  if (buy) {
    var out = $('.preview', buy), btn = $('#buy-btn'), amt = $('#dollars');
    var sel = function () { return $('input[name=outcome]:checked', buy); };
    var timer = null;
    var update = function () {
      var o = sel(), v = parseFloat(amt.value);
      btn.textContent = o ? 'Buy ' + o.dataset.label : 'Buy';
      if (!o || !(v > 0)) { out.textContent = ''; out.className = 'preview'; return; }
      clearTimeout(timer);
      timer = setTimeout(function () {
        fetch('/api/market/' + buy.dataset.market + '/preview?outcome=' + o.value + '&dollars=' + v, { credentials: 'same-origin' })
          .then(function (r) { return r.json(); }).then(function (d) {
            if (d.error) { out.textContent = d.error; out.className = 'preview err'; return; }
            out.className = 'preview ok';
            out.innerHTML = 'You get <b>' + d.shares.toFixed(1) + ' shares</b>. If <b>' + o.dataset.label + '</b> wins you collect <b>' +
              fmt(d.payout) + '</b> (profit ' + fmt(d.payout - v) + ').';
          });
      }, 120);
    };
    buy.addEventListener('input', update);
    $$('[data-amt]', buy).forEach(function (c) { c.addEventListener('click', function () { amt.value = c.dataset.amt; update(); }); });
    update();
  }
  var sell = $('#sell-form');
  if (sell) {
    var sout = $('.preview', sell), sin = $('input[name=shares]', sell);
    var supd = function () {
      var o = $('select[name=outcome]', sell).value, v = parseFloat(sin.value);
      if (!(v > 0)) { sout.textContent = ''; return; }
      fetch('/api/market/' + sell.dataset.market + '/preview?outcome=' + o + '&shares=' + v, { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).then(function (d) {
          sout.textContent = d.error ? d.error : 'You would receive ' + fmt(d.refund) + '.';
        });
    };
    sell.addEventListener('input', supd);
  }

  /* ---- SVG line chart ---- */
  var NS = 'http://www.w3.org/2000/svg';
  function el(name, attrs, text) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  /* series: [{label,color,pts:[[tMs, value]],width,opacity}] ; opts: {pct, h} */
  function drawLines(host, series, opts) {
    host.innerHTML = '';
    var W = host.clientWidth || 340, H = opts.h || 240, m = { l: 40, r: 10, t: 8, b: 22 };
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: '100%', height: H, role: 'img' });
    var all = [].concat.apply([], series.map(function (s) { return s.pts; }));
    if (!all.length) { host.textContent = 'No data yet.'; return; }
    var xmin = opts.xmin != null ? opts.xmin : Math.min.apply(null, all.map(function (p) { return p[0]; }));
    var xmax = opts.xmax != null ? opts.xmax : Math.max.apply(null, all.map(function (p) { return p[0]; }));
    if (xmax <= xmin) xmax = xmin + 3600e3;
    var visible = all.filter(function (p) { return p[0] >= xmin; });
    var ymax = opts.pct ? Math.min(100, Math.ceil((Math.max.apply(null, visible.map(function (p) { return p[1]; })) + 4) / 10) * 10)
      : Math.max.apply(null, visible.map(function (p) { return p[1]; })) * 1.08;
    var ymin = opts.pct ? 0 : Math.min.apply(null, visible.map(function (p) { return p[1]; })) * 0.92;
    if (ymax <= ymin) ymax = ymin + 1;
    var X = function (x) { return m.l + (x - xmin) / (xmax - xmin) * (W - m.l - m.r); };
    var Y = function (y) { return H - m.b - (y - ymin) / (ymax - ymin) * (H - m.t - m.b); };
    var grid = css('--border'), mut = css('--muted');
    for (var k = 0; k <= 4; k++) {
      var yv = ymin + (ymax - ymin) * k / 4;
      svg.appendChild(el('line', { x1: m.l, x2: W - m.r, y1: Y(yv), y2: Y(yv), stroke: grid }));
      svg.appendChild(el('text', { x: m.l - 6, y: Y(yv) + 4, fill: mut, 'font-size': 11, 'text-anchor': 'end' },
        opts.pct ? Math.round(yv) + '%' : '$' + Math.round(yv)));
    }
    for (var j = 0; j <= 3; j++) {
      var xv = xmin + (xmax - xmin) * j / 3, d = new Date(xv);
      var label = (xmax - xmin) < 36e5 * 36 ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
      svg.appendChild(el('text', { x: X(xv), y: H - 5, fill: mut, 'font-size': 11, 'text-anchor': j === 0 ? 'start' : j === 3 ? 'end' : 'middle' }, label));
    }
    series.forEach(function (s) {
      var pts = s.pts.filter(function (p) { return p[0] >= xmin; });
      /* step line: price holds until the next trade */
      var d = '';
      pts.forEach(function (p, i) { d += (i ? ' L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); });
      svg.appendChild(el('path', { d: d, fill: 'none', stroke: s.color, 'stroke-width': s.width || 2, 'stroke-opacity': s.opacity == null ? 1 : s.opacity, 'stroke-linejoin': 'round' }));
    });
    host.appendChild(svg);
  }

  function chartShell(host) {
    host.innerHTML = '<div class="chart-controls"></div><div class="chart-area"></div><div class="legend"></div>';
    return { controls: $('.chart-controls', host), area: $('.chart-area', host), legend: $('.legend', host) };
  }
  function pills(container, items, current, onPick) {
    container.innerHTML = '';
    items.forEach(function (it) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'chip small' + (it.key === current ? ' on' : ''); b.textContent = it.label;
      b.addEventListener('click', function () { onPick(it.key); });
      container.appendChild(b);
    });
  }

  var mc = $('#market-chart');
  if (mc) fetch(mc.dataset.url).then(function (r) { return r.json(); }).then(function (d) {
    var sh = chartShell(mc);
    var pts = d.points.map(function (p) { return { t: Date.parse(p.t), p: p.p }; });
    var last = pts[pts.length - 1];
    var order = d.outcomes.map(function (o, i) { return { o: o, i: i, v: last ? (last.p[o.id] || 0) : 0 }; })
      .sort(function (a, b) { return b.v - a.v; });
    var state = { top: d.outcomes.length > 4, range: 'all', hi: null };
    function render() {
      var shown = state.top ? order.slice(0, 4) : order;
      var end = last ? last.t : Date.now();
      var span = { '1d': 864e5, '1w': 6048e5, all: null }[state.range];
      var series = shown.map(function (x) {
        var dim = state.hi != null && state.hi !== x.o.id;
        return {
          label: x.o.label, color: COLORS[x.i % COLORS.length], id: x.o.id,
          width: state.hi === x.o.id ? 3.5 : 2, opacity: dim ? 0.18 : 1,
          pts: pts.map(function (p) { return [p.t, (p.p[x.o.id] || 0) * 100]; })
        };
      });
      /* extend the last value to "now" so a quiet market still shows a line to the right edge */
      series.forEach(function (s) { if (s.pts.length) s.pts.push([Math.max(end, Date.now()), s.pts[s.pts.length - 1][1]]); });
      var rangeItems = [{ key: '1d', label: '1 day' }, { key: '1w', label: '1 week' }, { key: 'all', label: 'All' }];
      var ctl = sh.controls; ctl.innerHTML = '';
      var left = document.createElement('div'); left.className = 'pill-row'; ctl.appendChild(left);
      pills(left, rangeItems, state.range, function (k) { state.range = k; render(); });
      if (d.outcomes.length > 4) {
        var right = document.createElement('div'); right.className = 'pill-row'; ctl.appendChild(right);
        pills(right, [{ key: 'top', label: 'Top 4' }, { key: 'all', label: 'Show all ' + d.outcomes.length }], state.top ? 'top' : 'all',
          function (k) { state.top = k === 'top'; render(); });
      }
      drawLines(sh.area, series, { pct: true, h: 230, xmax: Math.max(end, Date.now()), xmin: span ? Math.max(end, Date.now()) - span : null });
      sh.legend.innerHTML = '';
      series.forEach(function (s) {
        var b = document.createElement('button'); b.type = 'button';
        b.className = 'lg' + (state.hi === s.id ? ' on' : '');
        b.innerHTML = '<i style="background:' + s.color + '"></i>' + s.label.replace(/</g, '&lt;');
        b.addEventListener('click', function () { state.hi = state.hi === s.id ? null : s.id; render(); });
        sh.legend.appendChild(b);
      });
    }
    render();
    window.addEventListener('resize', function () { render(); });
  });

  var lb = $('#lb-chart');
  if (lb) fetch(lb.dataset.url).then(function (r) { return r.json(); }).then(function (d) {
    var sh = chartShell(lb);
    var top = d.board.slice(0, 5);
    var series = top.map(function (b, i) {
      return { label: b.name, color: COLORS[i % COLORS.length], width: 2.2,
        pts: (d.series[b.id] || []).map(function (p) { return [Date.parse(p.t), p.v]; }) };
    });
    drawLines(sh.area, series, { pct: false, h: 230 });
    series.forEach(function (s) {
      var b = document.createElement('span'); b.className = 'lg';
      b.innerHTML = '<i style="background:' + s.color + '"></i>' + s.label.replace(/</g, '&lt;');
      sh.legend.appendChild(b);
    });
  });
})();
