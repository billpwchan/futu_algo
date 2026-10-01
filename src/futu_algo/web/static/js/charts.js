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
    grid: v('--chart-grid'), border: v('--border'), crosshair: v('--text-3'),
    up: v('--up'), down: v('--down'), accent: v('--accent'),
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--series-${i}`)),
    font: getComputedStyle(document.body).fontFamily,
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
  const chart = LWC().createChart(el, {
    autoSize: true,
    height,
    layout: {
      background: { type: 'solid', color: c.surface },
      textColor: c.text2,
      fontFamily: c.font,
      fontSize: 11,
      attributionLogo: false,
      panes: panes ? { separatorColor: c.border, separatorHoverColor: alpha(c.accent, 0.25), enableResize: true } : undefined,
    },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
    rightPriceScale: { borderColor: c.border },
    timeScale: { borderColor: c.border, timeVisible: intraday, secondsVisible: false, rightOffset: 4 },
    crosshair: {
      mode: LWC().CrosshairMode.Normal,
      vertLine: { color: c.crosshair, labelBackgroundColor: c.text2, style: 3 },
      horzLine: { color: c.crosshair, labelBackgroundColor: c.text2, style: 3 },
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
    wickUpColor: c.up, wickDownColor: c.down, priceFormat, priceLineVisible: true, priceLineStyle: 2,
  }, 0);
  const volume = chart.addSeries(L.HistogramSeries, {
    priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false,
  }, 1);
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
        color, lineWidth: pane === 0 ? 1.5 : 1.5, priceLineVisible: false, lastValueVisible: pane !== 0,
        crosshairMarkerRadius: 3, priceFormat: pane === 0 ? priceFormat : { type: 'price', precision: 2, minMove: 0.01 },
      }, pane);
      s._color = color;
    }
    lineSeries.set(line.column, { series: s, spec: line });
  }
  setStretch(chart, hasLower ? [5, 1.2, 1.8] : [5, 1.3]);
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
      if (found && found.time === k.time) values.push(h('span', { class: 'lg-item' }, h('span', { class: 'lg-swatch', style: { background: series._color || c.text3 } }), h('span', { class: 'lg-k' }, spec.label), h('span', { class: 'lg-v' }, fmtPrice(found.value, 2, spec.pane === 'price' ? prec : 2))));
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
    volume.setData(p.candles.map((k) => ({ time: k.time, value: k.volume ?? 0, color: alpha(k.close >= k.open ? c.up : c.down, 0.45) })));
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
export function equityChart(el, { lines, drawdown, valueFormat = (v) => fmtCompact(v, 2), baseline } = {}) {
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
        topLineColor: c.up, topFillColor1: alpha(c.up, 0.22), topFillColor2: alpha(c.up, 0.02),
        bottomLineColor: c.down, bottomFillColor1: alpha(c.down, 0.02), bottomFillColor2: alpha(c.down, 0.22),
        lineWidth: 2, priceFormat: fmt, priceLineVisible: false,
      }, 0);
    } else {
      s = chart.addSeries(L.LineSeries, {
        color, lineWidth: line.width || (i === 0 ? 2 : 1.5), lineStyle: line.style || 0,
        priceFormat: fmt, priceLineVisible: false, lastValueVisible: i === 0, crosshairMarkerRadius: 3,
      }, 0);
    }
    s.setData(line.data);
    series.push({ s, line, color: baseline != null && i === 0 ? c.accent : color });
  }
  let dd = null;
  if (drawdown?.length) {
    dd = chart.addSeries(L.BaselineSeries, {
      baseValue: { type: 'price', price: 0 },
      topLineColor: 'transparent', topFillColor1: 'transparent', topFillColor2: 'transparent',
      bottomLineColor: c.down, bottomFillColor1: alpha(c.down, 0.08), bottomFillColor2: alpha(c.down, 0.35),
      lineWidth: 1, priceFormat: { type: 'custom', formatter: (v) => `${v.toFixed(1)}%`, minMove: 0.01 },
      priceLineVisible: false, lastValueVisible: false,
    }, 1);
    dd.setData(drawdown.map((d) => ({ time: d.time, value: (d.value ?? 0) * 100 })));
    setStretch(chart, [3, 1]);
  }
  chart.timeScale().fitContent();

  const legend = h('div', { class: 'chart-legend chart-legend-interactive' });
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
