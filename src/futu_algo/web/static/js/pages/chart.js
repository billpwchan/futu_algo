// Chart: candles + volume + strategy indicators + fill markers, live-updated on bar events,
// beside a quote panel, the strategy and the engine's recorded decisions.

import { h, mount, icon, fmtPrice, fmtWhen, normalizeSymbol, throttle, parseJSONMaybe, fmtInt, fmtCompact, fmtPct, signCls, fmtChartTime } from '../core.js';
import { api } from '../api.js';
import { app, engine, go } from '../state.js';
import { card, badge, btn, errorBox, loading, empty, select, kv, segmented, delta, switchControl } from '../ui.js';
import { TIMEFRAMES } from '../common.js';
import { candleChart } from '../charts.js';

const BAR_COUNTS = [100, 200, 400, 800, 1500];
const ACTION_TONE = { buy: 'good', sell: 'bad', hold: 'muted', warmup: 'info', skip: 'warn', error: 'bad' };

function knownSymbols() {
  const e = engine();
  return e ? e.symbols.map((s) => ({ symbol: s.symbol, name: s.name })) : (app.status?.trading?.symbols || []).map((s) => ({ symbol: s, name: '' }));
}

export default {
  title: ({ params }) => (params[0] ? normalizeSymbol(params[0]) : 'Chart'),
  head: () => false,
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
    const known = knownSymbols();
    const name = known.find((k) => k.symbol === symbol)?.name || '';

    // ---------------------------------------------------------------- toolbar
    const symInput = h('input', { class: 'input input-sm input-sym mono', value: symbol, list: 'chart-syms', 'aria-label': 'Symbol', placeholder: 'HK.00700', autocomplete: 'off', spellcheck: 'false' });
    const datalist = h('datalist', { id: 'chart-syms' }, known.map((s) => h('option', { value: s.symbol }, s.name)));
    const tfOptions = TIMEFRAMES.includes(tf) ? TIMEFRAMES : [tf, ...TIMEFRAMES];
    const tfSeg = segmented(tfOptions.map((t) => ({ value: t, label: t === 'DAY' ? 'D' : t === 'WEEK' ? 'W' : t === 'MON' ? 'M' : t.replace('M', 'm').replace('H', 'h') })), tf, (v) => nav({ tf: v }), { label: 'Timeframe', size: 'sm', cls: 'segmented-mono' });
    const barSel = select(BAR_COUNTS.map((n) => ({ value: n, label: `${n} bars` })), bars, { class: 'input input-sm', 'aria-label': 'Bar count', onchange: (e) => nav({ bars: Number(e.target.value) }) });
    const sourceBadge = h('span', { class: 'toolbar-meta' });
    const toolbar = h('div', { class: 'chart-toolbar' },
      h('form', { onsubmit: (e) => { e.preventDefault(); const s = normalizeSymbol(symInput.value); if (s) nav({ symbol: s }); } },
        h('div', { class: 'input-icon' }, icon('search', 14), symInput), datalist),
      tfSeg, barSel,
      h('div', { class: 'tb-end' }, sourceBadge,
        btn('', { size: 'sm', iconName: 'refresh', tone: 'ghost', title: 'Reload', attrs: { 'aria-label': 'Reload chart' }, onclick: () => load(true) })));

    if (!symbol) {
      mount(root, card({ body: h('div', {}, toolbar, empty('Pick a symbol', 'Type a code such as 700 or HK.00700, or open one from the watchlist.', null, 'candles')), flush: true }));
      return;
    }

    const chartEl = h('div', { class: 'chart chart-xl' });
    const chartHolder = h('div', { class: 'chart-wrap' }, loading('Loading chart…'));
    const quoteBox = h('div', { class: 'quote' }, loading());
    const infoBox = h('div');
    const signalList = h('div', { class: 'signal-list' });
    const holds = switchControl('Holds', false, { onchange: () => loadSignals().catch(() => {}) });

    mount(root, h('div', { class: 'chart-layout' },
      h('div', { class: 'chart-main' }, card({ body: h('div', {}, toolbar, chartHolder), flush: true, cls: 'card-chart-main' })),
      h('div', { class: 'chart-side' },
        card({ body: quoteBox }),
        card({ title: 'Strategy', body: infoBox }),
        card({ title: 'Decisions', actions: holds, body: signalList, flush: true }))));

    function renderQuote(data) {
      const c = data.candles;
      const k = c[c.length - 1];
      if (!k) { mount(quoteBox, empty('No bars')); return; }
      const day = Math.floor(k.time / 86400);
      const firstToday = c.findIndex((x) => Math.floor(x.time / 86400) === day);
      const intraday = c.some((x) => x.time % 86400 !== 0);
      const ref = intraday ? (firstToday > 0 ? c[firstToday - 1].close : c[0].open) : c[c.length - 2]?.close;
      const chg = ref ? k.close / ref - 1 : null;
      const sessionBars = intraday ? c.slice(Math.max(0, firstToday)) : [k];
      const hi = Math.max(...sessionBars.map((x) => x.high));
      const lo = Math.min(...sessionBars.map((x) => x.low));
      const vol = sessionBars.reduce((s, x) => s + (x.volume || 0), 0);
      mount(quoteBox,
        h('div', { class: 'quote-sym' }, h('span', { class: 'sym' }, symbol), data.source === 'live' ? badge('live', 'good', { class: 'badge badge-good badge-dot' }) : badge('cache', 'neutral')),
        name ? h('div', { class: 'quote-name' }, name) : null,
        h('div', { class: 'quote-last' }, fmtPrice(k.close)),
        h('div', { class: 'row' }, delta(chg, fmtPct(chg)), h('span', { class: ['small', signCls(chg)] }, ref ? `${k.close - ref >= 0 ? '+' : '−'}${fmtPrice(Math.abs(k.close - ref))}` : ''), h('span', { class: 'muted small' }, intraday ? 'vs prev. close' : 'vs prev. bar')),
        h('div', { class: 'ohlc' },
          kv([['Open', fmtPrice(sessionBars[0].open)], ['High', fmtPrice(hi)]]),
          kv([['Low', fmtPrice(lo)], ['Volume', fmtCompact(vol)]])),
        h('div', { class: 'muted small', style: { marginTop: '8px' } }, `Last bar ${fmtChartTime(k.time, intraday)}`));
    }

    let view = null;
    let live = false;
    ctx.add(() => view?.dispose());

    async function load(fit = false) {
      try {
        const data = await api(`/api/chart/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(tf)}&bars=${bars}`);
        if (!ctx.alive) return;
        live = data.source === 'live';
        mount(sourceBadge, live
          ? badge('live', 'good', { class: 'badge badge-good badge-dot', title: `Engine window, ${fmtInt(data.candles.length)} bars; updates on every bar` })
          : badge('cache', 'neutral', { title: `Local bar cache, ${fmtInt(data.candles.length)} bars` }));
        renderQuote(data);
        if (!data.candles.length) { mount(chartHolder, empty('No bars', `No ${tf} bars for ${symbol}. Fetch history on the Data page.`, h('a', { class: 'btn', href: '#/data' }, 'Open Data'), 'candles')); return; }
        if (!window.LightweightCharts) { mount(chartHolder, empty('Chart library unavailable', 'The vendored chart script failed to load.')); return; }
        const payload = { ...data, symbol };
        if (!view) {
          mount(chartHolder, chartEl);
          view = candleChart(chartEl, payload);
        } else view.setData(payload, { fit });
        const st = data.strategy || {};
        mount(infoBox, kv([
          ['Strategy', h('span', {}, st.title || st.name)],
          ['Name', h('span', { class: 'mono' }, st.name || '—')],
          ...Object.entries(st.params || {}).map(([k, v]) => [h('span', { class: 'mono small' }, k), h('span', { class: 'mono' }, String(v))]),
          ['Warm-up', `${fmtInt(st.warmup_bars)} bars`],
          ['Look-ahead', st.lookahead_safe === false ? badge('unsafe', 'bad') : badge('safe', 'good')],
          ['Indicators', (data.lines || []).map((l) => l.label).join(', ') || '—'],
          ['Fills on chart', fmtInt(data.markers?.length || 0)],
        ]));
      } catch (err) {
        if (!ctx.alive) return;
        if (!view) mount(chartHolder, errorBox(err, () => load(true)));
        else throw err;
      }
    }

    async function loadSignals() {
      const rows = await api(`/api/signals?symbol=${encodeURIComponent(symbol)}&limit=150&actions_only=${!holds.input.checked}`);
      if (!ctx.alive) return;
      if (!rows?.length) { mount(signalList, h('p', { class: 'muted small card-pad' }, holds.input.checked ? 'No decisions recorded for this symbol yet.' : 'No buy or sell decisions yet. Turn on Holds to see every bar.')); return; }
      mount(signalList, rows.map((r) => {
        const d = parseJSONMaybe(r.detail);
        const detail = (d && typeof d === 'object' ? d.detail : d) || (r.close != null ? `close ${fmtPrice(r.close)}` : '');
        return h('div', { class: 'signal-item' },
          badge(r.action, ACTION_TONE[r.action] || 'neutral'),
          h('span', { class: 'signal-detail', title: detail }, detail),
          h('span', { class: 'signal-time' }, fmtWhen(r.bar_time)));
      }));
    }

    await Promise.all([load(true), loadSignals().catch(() => {})]);
    const refresh = throttle(() => { if (live) load().catch(() => {}); loadSignals().catch(() => {}); }, 2500);
    ctx.on('bar', (ev) => { if (ev.symbol === symbol) refresh(); });
    ctx.on('fill', (ev) => { if (ev.symbol === symbol) refresh(); });
    ctx.on('signal', (ev) => { if (ev.symbol === symbol) loadSignals().catch(() => {}); });
  },
};
