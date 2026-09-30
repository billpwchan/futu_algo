// Dashboard: engine controls, account KPIs, intraday equity, positions, orders, fills, live feed.

import { h, mount, storage, fmtMoney, fmtSignedMoney, fmtPct, fmtInt, fmtPrice, signCls, hkEpoch, fmtCompact, throttle } from '../core.js';
import { api, stream, KINDS } from '../api.js';
import { app, actions, engine, engineRunning, serverNow, refreshStatus } from '../state.js';
import { card, kpi, btn, busy, dataTable, empty, chips, skeleton, errorBox } from '../ui.js';
import { symLink, sideBadge, stateBadge, pnl, timeCell, feedItem } from '../common.js';
import { equityChart } from '../charts.js';

const FEED_KEY = 'futu_algo.feedKinds';

export default {
  title: () => 'Dashboard',
  async mount(root, { ctx }) {
    const controls = h('div', { class: 'toolbar controls' });
    const kpis = h('div', { class: 'kpis' }, Array.from({ length: 6 }, () => h('div', { class: 'kpi kpi-loading' }, skeleton(2))));
    const chartBox = h('div', { class: 'chart chart-md' });
    const chartEmpty = h('div', { class: 'chart-empty', hidden: true });
    const chartWrap = h('div', { class: 'chart-wrap' }, chartBox, chartEmpty);

    const positions = dataTable({
      caption: 'Positions',
      emptyText: 'No open positions',
      sort: { key: 'market_value', dir: 'desc' },
      columns: [
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'name', label: 'Name', cls: 'truncate hide-sm' },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'cost_price', label: 'Cost', num: true, render: (r) => fmtPrice(r.cost_price), cls: 'mono' },
        { key: 'last_price', label: 'Last', num: true, render: (r) => fmtPrice(r.last_price), cls: 'mono' },
        { key: 'market_value', label: 'Mkt value', num: true, render: (r) => fmtMoney(r.market_value) },
        { key: 'unrealized_pl', label: 'Unrl. P/L', num: true, render: (r) => pnl(r.unrealized_pl) },
        { key: 'unrealized_pl_pct', label: 'P/L %', num: true, render: (r) => pnl(r.unrealized_pl_pct, { pct: true }) },
        {
          key: '_act', label: '', sortable: false, cls: 'actions-cell',
          render: (r) => (engineRunning() ? btn('Flatten', { size: 'sm', tone: 'ghost-danger', onclick: (e) => busy(e.currentTarget, () => actions.flatten(r.symbol)), title: `Flatten ${r.symbol}` }) : ''),
        },
      ],
    });
    const working = dataTable({
      caption: 'Working intents',
      emptyText: 'No working intents',
      dense: true,
      columns: [
        { key: 'id', label: '#', num: true },
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'side', label: 'Side', render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'filled', label: 'Filled', num: true, render: (r) => fmtInt(r.filled) },
        { key: 'attempts', label: 'Tries', num: true },
        { key: 'reason', label: 'Reason', cls: 'truncate' },
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
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'price', label: 'Price', num: true, render: (r) => fmtPrice(r.price), cls: 'mono' },
        { key: 'filled_qty', label: 'Filled', num: true, render: (r) => fmtInt(r.filled_qty) },
        { key: 'state', label: 'State', render: (r) => stateBadge(r.state) },
      ],
    });
    const fills = dataTable({
      caption: 'Recent fills',
      emptyText: 'No fills yet',
      dense: true,
      maxHeight: '320px',
      columns: [
        { key: 'time', label: 'Time', render: (r) => timeCell(r.time) },
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'side', label: 'Side', render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'price', label: 'Price', num: true, render: (r) => fmtPrice(r.price), cls: 'mono' },
        { key: 'value', label: 'Value', num: true, value: (r) => r.quantity * r.price, render: (r) => fmtMoney(r.quantity * r.price, 0) },
      ],
    });

    // ---------------------------------------------------------------- activity feed
    const feedKinds = new Set(storage.get(FEED_KEY, KINDS.filter((k) => k !== 'bar' && k !== 'log')));
    const feedList = h('ol', { class: 'feed', 'aria-live': 'off' });
    const counts = {};
    const feedChips = chips(KINDS.map((k) => ({ value: k, label: k === 'daily_summary' ? 'summary' : k })), feedKinds, (sel) => {
      storage.set(FEED_KEY, [...sel]);
      renderFeed();
    }, { label: 'Event kinds' });
    function renderFeed() {
      const evs = stream.recent().filter((e) => feedKinds.has(e.kind)).slice(-150).reverse();
      if (!evs.length) mount(feedList, h('li', { class: 'feed-empty' }, stream.state === 'live' ? 'No activity for the selected kinds yet' : 'Waiting for the live stream…'));
      else mount(feedList, evs.map(feedItem));
    }
    ctx.on('event', (ev) => {
      counts[ev.kind] = (counts[ev.kind] || 0) + 1;
      if (!feedKinds.has(ev.kind)) return;
      feedList.querySelector('.feed-empty')?.remove();
      feedList.prepend(feedItem(ev));
      while (feedList.children.length > 150) feedList.lastElementChild.remove();
    });
    renderFeed();

    const summaryBtn = btn('Send daily summary', { size: 'sm', tone: 'ghost', iconName: 'bell', onclick: (e) => busy(e.currentTarget, () => actions.summary()) });

    mount(root,
      controls,
      kpis,
      h('div', { class: 'dash-grid' },
        h('div', { class: 'dash-main' },
          card({ title: 'Intraday equity', subtitle: 'Account equity vs. start of day', body: chartWrap, cls: 'card-chart' }),
          card({ title: 'Positions', actions: engineRunning() ? null : null, body: positions.el, flush: true, id: 'positions-card' }),
          h('div', { class: 'grid-2' },
            card({ title: 'Working intents', body: working.el, flush: true }),
            card({ title: 'Open orders', body: openOrders.el, flush: true, actions: h('a', { href: '#/orders', class: 'link-sm' }, 'All orders') })),
          card({ title: 'Recent fills', body: fills.el, flush: true, actions: h('a', { href: '#/orders?tab=fills', class: 'link-sm' }, 'All fills') })),
        h('div', { class: 'dash-side' },
          card({ title: 'Live activity', body: h('div', { class: 'feed-wrap' }, feedChips, feedList), cls: 'card-feed', actions: summaryBtn })),
      ));

    // ---------------------------------------------------------------- controls
    function renderControls() {
      const e = engine();
      const running = e?.state === 'running';
      const busyState = e && (e.state === 'starting' || e.state === 'stopping');
      mount(controls,
        h('div', { class: 'toolbar-group' },
          running
            ? btn('Stop engine', { tone: 'secondary', iconName: 'stop', onclick: (ev) => busy(ev.currentTarget, actions.stop) })
            : btn(busyState ? `Engine ${e.state}…` : 'Start engine', { tone: 'primary', iconName: 'play', disabled: busyState, onclick: (ev) => busy(ev.currentTarget, actions.start) }),
          running && !e.halted ? btn('Halt entries', { iconName: 'pause', onclick: (ev) => busy(ev.currentTarget, actions.halt), title: 'Stop opening new positions' }) : null,
          running && e.halted ? btn('Resume entries', { tone: 'primary', iconName: 'play', onclick: (ev) => busy(ev.currentTarget, actions.resume) }) : null),
        h('div', { class: 'toolbar-group' },
          btn('Cancel all orders', { tone: 'ghost-danger', iconName: 'x', disabled: !running, onclick: (ev) => busy(ev.currentTarget, actions.cancelAll) }),
          btn('Flatten all', { tone: 'danger', iconName: 'flatten', disabled: !running, onclick: (ev) => busy(ev.currentTarget, () => actions.flatten(null)) })),
        h('div', { class: 'toolbar-meta' }, metaText(e)));
    }
    function metaText(e) {
      const s = app.status;
      if (!e) return `${s?.trading?.symbols?.length ?? 0} symbols configured · ${s?.trading?.timeframe || ''} bars`;
      const base = `${e.symbols.length} symbols · ${e.timeframe} bars · trading day ${e.trading_day || '—'}`;
      return e.state === 'running' ? base : `${base} · engine ${e.state}: showing last known values`;
    }

    // ---------------------------------------------------------------- KPIs
    function renderKpis(acct, dayStart) {
      if (!acct) {
        const e = engine();
        mount(kpis, h('div', { class: 'kpis-empty' }, empty(e ? `Engine ${e.state}` : 'Engine is not running', 'Account figures appear once the engine is running and connected to OpenD.',
          btn('Start engine', { tone: 'primary', iconName: 'play', onclick: (ev) => busy(ev.currentTarget, actions.start) }))));
        return;
      }
      const dayPnl = dayStart ? acct.equity - dayStart : null;
      const dayPct = dayStart ? dayPnl / dayStart : null;
      const unrl = (lastAccount?.positions || []).reduce((s, p) => s + (p.unrealized_pl || 0), 0);
      mount(kpis,
        kpi('Equity', fmtMoney(acct.equity), { sub: acct.currency || 'HKD', title: 'Total assets' }),
        kpi('Day P/L', fmtSignedMoney(dayPnl), { tone: signCls(dayPnl), sub: fmtPct(dayPct), subTone: signCls(dayPct), title: `vs. start-of-day equity ${fmtMoney(dayStart)}` }),
        kpi('Cash', fmtMoney(acct.cash), { sub: `Buying power ${fmtCompact(acct.buying_power)}` }),
        kpi('Market value', fmtMoney(acct.market_value), { sub: acct.equity ? `${fmtPct(acct.market_value / acct.equity, 1, false)} of equity` : null }),
        kpi('Unrealized P/L', fmtSignedMoney(unrl), { tone: signCls(unrl), sub: `Realized ${fmtSignedMoney(acct.realized_pl)}` }),
        kpi('Positions', fmtInt(lastAccount?.positions?.length ?? 0), { sub: `${engine()?.working?.length ?? 0} working intent(s)` }));
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
      if (!pts.length || !window.LightweightCharts) {
        chartBox.hidden = true;
        chartEmpty.hidden = false;
        mount(chartEmpty, empty('No equity points yet', engineRunning() ? 'The engine records equity once a minute; the curve fills in as the session runs.' : 'Start the engine to record the intraday equity curve.'));
        return;
      }
      chartBox.hidden = false;
      chartEmpty.hidden = true;
      if (eq) { eq.dispose(); eq = null; }
      eq = equityChart(chartBox, {
        lines: [{ name: 'Equity', data: pts }],
        baseline: dayStart || pts[0].value,
        valueFormat: (v) => fmtMoney(v, 0),
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
      positions.update(acct.positions || []);
      openOrders.update(open || []);
      working.update(engine()?.working || []);
      renderKpis(acct.account, acct.day_start_equity);
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
      mount(kpis, errorBox(err, () => { refreshStatus(); loadAccount().catch(() => {}); }));
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
