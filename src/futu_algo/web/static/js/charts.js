// Chart helpers around TradingView Lightweight Charts v5 (vendored, global `LightweightCharts`).
// Chart times are epoch seconds of exchange-local wall time, so the library's UTC rendering
// shows Hong Kong time directly.

import { h, fmtPrice, fmtCompact, fmtChartTime, fmtPct, fmtInt, signCls, mount } from './core.js';

const LWC = () => window.LightweightCharts;

export function colors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (name) => cs.getPropertyValue(name).trim();
  return {
    surface: v('--surface'), text: v('--text'), text2: v('--text-2'), text3: v('--text-3'),
    grid: v('--chart-grid'), border: v('--border'), border2: v('--border-2'), crosshair: v('--chart-cross'),
    up: v('--up'), down: v('--down'), accent: v('--accent'), surface3: v('--surface-3'),
    series: [1, 2, 3, 4].map((i) => v(`--series-${i}`)),
    font: v('--font') || getComputedStyle(document.body).fontFamily,
  };
}

export function alpha(color, a) {
  // Accepts #rgb/#rrggbb; falls back to the input for anything else.
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color || '');
  if (!m) return color;
  let hex = m[1];
  if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('');
  const n = parseInt(hex, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

export function isIntraday(points) {
  return (points || []).some((p) => p.time % 86400 !== 0);
}

export function precisionFor(values) {
  let max = 0;
  for (const v of values) if (Number.isFinite(v) && Math.abs(v) > max) max = Math.abs(v);
  return max < 1 ? 4 : max < 10 ? 3 : 2;
}

export function makeChart(el, { intraday = false, height, panes = true } = {}) {
  const c = colors();
  const L = LWC();
  const chart = L.createChart(el, {
    autoSize: true,
    height,
    layout: {
      background: { type: 'solid', color: c.surface },
      textColor: c.text3,
      fontFamily: c.font,
      fontSize: 11,
      attributionLogo: false,
      panes: panes ? { separatorColor: c.border, separatorHoverColor: alpha(c.accent, 0.3), enableResize: true } : undefined,
    },
    grid: { vertLines: { visible: false }, horzLines: { color: c.grid, style: L.LineStyle.Solid } },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
    timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, rightOffset: 6, barSpacing: 7 },
    crosshair: {
      mode: L.CrosshairMode.Normal,
      vertLine: { color: c.crosshair, width: 1, style: L.LineStyle.Dashed, labelBackgroundColor: c.border2 },
      horzLine: { color: c.crosshair, width: 1, style: L.LineStyle.Dashed, labelBackgroundColor: c.border2 },
    },
    localization: { locale: 'en-US', dateFormat: 'yyyy-MM-dd' },
  });
  return chart;
}

function setStretch(chart, factors) {
  const panes = chart.panes();
  factors.forEach((f, i) => { if (panes[i]) panes[i].setStretchFactor(f); });
}

// --------------------------------------------------------------------------- candles

/**
 * Candles (pane 0) + volume (pane 1) + indicator lines (price overlays on pane 0, "lower"
 * lines/histograms on pane 2) + fill markers. Returns {chart, setData(payload)}.
 * payload: {candles, lines, markers, symbol, name}
 */
