// Dashboard: engine controls, account hero with the intraday equity curve, allocation,
// positions, working intents, open orders, fills and the live activity timeline.

import { h, mount, storage, fmtMoney, fmtSignedMoney, fmtPct, fmtInt, fmtPrice, signCls, hkEpoch, fmtCompact, throttle } from '../core.js';
import { api, stream, KINDS } from '../api.js';
import { app, actions, engine, engineRunning, serverNow, refreshStatus, envLabel } from '../state.js';
import { card, btn, busy, dataTable, empty, chips, skeleton, errorBox, delta } from '../ui.js';
import { symLink, symCell, sideBadge, stateBadge, timeCell, feedItem } from '../common.js';
import { equityChart } from '../charts.js';

const FEED_KEY = 'futu_algo.feedKinds';

function plCell(v, pct) {
  return h('span', { class: ['pl-cell', signCls(v)] }, fmtSignedMoney(v), pct != null ? h('small', {}, fmtPct(pct)) : null);
}

function weightCell(frac) {
  if (!Number.isFinite(frac)) return null;
  return h('span', { class: 'cell-bar' }, h('span', { class: 'num' }, fmtPct(frac, 1, false)),
    h('span', { class: 'cell-bar-track', 'aria-hidden': 'true' }, h('span', { class: 'cell-bar-fill', style: { width: `${Math.min(100, frac * 100).toFixed(1)}%` } })));
}

function heroValue(v, ccy) {
  const [int, dec] = fmtMoney(v).split('.');
  return h('div', { class: 'hero-value' }, int, dec ? h('span', { class: 'dec' }, `.${dec}`) : null, h('span', { class: 'ccy' }, ccy || 'HKD'));
}

function mini(label, value, cls) {
  return h('div', { class: 'mini' }, h('div', { class: 'mini-label' }, label), h('div', { class: ['mini-value', cls] }, value));
}

