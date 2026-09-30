// Watchlist: every symbol the engine trades, its strategy, warm-up and last decision.

import { h, mount, fmtPrice, fmtInt, fmtWhen, paramsText } from '../core.js';
import { app, engine, go, actions } from '../state.js';
import { dataTable, empty, badge, btn, busy, card } from '../ui.js';
import { symLink } from '../common.js';

const ACTION_TONE = { buy: 'good', sell: 'bad', hold: 'muted', warmup: 'info', skip: 'warn', error: 'bad', exit: 'bad' };

export default {
  title: () => 'Watchlist',
  mount(root, { ctx }) {
    const table = dataTable({
      caption: 'Watchlist',
      emptyText: 'No symbols',
      sort: { key: 'symbol', dir: 'asc' },
      onRowClick: (r) => go(`#/chart/${encodeURIComponent(r.symbol)}`),
      rowTitle: (r) => `Open ${r.symbol} chart`,
      rowClass: (r) => (r.position ? 'row-held' : null),
      columns: [
        { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol) },
        { key: 'name', label: 'Name', cls: 'truncate' },
        {
          key: 'strategy', label: 'Strategy',
          render: (r) => h('div', { class: 'cell-stack' }, h('span', { class: 'mono' }, r.strategy), h('span', { class: 'cell-sub mono' }, paramsText(r.params))),
        },
        {
          key: 'bars', label: 'Bars / warm-up', num: true, value: (r) => r.bars - r.warmup,
          render: (r) => {
            const ready = r.bars > r.warmup;
            return h('span', { class: ready ? '' : 'text-warn', title: ready ? 'Warmed up' : 'Still warming up' }, `${fmtInt(r.bars)} / ${fmtInt(r.warmup)}`);
          },
        },
        { key: 'close', label: 'Last close', num: true, value: (r) => r.last_bar?.close, render: (r) => h('span', { class: 'mono' }, fmtPrice(r.last_bar?.close)) },
        { key: 'bar_time', label: 'Bar time', value: (r) => r.last_bar?.time, render: (r) => h('span', { class: 'num' }, fmtWhen(r.last_bar?.time)) },
        {
          key: 'decision', label: 'Last decision', value: (r) => r.last_decision?.action,
          render: (r) => {
            const d = r.last_decision;
            if (!d) return null;
            return h('div', { class: 'cell-inline' }, badge(d.action, ACTION_TONE[d.action] || 'neutral'), d.detail ? h('span', { class: 'cell-sub truncate', title: d.detail }, d.detail) : null);
          },
        },
        { key: 'position', label: 'Position', num: true, render: (r) => (r.position ? h('strong', {}, fmtInt(r.position)) : h('span', { class: 'muted' }, '0')) },
        { key: 'blocked', label: 'Blocked', value: (r) => (r.blocked ? 1 : 0), render: (r) => (r.blocked ? badge('awaiting fresh signal', 'warn', { title: 'Re-entry blocked until the strategy issues a fresh buy signal' }) : h('span', { class: 'muted' }, 'no')) },
      ],
    });
    const body = h('div');
    mount(root, body);

    function render() {
      const e = engine();
      if (!e) {
        const syms = app.status?.trading?.symbols || [];
        mount(body, card({
          title: 'Configured universe',
          subtitle: 'The engine is not running; live strategy state appears once it starts.',
          actions: btn('Start engine', { tone: 'primary', iconName: 'play', onclick: (ev) => busy(ev.currentTarget, actions.start) }),
          body: syms.length
            ? h('ul', { class: 'sym-grid' }, syms.map((s) => h('li', {}, symLink(s))))
            : empty('No symbols configured', 'Add symbols under trading.universe in the config.'),
        }));
        return;
      }
      if (!body.contains(table.el)) {
        mount(body, card({
          title: `${e.symbols.length} symbols`,
          subtitle: `${e.timeframe} bars · ${e.state === 'running' ? 'live' : e.state}`,
          body: table.el, flush: true,
        }));
      }
      table.update(e.symbols);
    }
    render();
    ctx.onStatus(render);
  },
};