export function candleChart(el, payload, { onDispose } = {}) {
  const c = colors();
  const L = LWC();
  const intraday = isIntraday(payload.candles);
  const chart = makeChart(el, { intraday });
  const prec = precisionFor(payload.candles.map((k) => k.close));
  const priceFormat = { type: 'price', precision: prec, minMove: 1 / 10 ** prec };
  const candle = chart.addSeries(L.CandlestickSeries, {
    upColor: c.up, downColor: c.down, borderUpColor: c.up, borderDownColor: c.down,
    wickUpColor: c.up, wickDownColor: c.down, priceFormat, priceLineVisible: true, priceLineStyle: 2, priceLineWidth: 1,
  }, 0);
  const volume = chart.addSeries(L.HistogramSeries, {
    priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false,
  }, 1);
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.15, bottom: 0 } });
  const lineSeries = new Map();
  let slot = 0;
  const hasLower = (payload.lines || []).some((l) => l.pane !== 'price');
  for (const line of payload.lines || []) {
    const pane = line.pane === 'price' ? 0 : 2;
    let s;
    if (line.kind === 'histogram') {
      s = chart.addSeries(L.HistogramSeries, { priceLineVisible: false, lastValueVisible: false, title: '', priceFormat: { type: 'price', precision: 3, minMove: 0.001 } }, pane);
    } else {
      const color = c.series[slot++ % c.series.length];
      s = chart.addSeries(L.LineSeries, {
        color, lineWidth: 2, priceLineVisible: false, lastValueVisible: pane !== 0,
        crosshairMarkerRadius: 3, priceFormat: pane === 0 ? priceFormat : { type: 'price', precision: 2, minMove: 0.01 },
      }, pane);
      s._color = color;
    }
    lineSeries.set(line.column, { series: s, spec: line });
  }
  setStretch(chart, hasLower ? [5, 1, 1.7] : [5, 1.1]);
  const markersApi = L.createSeriesMarkers(candle, []);

  // Legend overlay (OHLC + indicator values at the crosshair).
  const legend = h('div', { class: 'chart-legend' });
  (el.parentElement || el).insertBefore(legend, el);
  const narrow = el.clientWidth < 600;
  let current = payload;
  const byTime = new Map();

  function renderLegend(time) {
    const k = time != null ? byTime.get(time) : current.candles[current.candles.length - 1];
    if (!k) { legend.replaceChildren(); return; }
    const idx = current.candles.indexOf(k);
    const prev = idx > 0 ? current.candles[idx - 1] : null;
    const chg = prev ? k.close / prev.close - 1 : null;
    const item = (label, value, cls) => h('span', { class: 'lg-item' }, h('span', { class: 'lg-k' }, label), h('span', { class: ['lg-v', cls] }, value));
    const values = [];
    for (const { series, spec } of lineSeries.values()) {
      const d = series.data();
      // binary search last point <= time
      let lo = 0; let hi = d.length - 1; let found = null;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (d[mid].time <= k.time) { found = d[mid]; lo = mid + 1; } else hi = mid - 1; }
      if (found && found.time === k.time) values.push(h('span', { class: 'lg-item' }, h('span', { class: 'lg-swatch', style: { background: series._color || alpha(c.up, 0.6) } }), h('span', { class: 'lg-k' }, spec.label), h('span', { class: 'lg-v' }, fmtPrice(found.value, 2, spec.pane === 'price' ? prec : 2))));
    }
    mount(legend,
      h('div', { class: 'lg-row' },
        current.symbol ? h('span', { class: 'lg-title' }, current.symbol) : null,
        h('span', { class: 'lg-time' }, fmtChartTime(k.time, intraday)),
            item('O', fmtPrice(k.open, 2, prec)), item('H', fmtPrice(k.high, 2, prec)), item('L', fmtPrice(k.low, 2, prec)), item('C', fmtPrice(k.close, 2, prec), signCls(chg)),
        chg != null ? h('span', { class: ['lg-v', signCls(chg)] }, fmtPct(chg)) : null,
        item('Vol', fmtCompact(k.volume))),
      values.length ? h('div', { class: 'lg-row' }, values) : null);
  }
  chart.subscribeCrosshairMove((param) => renderLegend(param.time ?? null));

  function setData(p, { fit = false } = {}) {
    current = p;
    byTime.clear();
    for (const k of p.candles) byTime.set(k.time, k);
    candle.setData(p.candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    volume.setData(p.candles.map((k) => ({ time: k.time, value: k.volume ?? 0, color: alpha(k.close >= k.open ? c.up : c.down, 0.32) })));
    for (const line of p.lines || []) {
      const entry = lineSeries.get(line.column);
      if (!entry) continue;
      if (line.kind === 'histogram') {
        entry.series.setData(line.data.map((d) => ({ time: d.time, value: d.value, color: alpha(d.value >= 0 ? c.up : c.down, 0.6) })));
      } else entry.series.setData(line.data);
    }
    const valid = new Set(p.candles.map((k) => k.time));
    const times = p.candles.map((k) => k.time);
    const snap = (t) => {
      if (valid.has(t)) return t;
      // place on the bar that contains the fill (first bar time >= t), else the last bar
      let lo = 0; let hi = times.length - 1; let ans = times[times.length - 1];
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (times[mid] >= t) { ans = times[mid]; hi = mid - 1; } else lo = mid + 1; }
      return ans;
    };
    const marks = (p.markers || []).filter((m) => times.length && m.time >= times[0] - 86400).map((m) => {
      const buy = String(m.side).toUpperCase() === 'BUY';
      return {
        time: snap(m.time), position: buy ? 'belowBar' : 'aboveBar', shape: buy ? 'arrowUp' : 'arrowDown',
        color: buy ? c.up : c.down, text: p.markerText === false || narrow ? '' : `${buy ? 'B' : 'S'} ${fmtInt(m.quantity)}`, size: 1,
      };
    }).sort((a, b) => a.time - b.time);
    markersApi.setMarkers(marks);
    if (fit) chart.timeScale().fitContent();
    renderLegend(null);
  }

  setData(payload, { fit: true });
  const bars = payload.candles.length;
  const show = Math.max(40, Math.min(160, Math.round(el.clientWidth / 7)));
  if (bars > show) chart.timeScale().setVisibleLogicalRange({ from: bars - show, to: bars + 3 });
  return { chart, setData, candle, dispose: () => { onDispose?.(); legend.remove(); chart.remove(); } };
}

