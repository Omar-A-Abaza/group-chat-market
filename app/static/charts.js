(function () {
  const COLORS = ['#6ea8ff','#4ade80','#f87171','#fbbf24','#c084fc','#22d3ee','#fb923c','#a3e635','#f472b6','#94a3b8'];
  const fmtT = t => new Date(t + 'Z').toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
  const opts = (extra) => Object.assign({responsive:true, maintainAspectRatio:false,
    plugins:{legend:{labels:{color:'#e8eaf0'}}},
    scales:{x:{ticks:{color:'#8a90a0',maxTicksLimit:6},grid:{color:'#222733'}},y:{ticks:{color:'#8a90a0'},grid:{color:'#222733'}}}}, extra || {});

  async function get(url) { const r = await fetch(url, {credentials:'same-origin'}); return r.json(); }

  const mc = document.getElementById('market-chart');
  if (mc && window.Chart) get(mc.dataset.url).then(d => {
    new Chart(mc, {type:'line', data:{labels:d.points.map(p => fmtT(p.t)),
      datasets:d.outcomes.map((o,i) => ({label:o.label, data:d.points.map(p => (p.p[o.id]||0)*100),
        borderColor:COLORS[i%COLORS.length], backgroundColor:COLORS[i%COLORS.length], pointRadius:1, tension:.2}))},
      options:opts({scales:{x:{ticks:{color:'#8a90a0',maxTicksLimit:6},grid:{color:'#222733'}},y:{min:0,max:100,ticks:{color:'#8a90a0',callback:v=>v+'%'},grid:{color:'#222733'}}}})});
  });

  const lb = document.getElementById('lb-bar'), ll = document.getElementById('lb-line');
  if ((lb || ll) && window.Chart) get((lb || ll).dataset.url).then(d => {
    if (lb) new Chart(lb, {type:'bar', data:{labels:d.board.map(b => b.name),
      datasets:[{label:'Net worth ($)', data:d.board.map(b => b.value), backgroundColor:'#6ea8ff'}]},
      options:opts({indexAxis:'y'})});
    if (ll) {
      const n = Math.max(0, ...Object.values(d.series).map(s => s.length));
      const ref = Object.values(d.series).sort((a,b) => b.length - a.length)[0] || [];
      new Chart(ll, {type:'line', data:{labels:ref.map(p => fmtT(p.t)),
        datasets:d.board.map((b,i) => ({label:b.name, data:(d.series[b.id]||[]).map(p => p.v),
          borderColor:COLORS[i%COLORS.length], pointRadius:1, tension:.2}))}, options:opts()});
    }
  });

  document.querySelectorAll('form[data-trade]').forEach(f => {
    const kind = f.dataset.trade, out = f.querySelector('.preview');
    const upd = async () => {
      const o = f.outcome.value, v = kind === 'buy' ? f.dollars.value : f.shares.value;
      if (!o || !v || isNaN(v) || +v <= 0) { out.textContent = ''; return; }
      const q = new URLSearchParams({outcome:o}); q.set(kind === 'buy' ? 'dollars' : 'shares', v);
      const r = await fetch(`/api/market/${f.dataset.market}/preview?` + q);
      const d = await r.json();
      const label = f.outcome.selectedOptions[0].text.replace(/ \(.*/, '');
      out.textContent = d.error ? d.error : kind === 'buy'
        ? `$${(+v).toFixed(2)} → ${d.shares.toFixed(1)} shares, pays $${d.payout.toFixed(2)} if ${label}`
        : `${(+v).toFixed(1)} shares → $${d.refund.toFixed(2)}`;
    };
    f.addEventListener('input', upd); f.outcome.addEventListener('change', upd);
  });
})();
