import { t as translate } from '../i18n.js';
// Chart: candles + volume + strategy indicators + fill markers, live-updated on bar events,
// beside a quote panel, the strategy and the engine's recorded decisions.

import { h, mount, icon, fmtPrice, fmtWhen, normalizeSymbol, throttle, parseJSONMaybe, fmtInt, fmtCompact, fmtPct, signCls, fmtChartTime } from '../core.js';
import { api } from '../api.js';
import { app, engine, go } from '../state.js';
import { card, badge, btn, errorBox, loading, empty, select, kv, segmented, delta, switchControl } from '../ui.js';
import { TIMEFRAMES } from '../common.js';
import { candleChart } from '../charts.js';
import { watchlistButton } from '../watchlist-store.js';

const BAR_COUNTS = [100, 200, 400, 800, 1500];
const ACTION_TONE = { buy: 'good', sell: 'bad', hold: 'muted', warmup: 'info', skip: 'warn', error: 'bad' };

function knownSymbols() {
  const e = engine();
  return e ? e.symbols.map((s) => ({ symbol: s.symbol, name: s.name })) : (app.status?.trading?.symbols || []).map((s) => ({ symbol: s, name: '' }));
}

export default {
  title: ({ params }) => (params[0] ? normalizeSymbol(params[0]) : translate('Chart')),
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
    const symInput = h('input', { class: 'input input-sm input-sym mono', value: symbol, list: 'chart-syms', 'aria-label': translate('Symbol'), placeholder: 'HK.00700', autocomplete: 'off', spellcheck: 'false' });
    const datalist = h('datalist', { id: 'chart-syms' }, known.map((s) => h('option', { value: s.symbol }, s.name)));
    const tfOptions = TIMEFRAMES.includes(tf) ? TIMEFRAMES : [tf, ...TIMEFRAMES];
    const tfSeg = segmented(tfOptions.map((t) => ({ value: t, label: t === 'DAY' ? 'D' : t === 'WEEK' ? 'W' : t === 'MON' ? 'M' : t.replace('M', 'm').replace('H', 'h') })), tf, (v) => nav({ tf: v }), { label: translate('Timeframe'), size: 'sm', cls: 'segmented-mono' });
    const barSel = select(BAR_COUNTS.map((n) => ({ value: n, label: translate("{0} bars", { 0: n }) })), bars, { class: 'input input-sm', 'aria-label': translate("Bar count"), onchange: (e) => nav({ bars: Number(e.target.value) }) });
    const sourceBadge = h('span', { class: 'toolbar-meta' });
    const toolbar = h('div', { class: 'chart-toolbar' },
      h('form', { onsubmit: (e) => { e.preventDefault(); const s = normalizeSymbol(symInput.value); if (s) nav({ symbol: s }); } },
        h('div', { class: 'input-icon' }, icon('search', 14), symInput), datalist),
      tfSeg, barSel,
      h('div', { class: 'tb-end' }, sourceBadge,
        btn('', { size: 'sm', iconName: 'refresh', tone: 'ghost', title: translate('Reload'), attrs: { 'aria-label': translate("Reload chart") }, onclick: () => load(true) })));

    if (!symbol) {
      mount(root, card({ body: h('div', {}, toolbar, empty(translate("Pick a symbol"), translate("Type a code such as 700 or HK.00700, or open one from the watchlist."), null, 'candles')), flush: true }));
      return;
    }

    const chartEl = h('div', { class: 'chart chart-xl' });
    const chartHolder = h('div', { class: 'chart-wrap' }, loading(translate("Loading chart…")));
    const quoteBox = h('div', { class: 'quote' }, loading());
    const infoBox = h('div');
    const signalList = h('div', { class: 'signal-list' });
    const holds = switchControl(translate("Holds"), false, { onchange: () => loadSignals().catch(() => {}) });

    mount(root, h('div', { class: 'chart-layout' },
      h('div', { class: 'chart-main' }, card({ body: h('div', {}, toolbar, chartHolder), flush: true, cls: 'card-chart-main' })),
      h('div', { class: 'chart-side' },
        card({ body: quoteBox }),
        card({ title: translate('Strategy'), body: infoBox }),
        card({ title: translate("Decisions"), actions: holds, body: signalList, flush: true }))));

    function renderQuote(data) {
      const c = data.candles;
      const k = c[c.length - 1];
      if (!k) { mount(quoteBox, empty(translate("No bars"))); return; }
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
        h('div', { class: 'quote-sym' }, h('span', { class: 'sym' }, symbol), data.source === 'live' ? badge(translate('live'), 'good', { class: 'badge badge-good badge-dot' }) : badge(translate('cache'), 'neutral'), watchlistButton(symbol, data.name || name)),
        name ? h('div', { class: 'quote-name' }, name) : null,
        h('div', { class: 'quote-last' }, fmtPrice(k.close)),
        h('div', { class: 'row' }, delta(chg, fmtPct(chg)), h('span', { class: ['small', signCls(chg)] }, ref ? `${k.close - ref >= 0 ? '+' : '−'}${fmtPrice(Math.abs(k.close - ref))}` : ''), h('span', { class: 'muted small' }, intraday ? translate("vs prev. close") : translate("vs prev. bar"))),
        h('div', { class: 'ohlc' },
          kv([[translate('Open'), fmtPrice(sessionBars[0].open)], [translate("High"), fmtPrice(hi)]]),
          kv([[translate("Low"), fmtPrice(lo)], [translate("Volume"), fmtCompact(vol)]])),
        h('div', { class: 'muted small', style: { marginTop: '8px' } }, translate("Last bar {0}", { 0: fmtChartTime(k.time, intraday) })));
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
          ? badge(translate('live'), 'good', { class: 'badge badge-good badge-dot', title: translate("Engine window, {0} bars; updates on every bar", { 0: fmtInt(data.candles.length) }) })
          : badge(translate('cache'), 'neutral', { title: translate("Local bar cache, {0} bars", { 0: fmtInt(data.candles.length) }) }));
        renderQuote(data);
        if (!data.candles.length) { mount(chartHolder, empty(translate("No bars"), translate("No {0} bars for {1}. Fetch history on the Data page.", { 0: tf, 1: symbol }), h('a', { class: 'btn', href: '#/data' }, translate("Open Data")), 'candles')); return; }
        if (!window.LightweightCharts) { mount(chartHolder, empty(translate("Chart library unavailable"), translate("The vendored chart script failed to load."))); return; }
        const payload = { ...data, symbol };
        if (!view) {
          mount(chartHolder, chartEl);
          view = candleChart(chartEl, payload);
        } else view.setData(payload, { fit });
        const st = data.strategy || {};
        mount(infoBox, kv([
          [translate('Strategy'), h('span', {}, st.title || st.name)],
          [translate("Name"), h('span', { class: 'mono' }, st.name || '—')],
          ...Object.entries(st.params || {}).map(([k, v]) => [h('span', { class: 'mono small' }, k), h('span', { class: 'mono' }, String(v))]),
          [translate('Warm-up'), translate("{0} bars", { 0: fmtInt(st.warmup_bars) })],
          [translate("Look-ahead"), st.lookahead_safe === false ? badge(translate("unsafe"), 'bad') : badge(translate("safe"), 'good')],
          [translate("Indicators"), (data.lines || []).map((l) => l.label).join(', ') || '—'],
          [translate("Fills on chart"), fmtInt(data.markers?.length || 0)],
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
      if (!rows?.length) { mount(signalList, h('p', { class: 'muted small card-pad' }, holds.input.checked ? translate("No decisions recorded for this symbol yet.") : translate("No buy or sell decisions yet. Turn on Holds to see every bar."))); return; }
      mount(signalList, rows.map((r) => {
        const d = parseJSONMaybe(r.detail);
        const detail = (d && typeof d === 'object' ? d.detail : d) || (r.close != null ? translate("close {0}", { 0: fmtPrice(r.close) }) : '');
        return h('div', { class: 'signal-item' },
          badge(translate(r.action), ACTION_TONE[r.action] || 'neutral'),
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