// --------------------------------------------------------------------------- equity / drawdown

/**
 * lines: [{name, data:[{time,value}], color, style, width}] on pane 0, optional drawdown
 * (fraction values) as a baseline area on pane 1. Legend with visibility toggles.
 */
export function equityChart(el, { lines, drawdown, valueFormat = (v) => fmtCompact(v, 2), baseline, legend: showLegend = true } = {}) {
  const c = colors();
  const L = LWC();
  const all = lines.flatMap((l) => l.data);
  const chart = makeChart(el, { intraday: isIntraday(all) });
  const fmt = { type: 'custom', formatter: valueFormat, minMove: 0.01 };
  const series = [];
  for (const [i, line] of lines.entries()) {
    if (!line.data?.length) continue;
    const color = line.color || c.series[i % c.series.length];
    let s;
    if (baseline != null && i === 0) {
      s = chart.addSeries(L.BaselineSeries, {
        baseValue: { type: 'price', price: baseline },
        topLineColor: c.up, topFillColor1: alpha(c.up, 0.16), topFillColor2: alpha(c.up, 0.01),
        bottomLineColor: c.down, bottomFillColor1: alpha(c.down, 0.01), bottomFillColor2: alpha(c.down, 0.16),
        lineWidth: 2, priceFormat: fmt, priceLineVisible: true, priceLineStyle: 2, priceLineWidth: 1, priceLineColor: c.border2,
      }, 0);
    } else {
      s = chart.addSeries(L.LineSeries, {
        color, lineWidth: line.width || 2, lineStyle: line.style || 0,
        priceFormat: fmt, priceLineVisible: false, lastValueVisible: i === 0, crosshairMarkerRadius: 3,
      }, 0);
    }
    s.setData(line.data);
    series.push({ s, line, color: baseline != null && i === 0 ? c.up : color });
  }
  let dd = null;
  if (drawdown?.length) {
    dd = chart.addSeries(L.BaselineSeries, {
      baseValue: { type: 'price', price: 0 },
      topLineColor: 'transparent', topFillColor1: 'transparent', topFillColor2: 'transparent',
      bottomLineColor: alpha(c.down, 0.8), bottomFillColor1: alpha(c.down, 0.06), bottomFillColor2: alpha(c.down, 0.28),
      lineWidth: 1, priceFormat: { type: 'custom', formatter: (v) => `${v.toFixed(1)}%`, minMove: 0.01 },
      priceLineVisible: false, lastValueVisible: false,
    }, 1);
    dd.setData(drawdown.map((d) => ({ time: d.time, value: (d.value ?? 0) * 100 })));
    setStretch(chart, [3, 1]);
  }
  chart.timeScale().fitContent();

  const legend = h('div', { class: 'chart-legend chart-legend-interactive', hidden: !showLegend });
  (el.parentElement || el).insertBefore(legend, el);
  const valueEls = new Map();
  mount(legend, h('div', { class: 'lg-row' }, series.map(({ s, line, color }) => {
    const v = h('span', { class: 'lg-v' });
    valueEls.set(s, v);
    const b = h('button', {
      type: 'button', class: 'lg-toggle', 'aria-pressed': 'true', title: `Show/hide ${line.name}`,
      onclick: () => {
        const on = b.getAttribute('aria-pressed') !== 'true';
        b.setAttribute('aria-pressed', String(on));
        s.applyOptions({ visible: on });
      },
    }, h('span', { class: ['lg-swatch', line.style ? 'lg-swatch-dashed' : ''], style: { background: line.style ? 'transparent' : color, borderColor: color } }), h('span', { class: 'lg-k' }, line.name), v);
    return b;
  }), dd ? h('span', { class: 'lg-item' }, h('span', { class: 'lg-swatch', style: { background: alpha(c.down, 0.5) } }), h('span', { class: 'lg-k' }, 'Drawdown'), h('span', { class: 'lg-v' })) : null));
  const ddEl = dd ? legend.querySelector('.lg-item:last-child .lg-v') : null;
  const update = (param) => {
    for (const { s } of series) {
      const d = param?.time != null ? param.seriesData.get(s) : s.data()[s.data().length - 1];
      valueEls.get(s).textContent = d ? valueFormat(d.value) : '';
    }
    if (dd && ddEl) {
      const d = param?.time != null ? param.seriesData.get(dd) : dd.data()[dd.data().length - 1];
      ddEl.textContent = d ? `${d.value.toFixed(2)}%` : '';
    }
  };
  chart.subscribeCrosshairMove(update);
  update(null);
  return { chart, series, dd, dispose: () => { legend.remove(); chart.remove(); }, update };
}

// --------------------------------------------------------------------------- histogram (SVG)

