// Watchlist: a quote board of every symbol the engine trades: session sparkline and change,
// strategy, warm-up progress, the last decision and the position.

import { h, mount, fmtPrice, fmtInt, fmtPct, fmtWhen, paramsText, throttle, signCls } from '../core.js';
import { api } from '../api.js';
import { app, engine, go, actions } from '../state.js';
import { dataTable, empty, badge, btn, busy, card, kpi, sparkline, delta, meter } from '../ui.js';
import { symLink, symCell } from '../common.js';

const ACTION_TONE = { buy: 'good', sell: 'bad', hold: 'muted', warmup: 'info', skip: 'warn', error: 'bad', exit: 'bad' };
const SPARK_BARS = 240;

/** Closes of the most recent trading day in a candle payload (epoch secs of HK wall time). */
function sessionCloses(candles) {
  if (!candles?.length) return { closes: [], open: null };
  const day = Math.floor(candles[candles.length - 1].time / 86400);
  const today = candles.filter((k) => Math.floor(k.time / 86400) === day);
  const intraday = today.length > 1 ? today : candles.slice(-60);
  return { closes: intraday.map((k) => k.close), open: intraday[0]?.open ?? null, prevClose: candles[candles.length - today.length - 1]?.close ?? null };
}

export default {
  title: () => 'Watchlist',
  mount(root, { ctx, actions: headActions, setDesc }) {
    const quotes = new Map(); // symbol -> {closes, ref, last, chg}

    const table = dataTable({
      caption: 'Watchlist',
      emptyText: 'No symbols',
      sort: { key: 'symbol', dir: 'asc' },
      onRowClick: (r) => go(`#/chart/${encodeURIComponent(r.symbol)}`),
      rowTitle: (r) => `Open the ${r.symbol} chart`,
      rowClass: (r) => (r.position ? 'row-held' : null),
      columns: [
        { key: 'symbol', label: 'Symbol', render: (r) => symCell(r.symbol, r.name) },
        { key: 'close', label: 'Last', num: true, value: (r) => r.last_bar?.close, render: (r) => h('span', { class: 'wl-last' }, fmtPrice(r.last_bar?.close)) },
        {
          key: 'chg', label: 'Session', num: true, value: (r) => quotes.get(r.symbol)?.chg,
          render: (r) => { const q = quotes.get(r.symbol); return q?.chg != null ? delta(q.chg, fmtPct(q.chg)) : null; },
        },
        {
          key: 'spark', label: 'Intraday', sortable: false, cls: 'hide-sm',
          render: (r) => { const q = quotes.get(r.symbol); return q ? h('span', { class: 'wl-spark' }, sparkline(q.closes, { tone: signCls(q.chg), baseline: q.ref, width: 120, height: 30 })) : h('span', { class: 'muted small' }, '…'); },
        },
        {
          key: 'strategy', label: 'Strategy',
          render: (r) => h('div', { class: 'cell-stack' }, h('span', { class: 'mono' }, r.strategy), h('span', { class: 'cell-sub mono truncate', style: { maxWidth: '240px' }, title: paramsText(r.params) }, paramsText(r.params))),
        },
        {
          key: 'bars', label: 'Warm-up', num: true, value: (r) => r.bars / Math.max(1, r.warmup), cls: 'hide-sm',
          render: (r) => {
            const title = `${fmtInt(r.bars)} bars loaded, ${fmtInt(r.warmup)} needed`;
            if (r.bars > r.warmup) return h('span', { class: 'muted small', title }, 'ready');
            return h('span', { class: 'warm', title }, h('span', { class: 'text-warn small' }, `${fmtInt(r.bars)}/${fmtInt(r.warmup)}`),
              meter(r.bars / Math.max(1, r.warmup), { warnAt: 2, badAt: 2, label: 'Warm-up' }));
          },
        },
        {
          key: 'decision', label: 'Last decision', value: (r) => r.last_decision?.action,
          render: (r) => {
            const d = r.last_decision;
            if (!d) return null;
            return h('div', { class: 'cell-stack' }, h('span', {}, badge(d.action, ACTION_TONE[d.action] || 'neutral', { class: `badge badge-${ACTION_TONE[d.action] || 'neutral'} badge-dot` })),
              h('span', { class: 'cell-sub truncate', title: d.detail || '' }, `${fmtWhen(d.bar_time)}${d.detail ? ` · ${d.detail}` : ''}`));
          },
        },
        {
          key: 'position', label: 'Position', num: true,
          render: (r) => h('span', { class: 'cell-inline', style: { justifyContent: 'flex-end' } },
            r.blocked ? badge('re-entry blocked', 'warn', { title: 'Re-entry is blocked until the strategy issues a fresh buy signal' }) : null,
            r.position ? h('strong', {}, fmtInt(r.position)) : h('span', { class: 'muted' }, '—')),
        },
      ],
    });
    const body = h('div');
    const stats = h('div', { class: 'kpis' });
    mount(root, stats, body);
    let decisions = { buy: 0, sell: 0 };

    function renderStats(e) {
      if (!e) { stats.hidden = true; return; }
      stats.hidden = false;
      const qs = e.symbols.map((s) => quotes.get(s.symbol)?.chg).filter((v) => v != null);
      const adv = qs.filter((v) => v > 0).length;
      const dec = qs.filter((v) => v < 0).length;
      const ready = e.symbols.filter((s) => s.bars > s.warmup).length;
      mount(stats,
        kpi('Universe', fmtInt(e.symbols.length), { sub: `${e.timeframe} bars` }),
        kpi('Held', fmtInt(e.symbols.filter((s) => s.position).length), { sub: `${e.symbols.filter((s) => s.blocked).length} awaiting a fresh signal` }),
        kpi('Breadth', h('span', {}, h('span', { class: 'up' }, fmtInt(adv)), h('span', { class: 'muted' }, ' / '), h('span', { class: 'down' }, fmtInt(dec))), { sub: 'advancing / declining' }),
        kpi('Decisions today', h('span', {}, h('span', { class: 'up' }, fmtInt(decisions.buy)), h('span', { class: 'muted' }, ' / '), h('span', { class: 'down' }, fmtInt(decisions.sell))), { sub: 'buy / sell' }),
        kpi('Warmed up', `${fmtInt(ready)} / ${fmtInt(e.symbols.length)}`, { extra: meter(ready / Math.max(1, e.symbols.length), { warnAt: 2, badAt: 2, label: 'Warmed up' }) }));
    }
    async function loadDecisions() {
      const e = engine();
      if (!e) return;
      try {
        const rows = await api('/api/signals?limit=1000&actions_only=true');
        const day = e.trading_day;
        const today = (rows || []).filter((r) => !day || String(r.bar_time).startsWith(day));
        decisions = { buy: today.filter((r) => r.action === 'buy').length, sell: today.filter((r) => r.action === 'sell' || r.action === 'exit').length };
        if (ctx.alive) renderStats(engine());
      } catch { /* keep the previous counts */ }
    }

    async function loadQuotes(symbols, tf) {
      await Promise.all(symbols.map(async (sym) => {
        try {
          const d = await api(`/api/chart/${encodeURIComponent(sym)}?timeframe=${encodeURIComponent(tf)}&bars=${SPARK_BARS}`);
          const { closes, open, prevClose } = sessionCloses(d.candles);
          const ref = prevClose ?? open;
          const last = closes[closes.length - 1];
          quotes.set(sym, { closes, ref, chg: ref && last ? last / ref - 1 : null });
        } catch { /* no cached bars for this symbol: leave the cells empty */ }
      }));
      if (ctx.alive) render();
    }

    function render() {
      const e = engine();
      mount(headActions, h('a', { href: '#/chart', class: 'btn btn-secondary' }, 'Open chart'));
      if (!e) {
        renderStats(null);
        const syms = app.status?.trading?.symbols || [];
        setDesc('The engine is not running; live strategy state appears once it starts');
        mount(body, card({
          title: 'Configured universe',
          subtitle: `${syms.length} symbols in trading.universe`,
          actions: btn('Start engine', { tone: 'primary', iconName: 'play', onclick: (ev) => busy(ev.currentTarget, actions.start) }),
          body: syms.length
            ? h('div', { class: 'sym-grid' }, syms.map((s) => h('a', { class: 'sym-tile', href: `#/chart/${encodeURIComponent(s)}` }, symLink(s), h('span', { class: 'muted small' }, 'Open chart →'))))
            : empty('No symbols configured', 'Add symbols under trading.universe in the config.'),
        }));
        return;
      }
      renderStats(e);
      const held = e.symbols.filter((s) => s.position).length;
      setDesc(`${e.symbols.length} symbols on ${e.timeframe} bars · ${held} held · ${e.state === 'running' ? 'live' : e.state}`);
      if (!body.contains(table.el)) mount(body, card({ body: table.el, flush: true }));
      table.update(e.symbols);
    }
    render();
    const e0 = engine();
    const tf = e0?.timeframe || app.status?.trading?.timeframe || 'DAY';
    const syms = e0 ? e0.symbols.map((s) => s.symbol) : app.status?.trading?.symbols || [];
    if (e0) { loadQuotes(syms, tf); loadDecisions(); }
    const refreshQuotes = throttle(() => loadQuotes(syms, tf), 5000);
    ctx.onStatus(render);
    ctx.on('bar', () => { if (engine()) refreshQuotes(); });
    ctx.on('signal', throttle(loadDecisions, 3000));
  },
};
