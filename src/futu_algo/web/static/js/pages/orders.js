// Orders: the full order blotter, fills and execution intents with filters.

import { h, mount, fmtInt, fmtPrice, fmtMoney, throttle } from '../core.js';
import { api } from '../api.js';
import { actions, engineRunning } from '../state.js';
import { card, dataTable, tabs, segmented, errorBox, btn, busy } from '../ui.js';
import { symLink, sideBadge, stateBadge, timeCell } from '../common.js';

const ORDER_STATES = ['all', 'open', 'filled', 'cancelled', 'failed'];
const OPEN = new Set(['pending', 'submitted', 'partial']);

export default {
  title: () => 'Orders',
  async mount(root, { query, ctx }) {
    let tab = ['orders', 'fills', 'intents'].includes(query.get('tab')) ? query.get('tab') : 'orders';
    const filters = { state: 'all', side: 'all', symbol: '' };
    const data = { orders: [], fills: [], intents: [] };

    const orders = dataTable({
      caption: 'Orders', emptyText: 'No orders match the filters', sort: { key: 'created', dir: 'desc' }, maxHeight: '70vh',
      columns: [
        { key: 'created', label: 'Created', render: (r) => timeCell(r.created) },
        { key: 'order_id', label: 'Order', cls: 'mono hide-sm' },
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'side', label: 'Side', render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'price', label: 'Limit', num: true, render: (r) => fmtPrice(r.price), cls: 'mono' },
        { key: 'filled_qty', label: 'Filled', num: true, render: (r) => fmtInt(r.filled_qty) },
        { key: 'avg_fill_price', label: 'Avg fill', num: true, render: (r) => (r.filled_qty ? fmtPrice(r.avg_fill_price) : '—'), cls: 'mono' },
        { key: 'state', label: 'State', render: (r) => stateBadge(r.state) },
        { key: 'order_type', label: 'Type', cls: 'hide-sm' },
        { key: 'intent_id', label: 'Intent', num: true, cls: 'hide-sm' },
        { key: 'error', label: 'Note', cls: 'truncate', value: (r) => r.error || r.remark },
        { key: 'updated', label: 'Updated', render: (r) => timeCell(r.updated), cls: 'hide-sm' },
      ],
    });
    const fills = dataTable({
      caption: 'Fills', emptyText: 'No fills match the filters', sort: { key: 'time', dir: 'desc' }, maxHeight: '70vh',
      columns: [
        { key: 'time', label: 'Time', render: (r) => timeCell(r.time) },
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'side', label: 'Side', render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'price', label: 'Price', num: true, render: (r) => fmtPrice(r.price), cls: 'mono' },
        { key: 'value', label: 'Value', num: true, value: (r) => r.quantity * r.price, render: (r) => fmtMoney(r.quantity * r.price) },
        { key: 'order_id', label: 'Order', cls: 'mono' },
        { key: 'env', label: 'Env', cls: 'hide-sm' },
      ],
    });
    const intents = dataTable({
      caption: 'Intents', emptyText: 'No intents match the filters', sort: { key: 'id', dir: 'desc' }, maxHeight: '70vh',
      columns: [
        { key: 'id', label: '#', num: true },
        { key: 'created', label: 'Created', render: (r) => timeCell(r.created) },
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'side', label: 'Side', render: (r) => sideBadge(r.side) },
        { key: 'quantity', label: 'Qty', num: true, render: (r) => fmtInt(r.quantity) },
        { key: 'reason', label: 'Reason' },
        { key: 'status', label: 'Status', render: (r) => stateBadge(r.status) },
        { key: 'attempts', label: 'Attempts', num: true },
        { key: 'bar_time', label: 'Bar', render: (r) => timeCell(r.bar_time), cls: 'hide-sm' },
        { key: 'detail', label: 'Detail', cls: 'truncate' },
      ],
    });
    const tables = { orders, fills, intents };

    const tabBar = tabs([
      { value: 'orders', label: 'Orders' }, { value: 'fills', label: 'Fills' }, { value: 'intents', label: 'Intents' },
    ], tab, (v) => { tab = v; history.replaceState(null, '', `#/orders${v === 'orders' ? '' : `?tab=${v}`}`); render(); });
    const stateSeg = segmented(ORDER_STATES.map((s) => ({ value: s, label: s[0].toUpperCase() + s.slice(1) })), filters.state, (v) => { filters.state = v; render(); }, { label: 'Order state', size: 'sm' });
    const sideSeg = segmented([{ value: 'all', label: 'Both' }, { value: 'BUY', label: 'Buy' }, { value: 'SELL', label: 'Sell' }], filters.side, (v) => { filters.side = v; render(); }, { label: 'Side', size: 'sm' });
    const symIn = h('input', { class: 'input input-sm mono', type: 'search', placeholder: 'Symbol…', 'aria-label': 'Filter by symbol', oninput: (e) => { filters.symbol = e.target.value.trim().toUpperCase(); render(); } });
    const stateWrap = h('div', { class: 'filter-group' }, h('span', { class: 'filter-label' }, 'State'), stateSeg);
    const cancelBtn = btn('Cancel all open', { size: 'sm', tone: 'ghost-danger', iconName: 'x', onclick: (e) => busy(e.currentTarget, async () => { await actions.cancelAll(); load(); }) });
    const body = h('div');
    const counts = h('span', { class: 'toolbar-meta' });

    mount(root,
      h('div', { class: 'toolbar' }, tabBar, counts),
      card({
        body: h('div', {},
          h('div', { class: 'filters' },
            stateWrap,
            h('div', { class: 'filter-group' }, h('span', { class: 'filter-label' }, 'Side'), sideSeg),
            h('div', { class: 'filter-group' }, symIn),
            h('div', { class: 'filter-spacer' }),
            cancelBtn),
          body),
        flush: true,
      }));

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
      counts.textContent = `${rows.length} of ${data[tab].length} ${tab}`;
    }
    async function load() {
      try {
        const [o, f, i] = await Promise.all([api('/api/orders?limit=500'), api('/api/fills?limit=500'), api('/api/intents?limit=500')]);
        if (!ctx.alive) return;
        Object.assign(data, { orders: o || [], fills: f || [], intents: i || [] });
        render();
      } catch (err) {
        if (ctx.alive) mount(body, errorBox(err, load));
      }
    }
    await load();
    const refresh = throttle(load, 1500);
    ctx.on('order', refresh);
    ctx.on('fill', refresh);
    ctx.on('rejection', refresh);
    ctx.every(10000, load);
    ctx.onStatus(() => { cancelBtn.hidden = tab !== 'orders' || !engineRunning(); });
  },
};