export default {
  title: () => 'Dashboard',
  async mount(root, { ctx, actions: headActions, setDesc }) {
    // ---------------------------------------------------------------- layout
    const heroBox = h('div', {}, skeleton(3));
    const chartBox = h('div', { class: 'chart chart-sm' });
    const chartEmpty = h('div', { class: 'chart-empty', hidden: true });
    const chartWrap = h('div', { class: 'chart-wrap' }, chartBox, chartEmpty);
    const allocBox = h('div', {}, skeleton(5));
    const allocSub = h('span');

    const positions = dataTable({
      caption: 'Positions',
      emptyText: 'No open positions',
      sort: { key: 'market_value', dir: 'desc' },
      columns: [
        { key: 'symbol', label: 'Symbol', render: (r) => symCell(r.symbol, r.name) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'cost_price', label: 'Avg cost', num: true, render: (r) => fmtPrice(r.cost_price), cls: 'hide-sm' },
        { key: 'last_price', label: 'Last', num: true, render: (r) => fmtPrice(r.last_price) },
        { key: 'market_value', label: 'Mkt value', num: true, render: (r) => fmtMoney(r.market_value, 0) },
        { key: 'weight', label: 'Weight', num: true, value: (r) => r.market_value / (lastAccount?.account?.equity || 1), render: (r) => weightCell(r.market_value / (lastAccount?.account?.equity || NaN)), cls: 'hide-sm' },
        { key: 'unrealized_pl', label: 'Unrealized P/L', num: true, render: (r) => plCell(r.unrealized_pl, r.unrealized_pl_pct) },
        {
          key: '_act', label: '', sortable: false, cls: 'actions-cell',
          render: (r) => (engineRunning() ? btn('Flatten', { size: 'sm', tone: 'ghost-danger', onclick: (e) => busy(e.currentTarget, () => actions.flatten(r.symbol)), title: `Flatten ${r.symbol}` }) : ''),
        },
      ],
    });
    const working = dataTable({
      caption: 'Working intents',
      emptyText: 'Nothing working',
      dense: true,
      columns: [
        { key: 'id', label: '#', num: true },
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'side', label: 'Side', render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => `${fmtInt(r.filled)} / ${fmtInt(r.quantity)}` },
        { key: 'attempts', label: 'Tries', num: true },
        { key: 'reason', label: 'Reason', cls: 'truncate hide-sm' },
      ],
    });
    const openOrders = dataTable({
      caption: 'Open orders',
      emptyText: 'No open orders',
      dense: true,
      columns: [
        { key: 'created', label: 'Time', render: (r) => timeCell(r.created) },
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'side', label: 'Side', render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => `${fmtInt(r.filled_qty)} / ${fmtInt(r.quantity)}` },
        { key: 'price', label: 'Limit', num: true, render: (r) => fmtPrice(r.price) },
        { key: 'state', label: 'State', render: (r) => stateBadge(r.state), cls: 'hide-sm' },
      ],
    });
    const fills = dataTable({
      caption: 'Recent fills',
      emptyText: 'No fills yet today',
      dense: true,
      maxHeight: '340px',
      sort: { key: 'time', dir: 'desc' },
      columns: [
        { key: 'time', label: 'Time', render: (r) => timeCell(r.time) },
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'side', label: 'Side', render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'price', label: 'Price', num: true, render: (r) => fmtPrice(r.price) },
        { key: 'value', label: 'Value', num: true, value: (r) => r.quantity * r.price, render: (r) => fmtMoney(r.quantity * r.price, 0) },
      ],
    });

    // ---------------------------------------------------------------- activity feed
    const feedKinds = new Set(storage.get(FEED_KEY, KINDS.filter((k) => k !== 'bar' && k !== 'log')));
    const feedList = h('ol', { class: 'feed', 'aria-live': 'off' });
    const feedChips = chips(KINDS.map((k) => ({ value: k, label: k === 'daily_summary' ? 'summary' : k })), feedKinds, (sel) => {
      storage.set(FEED_KEY, [...sel]);
      renderFeed();
    }, { label: 'Event kinds' });
    const filterBox = h('div', { class: 'feed-filters', hidden: true }, feedChips);
    function renderFeed() {
      const evs = stream.recent().filter((e) => feedKinds.has(e.kind)).slice(-150).reverse();
      if (!evs.length) mount(feedList, h('li', { class: 'feed-empty' }, stream.state === 'live' ? 'No activity for the selected kinds yet' : 'Waiting for the live stream…'));
      else mount(feedList, evs.map(feedItem));
    }
    ctx.on('event', (ev) => {
      if (!feedKinds.has(ev.kind)) return;
      feedList.querySelector('.feed-empty')?.remove();
      feedList.prepend(feedItem(ev));
      while (feedList.children.length > 150) feedList.lastElementChild.remove();
    });
    renderFeed();
    const filterBtn = btn('', {
      size: 'sm', tone: 'ghost', iconName: 'filter', title: 'Filter event kinds', attrs: { 'aria-label': 'Filter event kinds', 'aria-expanded': 'false' },
      onclick: (e) => { filterBox.hidden = !filterBox.hidden; e.currentTarget.setAttribute('aria-expanded', String(!filterBox.hidden)); },
    });
    const summaryBtn = btn('', { size: 'sm', tone: 'ghost', iconName: 'bell', title: 'Send the daily summary now', attrs: { 'aria-label': 'Send daily summary' }, onclick: (e) => busy(e.currentTarget, () => actions.summary()) });

    const positionsCount = h('span');
    mount(root,
      h('div', { class: 'dash-grid' },
        h('div', { class: 'dash-main' },
          card({ body: h('div', {}, heroBox, chartWrap), cls: 'equity-card' }),
          card({ title: h('span', {}, 'Positions ', positionsCount), body: positions.el, flush: true, actions: h('a', { href: '#/watchlist', class: 'link-sm' }, 'Watchlist') }),
          h('div', { class: 'grid-2' },
            card({ title: 'Working intents', subtitle: 'Target changes the executor is still filling', body: working.el, flush: true }),
            card({ title: 'Open orders', subtitle: 'Resting at the broker', body: openOrders.el, flush: true, actions: h('a', { href: '#/orders', class: 'link-sm' }, 'Blotter') })),
          card({ title: 'Recent fills', body: fills.el, flush: true, actions: h('a', { href: '#/orders?tab=fills', class: 'link-sm' }, 'All fills') })),
        h('div', { class: 'dash-side' },
          card({ title: 'Allocation', subtitle: allocSub, body: allocBox }),
          card({
            title: h('span', { class: 'row' }, h('span', { class: ['dot', 'dot-good', 'dot-live'], 'aria-hidden': 'true' }), 'Live activity'),
            body: h('div', { class: 'feed-wrap' }, filterBox, feedList), flush: true, actions: [filterBtn, summaryBtn],
          }))));

    // ---------------------------------------------------------------- engine controls (page header)
    function renderControls() {
      const e = engine();
      const running = e?.state === 'running';
      const busyState = e && (e.state === 'starting' || e.state === 'stopping');
      mount(headActions,
        running && !e.halted ? btn('Halt entries', { iconName: 'pause', onclick: (ev) => busy(ev.currentTarget, actions.halt), title: 'Stop opening new positions' }) : null,
        running && e.halted ? btn('Resume entries', { tone: 'primary', iconName: 'play', onclick: (ev) => busy(ev.currentTarget, actions.resume) }) : null,
        running ? btn('Cancel all', { tone: 'ghost-danger', iconName: 'x', onclick: (ev) => busy(ev.currentTarget, actions.cancelAll), title: 'Cancel every open order' }) : null,
        running ? btn('Flatten all', { tone: 'ghost-danger', iconName: 'flatten', onclick: (ev) => busy(ev.currentTarget, () => actions.flatten(null)) }) : null,
        running ? h('span', { class: 'engine-controls' }, h('span', { class: 'sep' })) : null,
        running
          ? btn('Stop engine', { iconName: 'stop', onclick: (ev) => busy(ev.currentTarget, actions.stop) })
          : btn(busyState ? `Engine ${e.state}…` : 'Start engine', { tone: 'primary', iconName: 'play', disabled: busyState, onclick: (ev) => busy(ev.currentTarget, actions.start) }));
      const s = app.status;
      const env = envLabel(s);
      if (e) setDesc(`${env} account · ${e.symbols.length} symbols on ${e.timeframe} bars · trading day ${e.trading_day || '—'}${e.state === 'running' ? '' : ` · engine ${e.state}, showing last known values`}`);
      else setDesc(`${s?.trading?.symbols?.length ?? 0} symbols configured on ${s?.trading?.timeframe || '—'} bars · engine not running`);
    }

    // ---------------------------------------------------------------- hero
    function renderHero(acct, dayStart) {
      if (!acct) {
        const e = engine();
        mount(heroBox, empty(e ? `Engine ${e.state}` : 'The engine is not running', 'Account equity, positions and the intraday curve appear once the engine is running and connected to OpenD.',
          btn('Start engine', { tone: 'primary', iconName: 'play', onclick: (ev) => busy(ev.currentTarget, actions.start) }), 'zap'));
        chartWrap.hidden = true;
        return;
      }
      chartWrap.hidden = false;
      const dayPnl = dayStart ? acct.equity - dayStart : null;
      const dayPct = dayStart ? dayPnl / dayStart : null;
      const unrl = (lastAccount?.positions || []).reduce((s, p) => s + (p.unrealized_pl || 0), 0);
      mount(heroBox, h('div', { class: 'hero' },
        h('div', {},
          h('div', { class: 'hero-label' }, 'Account equity', h('span', { class: ['env', `env-${envLabel(app.status).toLowerCase()}`] }, envLabel(app.status))),
          heroValue(acct.equity, acct.currency),
          h('div', { class: 'hero-delta' }, delta(dayPct, fmtPct(dayPct)), h('span', { class: signCls(dayPnl) }, fmtSignedMoney(dayPnl)), h('span', { class: 'muted' }, 'today'))),
        h('div', { class: 'minis' },
          mini('Cash', fmtMoney(acct.cash, 0)),
          mini('Market value', fmtMoney(acct.market_value, 0)),
          mini('Buying power', fmtCompact(acct.buying_power)),
          mini('Unrealized', fmtSignedMoney(unrl, 0), signCls(unrl)),
          mini('Realized', fmtSignedMoney(acct.realized_pl, 0), signCls(acct.realized_pl)))));
    }

    // ---------------------------------------------------------------- allocation
    function renderAllocation(acct, rows) {
      if (!acct) { mount(allocBox, h('p', { class: 'muted small' }, 'No account data yet.')); allocSub.textContent = ''; return; }
      const eq = acct.equity || 1;
      const pos = [...rows].sort((a, b) => (b.market_value || 0) - (a.market_value || 0));
      const cash = Math.max(0, acct.cash || 0);
      allocSub.textContent = `${fmtPct(acct.market_value / eq, 1, false)} invested · ${fmtInt(pos.length)} position${pos.length === 1 ? '' : 's'}`;
      const seg = (cls, v, label) => h('span', { class: ['alloc-seg', cls], style: { flex: `${Math.max(v, 0)} 1 0` }, title: `${label}: ${fmtPct(v / eq, 1, false)}` });
      mount(allocBox, h('div', { class: 'alloc' },
        h('div', { class: 'alloc-bar', role: 'img', 'aria-label': `Allocation: ${pos.map((p) => `${p.symbol} ${fmtPct(p.market_value / eq, 1, false)}`).join(', ')}, cash ${fmtPct(cash / eq, 1, false)}` },
          pos.map((p) => seg('', p.market_value, p.symbol)), seg('cash', cash, 'Cash')),
        h('div', { class: 'alloc-list' },
          pos.map((p) => h('div', { class: 'alloc-row' }, h('span', { class: 'alloc-sw' }), h('span', {}, symLink(p.symbol)), h('span', { class: 'alloc-val' }, fmtCompact(p.market_value)), h('span', { class: 'alloc-pct' }, fmtPct(p.market_value / eq, 1, false)))),
          h('div', { class: 'alloc-row cash' }, h('span', { class: 'alloc-sw' }), h('span', { class: 'text-2' }, 'Cash'), h('span', { class: 'alloc-val' }, fmtCompact(cash)), h('span', { class: 'alloc-pct' }, fmtPct(cash / eq, 1, false))))));
    }

    // ---------------------------------------------------------------- equity chart
    let eq = null;
    let lastEqTime = 0;
    function drawEquity(rows, dayStart) {
      const today = engine()?.trading_day;
      const pts = [];
      for (const r of rows) {
        const t = hkEpoch(r.time);
        if (t == null || r.equity == null) continue;
        if (today && new Date(t * 1000).toISOString().slice(0, 10) !== today) continue;
        if (pts.length && t <= pts[pts.length - 1].time) continue;
        pts.push({ time: t, value: r.equity });
      }
      if (pts.length < 2 || !window.LightweightCharts) {
        chartBox.hidden = true;
        chartEmpty.hidden = false;
        mount(chartEmpty, h('p', { class: 'muted small' }, engineRunning() ? 'The intraday curve fills in as the engine records equity once a minute.' : 'Start the engine to record the intraday equity curve.'));
        return;
      }
      chartBox.hidden = false;
      chartEmpty.hidden = true;
      if (eq) { eq.dispose(); eq = null; }
      eq = equityChart(chartBox, {
        lines: [{ name: 'Equity', data: pts }],
        baseline: dayStart || pts[0].value,
        valueFormat: (v) => fmtMoney(v, 0),
        legend: false,
      });
      lastEqTime = pts[pts.length - 1].time;
    }
    ctx.add(() => eq?.dispose());
    function appendEquity(acct) {
      if (!eq || !acct) return;
      const t = hkEpoch(serverNow());
      if (t <= lastEqTime) return;
      eq.series[0].s.update({ time: t, value: acct.equity });
      lastEqTime = t;
      eq.update(null);
    }

    // ---------------------------------------------------------------- data
    let lastAccount = null;
    async function loadAccount() {
      const [acct, open] = await Promise.all([api('/api/account'), api('/api/orders?open_only=true&limit=50')]);
      if (!ctx.alive) return;
      lastAccount = acct;
      const rows = acct.positions || [];
      positionsCount.textContent = rows.length ? String(rows.length) : '';
      positionsCount.className = 'tab-count';
      positionsCount.hidden = !rows.length;
      positions.update(rows);
      openOrders.update(open || []);
      working.update(engine()?.working || []);
      renderHero(acct.account, acct.day_start_equity);
      renderAllocation(acct.account, rows);
      appendEquity(acct.account);
    }
    async function loadFills() {
      const rows = await api('/api/fills?limit=40');
      if (ctx.alive) fills.update(rows || []);
    }
    async function loadEquity() {
      const rows = await api('/api/equity?days=1');
      if (!ctx.alive) return;
      drawEquity(rows || [], lastAccount?.day_start_equity);
    }

    renderControls();
    ctx.onStatus(() => { renderControls(); working.update(engine()?.working || []); });
    try {
      await loadAccount();
      await Promise.all([loadFills(), loadEquity()]);
    } catch (err) {
      if (!ctx.alive) return;
      mount(heroBox, errorBox(err, () => { refreshStatus(); loadAccount().catch(() => {}); }));
    }
    const refresh = throttle(() => { loadAccount().catch(() => {}); loadFills().catch(() => {}); }, 1000);
    ctx.every(3000, () => loadAccount().catch(() => {}));
    ctx.every(60000, () => loadEquity().catch(() => {}));
    ctx.on('fill', refresh);
    ctx.on('order', refresh);
    ctx.on('rejection', refresh);
    ctx.on('engine', () => { refresh(); loadEquity().catch(() => {}); });
  },
};
