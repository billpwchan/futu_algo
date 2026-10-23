import { t as translate } from '../i18n.js';
// Orders: the full order blotter, fills and execution intents with filters.

import { h, mount, icon, fmtInt, fmtPrice, fmtMoney, fmtCompact, throttle } from '../core.js';
import { api } from '../api.js';
import { actions, engineRunning } from '../state.js';
import { card, dataTable, tabs, segmented, errorBox, btn, busy, kpi } from '../ui.js';
import { symLink, sideBadge, stateBadge, timeCell } from '../common.js';
import { engine } from '../state.js';

const ORDER_STATES = ['all', 'open', 'filled', 'cancelled', 'failed'];
const OPEN = new Set(['pending', 'submitted', 'partial']);

export default {
  title: () => translate('Orders'),
  async mount(root, { query, ctx }) {
    let tab = ['orders', 'fills', 'intents'].includes(query.get('tab')) ? query.get('tab') : 'orders';
    const filters = { state: 'all', side: 'all', symbol: '' };
    const data = { orders: [], fills: [], intents: [] };

    const orders = dataTable({
      caption: translate('Orders'), emptyText: translate('No orders match the filters'), sort: { key: 'created', dir: 'desc' }, maxHeight: '70vh',
      columns: [
        { key: 'created', label: translate('Created'), render: (r) => timeCell(r.created) },
        { key: 'order_id', label: translate('Order'), cls: 'mono muted hide-sm' },
        { key: 'symbol', label: translate('Symbol'), render: (r) => symLink(r.symbol) },
        { key: 'side', label: translate('Side'), render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: translate('Qty'), num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'price', label: translate('Limit'), num: true, render: (r) => fmtPrice(r.price) },
        { key: 'filled_qty', label: translate('Filled'), num: true, render: (r) => fmtInt(r.filled_qty) },
        { key: 'avg_fill_price', label: translate('Avg fill'), num: true, render: (r) => (r.filled_qty ? fmtPrice(r.avg_fill_price) : '—') },
        { key: 'state', label: translate('State'), render: (r) => stateBadge(r.state) },
        { key: 'order_type', label: translate('Type'), cls: 'hide-sm' },
        { key: 'intent_id', label: translate('Intent'), num: true, cls: 'hide-sm' },
        { key: 'error', label: translate('Note'), cls: 'truncate', value: (r) => r.error || r.remark },
        { key: 'updated', label: translate('Updated'), render: (r) => timeCell(r.updated), cls: 'hide-sm' },
      ],
    });
    const fills = dataTable({
      caption: translate('Fills'), emptyText: translate('No fills match the filters'), sort: { key: 'time', dir: 'desc' }, maxHeight: '70vh',
      columns: [
        { key: 'time', label: translate('Time'), render: (r) => timeCell(r.time) },
        { key: 'symbol', label: translate('Symbol'), render: (r) => symLink(r.symbol) },
        { key: 'side', label: translate('Side'), render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: translate('Qty'), num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'price', label: translate('Price'), num: true, render: (r) => fmtPrice(r.price) },
        { key: 'value', label: translate('Value'), num: true, value: (r) => r.quantity * r.price, render: (r) => fmtMoney(r.quantity * r.price) },
        { key: 'order_id', label: translate('Order'), cls: 'mono muted' },
        { key: 'env', label: translate("Env"), cls: 'hide-sm', render: (r) => h('span', { class: ['env', `env-${String(r.env || '').toLowerCase()}`] }, r.env || '—') },
      ],
    });
    const intents = dataTable({
      caption: translate('Intents'), emptyText: translate('No intents match the filters'), sort: { key: 'id', dir: 'desc' }, maxHeight: '70vh',
      columns: [
        { key: 'id', label: '#', num: true },
        { key: 'created', label: translate('Created'), render: (r) => timeCell(r.created) },
        { key: 'symbol', label: translate('Symbol'), render: (r) => symLink(r.symbol) },
        { key: 'side', label: translate('Side'), render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: translate('Qty'), num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'reason', label: translate('Reason') },
        { key: 'status', label: translate('Status'), render: (r) => stateBadge(r.status) },
        { key: 'attempts', label: translate('Attempts'), num: true },
        { key: 'bar_time', label: translate('Bar'), render: (r) => timeCell(r.bar_time), cls: 'hide-sm' },
        { key: 'detail', label: translate('Detail'), cls: 'truncate' },
      ],
    });
    const tables = { orders, fills, intents };

    const tabItems = () => [
      { value: 'orders', label: translate('Orders'), count: data.orders.length }, { value: 'fills', label: translate('Fills'), count: data.fills.length }, { value: 'intents', label: translate('Intents'), count: data.intents.length },
    ];
    const onTab = (v) => { tab = v; history.replaceState(null, '', `#/orders${v === 'orders' ? '' : `?tab=${v}`}`); render(); };
    const tabHolder = h('div', { class: 'card-tabs' });
    const renderTabs = () => mount(tabHolder, tabs(tabItems(), tab, onTab));
    const stats = h('div', { class: 'kpis' });
    const stateSeg = segmented(ORDER_STATES.map((s) => ({ value: s, label: s === 'open' ? translate('Open orders') : translate(s[0].toUpperCase() + s.slice(1)) })), filters.state, (v) => { filters.state = v; render(); }, { label: translate('Order state'), size: 'sm' });
    const sideSeg = segmented([{ value: 'all', label: translate('Both') }, { value: 'BUY', label: translate('Buy') }, { value: 'SELL', label: translate('Sell') }], filters.side, (v) => { filters.side = v; render(); }, { label: translate('Side'), size: 'sm' });
    const symIn = h('input', { class: 'input input-sm mono', type: 'search', placeholder: translate("Symbol…"), 'aria-label': translate('Filter by symbol'), oninput: (e) => { filters.symbol = e.target.value.trim().toUpperCase(); render(); } });
    const stateWrap = h('div', { class: 'filter-group' }, h('span', { class: 'filter-label' }, translate('State')), stateSeg);
    const cancelBtn = btn(translate('Cancel all open'), { size: 'sm', tone: 'ghost-danger', iconName: 'x', onclick: (e) => busy(e.currentTarget, async () => { await actions.cancelAll(); load(); }) });
    const body = h('div');
    const counts = h('span', { class: 'toolbar-meta' });

    mount(root,
      stats,
      card({
        body: h('div', {},
          tabHolder,
          h('div', { class: 'filters' },
            stateWrap,
            h('div', { class: 'filter-group' }, h('span', { class: 'filter-label' }, translate('Side')), sideSeg),
            h('div', { class: 'filter-group' }, h('div', { class: 'input-icon' }, icon('search', 13), symIn)),
            h('div', { class: 'filter-spacer' }),
            counts,
            cancelBtn),
          body),
        flush: true,
      }));

    function renderStats() {
      // The engine's trading day, or the last day with orders when it has none yet.
      const latest = data.orders.reduce((m, o) => (String(o.created || '') > m ? String(o.created) : m), '').slice(0, 10);
      const tradingDay = engine()?.trading_day;
      const day = data.orders.some((o) => String(o.created || '').startsWith(tradingDay)) ? tradingDay : latest || tradingDay;
      const onDay = (t) => !day || String(t || '').startsWith(day);
      const ordersToday = data.orders.filter((o) => onDay(o.created));
      const fillsToday = data.fills.filter((f) => onDay(f.time));
      const value = fillsToday.reduce((a, f) => a + f.quantity * f.price, 0);
      const buys = fillsToday.filter((f) => f.side === 'BUY').length;
      const openN = data.orders.filter((o) => OPEN.has(o.state)).length;
      const filled = ordersToday.filter((o) => o.state === 'filled').length;
      const failed = ordersToday.filter((o) => o.state === 'failed').length;
      mount(stats,
        kpi(day && day !== tradingDay ? translate("Orders on {0}", { 0: day }) : translate("Orders today"), fmtInt(ordersToday.length), { sub: translate("{0} filled · {1} failed", { 0: fmtInt(filled), 1: fmtInt(failed) }) }),
        kpi(translate('Open orders'), fmtInt(openN), { sub: translate("resting at the broker") }),
        kpi(translate('Fills'), fmtInt(fillsToday.length), { sub: translate("{0} buy · {1} sell", { 0: fmtInt(buys), 1: fmtInt(fillsToday.length - buys) }) }),
        kpi(translate("Traded value"), `HK$${fmtCompact(value)}`, { sub: translate("sum of fills") }),
        kpi(translate("Fill rate"), ordersToday.length ? `${Math.round((filled / ordersToday.length) * 100)}%` : '—', { sub: translate("orders filled in full") }));
    }

    function pass(r, stateKey) {
      if (filters.side !== 'all' && r.side !== filters.side) return false;
      if (filters.symbol && !String(r.symbol).toUpperCase().includes(filters.symbol)) return false;
      if (stateKey && filters.state !== 'all') {
        const st = r[stateKey];
        if (filters.state === 'open') return OPEN.has(st) || st === 'working';
        return st === filters.state || (filters.state === 'filled' && st === 'done');
      }
      return true;
    }
    function render() {
      stateWrap.hidden = tab === 'fills';
      cancelBtn.hidden = tab !== 'orders' || !engineRunning();
      const rows = tab === 'orders' ? data.orders.filter((r) => pass(r, 'state'))
        : tab === 'fills' ? data.fills.filter((r) => pass(r))
          : data.intents.filter((r) => pass(r, 'status'));
      tables[tab].update(rows);
      if (!body.contains(tables[tab].el)) mount(body, tables[tab].el);
      counts.textContent = translate("{0} of {1} {2}", { 0: rows.length, 1: data[tab].length, 2: translate(tab) });
    }
    async function load() {
      try {
        const [o, f, i] = await Promise.all([api('/api/orders?limit=500'), api('/api/fills?limit=500'), api('/api/intents?limit=500')]);
        if (!ctx.alive) return;
        Object.assign(data, { orders: o || [], fills: f || [], intents: i || [] });
        renderTabs();
        renderStats();
        render();
      } catch (err) {
        if (ctx.alive) mount(body, errorBox(err, load));
      }
    }
    renderTabs();
    await load();
    const refresh = throttle(load, 1500);
    ctx.on('order', refresh);
    ctx.on('fill', refresh);
    ctx.on('rejection', refresh);
    ctx.every(10000, load);
    ctx.onStatus(() => { cancelBtn.hidden = tab !== 'orders' || !engineRunning(); });
  },
};
