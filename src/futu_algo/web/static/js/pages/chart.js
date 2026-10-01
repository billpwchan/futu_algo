// Chart: candles + volume + strategy indicators + fill markers, live-updated on bar events.

import { h, mount, fmtPrice, fmtWhen, paramsText, normalizeSymbol, throttle, parseJSONMaybe, fmtInt } from '../core.js';
import { api } from '../api.js';
import { app, engine, go } from '../state.js';
import { card, dataTable, badge, btn, errorBox, loading, empty, select, kv } from '../ui.js';
import { TIMEFRAMES } from '../common.js';
import { candleChart } from '../charts.js';

const BAR_COUNTS = [100, 200, 400, 800, 1500];
const ACTION_TONE = { buy: 'good', sell: 'bad', hold: 'muted', warmup: 'info', skip: 'warn', error: 'bad' };

function knownSymbols() {
  const e = engine();
  const list = e ? e.symbols.map((s) => ({ symbol: s.symbol, name: s.name })) : (app.status?.trading?.symbols || []).map((s) => ({ symbol: s, name: '' }));
  return list;
}

export default {
  title: ({ params }) => (params[0] ? `Chart · ${params[0]}` : 'Chart'),
  async mount(root, { params, query, ctx }) {
    const defaultTf = app.status?.trading?.timeframe || 'DAY';
    const symbol = normalizeSymbol(params[0] || '') || knownSymbols()[0]?.symbol || '';
    const tf = (query.get('tf') || defaultTf).toUpperCase();
    const bars = Number(query.get('bars')) || 400;
    const nav = (next) => {
      const s = next.symbol ?? symbol; const t = next.tf ?? tf; const b = next.bars ?? bars;
      const q = new URLSearchParams();
      if (t !== defaultTf) q.set('tf', t);
      if (b !== 400) q.set('bars', String(b));
      go(`#/chart/${encodeURIComponent(s)}${q.toString() ? `?${q}` : ''}`);
    };

    // ---------------------------------------------------------------- toolbar
    const symInput = h('input', { class: 'input input-sym mono', value: symbol, list: 'chart-syms', 'aria-label': 'Symbol', placeholder: 'HK.00700', autocomplete: 'off', spellcheck: 'false' });
    const datalist = h('datalist', { id: 'chart-syms' }, knownSymbols().map((s) => h('option', { value: s.symbol }, s.name)));
    const tfOptions = TIMEFRAMES.includes(tf) ? TIMEFRAMES : [tf, ...TIMEFRAMES];
    const tfSel = select(tfOptions.map((t) => ({ value: t, label: t === defaultTf ? `${t} (live)` : t })), tf, { 'aria-label': 'Timeframe', onchange: (e) => nav({ tf: e.target.value }) });
    const barSel = select(BAR_COUNTS.map((n) => ({ value: n, label: `${n} bars` })), bars, { 'aria-label': 'Bar count', onchange: (e) => nav({ bars: Number(e.target.value) }) });
    const sourceBadge = h('span', { class: 'toolbar-meta' });
    const toolbar = h('form', {
      class: 'toolbar chart-toolbar',
      onsubmit: (e) => { e.preventDefault(); const s = normalizeSymbol(symInput.value); if (s) nav({ symbol: s }); },
    },
    h('div', { class: 'toolbar-group' }, symInput, datalist, btn('Go', { type: 'submit', tone: 'secondary' })),
    h('div', { class: 'toolbar-group' }, tfSel, barSel, btn('', { iconName: 'refresh', tone: 'ghost', title: 'Reload', attrs: { 'aria-label': 'Reload chart' }, onclick: () => load(true) })),
    sourceBadge);

    const chartEl = h('div', { class: 'chart chart-lg' });
    const chartHolder = h('div', { class: 'chart-wrap' }, loading('Loading chart…'));
    const infoBox = h('div');
    const showHolds = h('input', { type: 'checkbox', id: 'show-holds' });
    const signals = dataTable({
      caption: 'Signals',
      emptyText: 'No signals recorded for this symbol',
      dense: true,
      maxHeight: '360px',
      columns: [
        { key: 'bar_time', label: 'Bar', render: (r) => h('span', { class: 'num' }, fmtWhen(r.bar_time)) },
        { key: 'strategy', label: 'Strategy', cls: 'mono hide-sm' },
        { key: 'action', label: 'Action', render: (r) => badge(r.action, ACTION_TONE[r.action] || 'neutral') },
        { key: 'signal', label: 'Signal', num: true, render: (r) => (r.signal == null ? '—' : String(r.signal)) },
        { key: 'close', label: 'Close', num: true, render: (r) => fmtPrice(r.close), cls: 'mono' },
        { key: 'detail', label: 'Detail', cls: 'truncate', value: (r) => { const d = parseJSONMaybe(r.detail); return (d && typeof d === 'object' ? d.detail : d) || ''; } },
      ],
    });

    if (!symbol) {
      mount(root, toolbar, card({ body: empty('Pick a symbol', 'Type a symbol such as HK.00700, or open one from the watchlist.') }));
      return;
    }

    mount(root,
      toolbar,
      card({ body: chartHolder, cls: 'card-chart', flush: true }),
      h('div', { class: 'grid-2-1' },
        card({
          title: 'Signals', subtitle: 'Decisions recorded by the live engine',
          actions: h('label', { class: 'check' }, showHolds, h('span', {}, 'Show holds')),
          body: signals.el, flush: true,
        }),
        card({ title: 'Strategy', body: infoBox })));

    let view = null;
    let live = false;
    ctx.add(() => view?.dispose());

    async function load(fit = false) {
      try {
        const data = await api(`/api/chart/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(tf)}&bars=${bars}`);
        if (!ctx.alive) return;
        live = data.source === 'live';
        mount(sourceBadge,
          live ? badge('live', 'good', { title: 'Engine window; updates on every bar' }) : badge('cache', 'neutral', { title: 'Loaded from the local bar cache' }),
          h('span', {}, ` ${fmtInt(data.candles.length)} bars`));
        if (!data.candles.length) { mount(chartHolder, empty('No bars', `No ${tf} bars for ${symbol}.`)); return; }
        if (!window.LightweightCharts) { mount(chartHolder, empty('Chart library unavailable', 'The vendored chart script failed to load.')); return; }
        const payload = { ...data, symbol };
        if (!view) {
          mount(chartHolder, chartEl);
          view = candleChart(chartEl, payload);
        } else view.setData(payload, { fit });
        const st = data.strategy || {};
        mount(infoBox, kv([
          ['Strategy', h('span', {}, st.title || st.name, ' ', h('span', { class: 'mono muted' }, `(${st.name})`))],
          ['Parameters', h('span', { class: 'mono' }, paramsText(st.params) || '—')],
          ['Warm-up', `${fmtInt(st.warmup_bars)} bars`],
          ['Look-ahead safe', st.lookahead_safe === false ? badge('no', 'bad') : badge('yes', 'good')],
          ['Indicators', (data.lines || []).map((l) => l.label).join(', ') || '—'],
          ['Fills on chart', fmtInt(data.markers?.length || 0)],
          ['Timeframe', data.timeframe],
        ]));
      } catch (err) {
        if (!ctx.alive) return;
        if (!view) mount(chartHolder, errorBox(err, () => load(true)));
        else throw err;
      }
    }
    async function loadSignals() {
      const rows = await api(`/api/signals?symbol=${encodeURIComponent(symbol)}&limit=150&actions_only=${!showHolds.checked}`);
      if (ctx.alive) signals.update(rows || []);
    }
    showHolds.addEventListener('change', () => loadSignals().catch(() => {}));

    await Promise.all([load(true), loadSignals().catch(() => {})]);
    const refresh = throttle(() => { if (live) load().catch(() => {}); loadSignals().catch(() => {}); }, 2500);
    ctx.on('bar', (ev) => { if (ev.symbol === symbol) refresh(); });
    ctx.on('fill', (ev) => { if (ev.symbol === symbol) refresh(); });
    ctx.on('signal', (ev) => { if (ev.symbol === symbol) loadSignals().catch(() => {}); });
  },
};