function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw));
  const n = raw / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

/**
 * Distribution of values (fractions, e.g. trade returns) in bins aligned on zero; bars below
 * zero use the down colour, above the up colour. Hover shows the bin and its count.
 * Returns {dispose}. Redraws on resize.
 */
export function histogram(el, values, { fmt = (v) => fmtPct(v, 1), height = 220, unit = 'trades' } = {}) {
  const NS = 'http://www.w3.org/2000/svg';
  const vals = values.filter((v) => Number.isFinite(v));
  const tip = h('div', { class: 'viz-tip', hidden: true });
  const host = h('div', { class: 'viz' });
  el.replaceChildren(host, tip);
  if (!vals.length) return { dispose() {} };
  let lo = Math.min(...vals, 0); let hi = Math.max(...vals, 0);
  if (lo === hi) { lo -= 0.01; hi += 0.01; }
  const step = niceStep((hi - lo) / 16);
  const start = Math.floor(lo / step) * step;
  const nb = Math.max(1, Math.ceil((hi - start) / step + 1e-9));
  const bins = Array.from({ length: nb }, (_, i) => ({ from: start + i * step, to: start + (i + 1) * step, n: 0 }));
  for (const v of vals) bins[Math.min(nb - 1, Math.floor((v - start) / step + 1e-9))].n += 1;
  const maxN = Math.max(...bins.map((b) => b.n));
  const yStep = Math.max(1, niceStep(maxN / 4));
  const yMax = Math.ceil(maxN / yStep) * yStep;

  function draw() {
    const W = Math.max(240, host.clientWidth || el.clientWidth || 480);
    const H = height;
    const m = { l: 34, r: 8, t: 10, b: 24 };
    const pw = W - m.l - m.r; const ph = H - m.t - m.b;
    const slot = pw / nb;
    const bw = Math.min(24, Math.max(2, slot - 2));
    const x = (i) => m.l + i * slot + (slot - bw) / 2;
    const y = (n) => m.t + ph - (n / yMax) * ph;
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('height', H);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `Distribution of ${vals.length} ${unit}`);
    const mk = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text != null) e.textContent = text; svg.appendChild(e); return e; };
    for (let n = 0; n <= yMax; n += yStep) {
      mk('line', { x1: m.l, x2: W - m.r, y1: y(n), y2: y(n), class: n === 0 ? 'viz-base' : 'viz-grid' });
      mk('text', { x: m.l - 8, y: y(n) + 3.5, 'text-anchor': 'end', class: 'viz-axis' }, String(n));
    }
    const every = Math.max(1, Math.ceil(nb / Math.max(2, Math.floor(pw / 64))));
    for (let i = 0; i <= nb; i++) {
      const edge = start + i * step;
      if (Math.abs(edge) > 1e-12 && i % every !== 0) continue;
      mk('text', { x: m.l + i * slot, y: H - 6, 'text-anchor': 'middle', class: 'viz-axis' }, fmt(Math.abs(edge) < 1e-12 ? 0 : edge));
    }
    const css = getComputedStyle(document.documentElement);
    const up = css.getPropertyValue('--up').trim(); const down = css.getPropertyValue('--down').trim();
    bins.forEach((b, i) => {
      const mid = (b.from + b.to) / 2;
      const hit = mk('rect', { x: m.l + i * slot, y: m.t, width: slot, height: ph, class: 'viz-hit' });
      let bar = null;
      if (b.n) {
        const top = y(b.n); const bh = m.t + ph - top; const r = Math.min(4, bw / 2, bh);
        bar = mk('path', {
          d: `M${x(i)},${m.t + ph} V${top + r} Q${x(i)},${top} ${x(i) + r},${top} H${x(i) + bw - r} Q${x(i) + bw},${top} ${x(i) + bw},${top + r} V${m.t + ph} Z`,
          fill: mid < 0 ? down : up, class: 'viz-bar',
        });
      }
      const show = () => {
        bar?.classList.add('hover');
        mount(tip, h('b', {}, `${b.n} ${unit}`), h('div', {}, `${fmt(b.from)} to ${fmt(b.to)}`));
        tip.hidden = false;
        tip.style.left = `${m.l + (i + 0.5) * slot}px`;
        tip.style.top = `${b.n ? y(b.n) : m.t + ph}px`;
      };
      const hide = () => { bar?.classList.remove('hover'); tip.hidden = true; };
      hit.addEventListener('mouseenter', show);
      hit.addEventListener('mouseleave', hide);
    });
    host.replaceChildren(svg);
  }
  draw();
  let last = host.clientWidth;
  const ro = new ResizeObserver(() => { if (Math.abs(host.clientWidth - last) > 4) { last = host.clientWidth; draw(); } });
  ro.observe(host);
  return { dispose() { ro.disconnect(); } };
}
