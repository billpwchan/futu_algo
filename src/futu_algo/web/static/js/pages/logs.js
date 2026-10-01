// Logs: persisted events with kind / level filters and live append from the stream.

import { h, mount, storage, fmtDateTime } from '../core.js';
import { api, KINDS, stream } from '../api.js';
import { card, chips, segmented, errorBox, loading, btn } from '../ui.js';
import { kindBadge, levelBadge } from '../common.js';

const LEVELS = ['debug', 'info', 'warning', 'error'];
const KEY = 'futu_algo.logFilters';
const MAX = 1500;

export default {
  title: () => 'Logs',
  async mount(root, { ctx }) {
    const saved = storage.get(KEY, {});
    const kinds = new Set(saved.kinds || KINDS.filter((k) => k !== 'bar'));
    let minLevel = saved.level || 'info';
    let text = '';
    let paused = false;
    let events = [];
    let pending = 0;

    const persist = () => storage.set(KEY, { kinds: [...kinds], level: minLevel });
    const list = h('tbody');
    const table = h('div', { class: 'table-wrap logs-wrap' }, h('table', { class: 'table table-dense logs-table' },
      h('caption', { class: 'sr-only' }, 'Event log'),
      h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Time (HKT)'), h('th', { scope: 'col' }, 'Level'), h('th', { scope: 'col' }, 'Kind'), h('th', { scope: 'col', class: 'hide-sm' }, 'Symbol'), h('th', { scope: 'col' }, 'Message'))),
      list));
    const count = h('span', { class: 'toolbar-meta' });
    const pauseBtn = btn('Pause', { size: 'sm', tone: 'ghost', iconName: 'pause', onclick: () => { paused = !paused; renderPause(); if (!paused) render(); } });
    function renderPause() {
      pauseBtn.replaceChildren(document.createTextNode(paused ? `Resume${pending ? ` (${pending} new)` : ''}` : 'Pause'));
      pauseBtn.classList.toggle('active', paused);
    }

    const passes = (ev) => kinds.has(ev.kind) && LEVELS.indexOf(ev.level) >= LEVELS.indexOf(minLevel)
      && (!text || `${ev.message} ${ev.symbol || ''}`.toLowerCase().includes(text));

    function row(ev) {
      const data = ev.data && typeof ev.data === 'object' && Object.keys(ev.data).length ? ev.data : null;
      const msg = h('td', { class: 'log-msg' }, ev.message);
      const tr = h('tr', { class: [`lvl-${ev.level}`, data && 'clickable'], title: data ? 'Click for details' : null },
        h('td', { class: 'num nowrap', title: fmtDateTime(ev.time) }, fmtDateTime(ev.time)),
        h('td', {}, levelBadge(ev.level)),
        h('td', {}, kindBadge(ev.kind)),
        h('td', { class: 'mono hide-sm' }, ev.symbol || ''),
        msg);
      if (data) {
        tr.tabIndex = 0;
        const toggle = () => {
          const pre = msg.querySelector('pre');
          if (pre) pre.remove(); else msg.appendChild(h('pre', { class: 'log-data mono' }, JSON.stringify(data, null, 2)));
        };
        tr.addEventListener('click', toggle);
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') toggle(); });
      }
      return tr;
    }
    function render() {
      const rows = events.filter(passes);
      pending = 0;
      renderPause();
      count.textContent = `${rows.length} of ${events.length} events`;
      if (!rows.length) mount(list, h('tr', { class: 'empty-row' }, h('td', { colspan: 5 }, 'No events match the filters')));
      else mount(list, rows.slice(0, 500).map(row));
    }

    const kindChips = chips(KINDS.map((k) => ({ value: k, label: k === 'daily_summary' ? 'summary' : k })), kinds, () => { persist(); load(); }, { label: 'Kinds' });
    const levelSeg = segmented(LEVELS.map((l) => ({ value: l, label: l === 'debug' ? 'Debug+' : l === 'info' ? 'Info+' : l === 'warning' ? 'Warn+' : 'Error' })), minLevel, (v) => { minLevel = v; persist(); render(); }, { label: 'Minimum level', size: 'sm' });
    const search = h('input', { class: 'input input-sm', type: 'search', placeholder: 'Search messages…', 'aria-label': 'Search messages', oninput: (e) => { text = e.target.value.trim().toLowerCase(); render(); } });
    const holder = h('div', {}, loading());

    mount(root, card({
      flush: true,
      body: h('div', {},
        h('div', { class: 'filters' },
          h('div', { class: 'filter-group filter-grow' }, kindChips),
          h('div', { class: 'filter-group' }, levelSeg),
          h('div', { class: 'filter-group' }, search),
          h('div', { class: 'filter-group' }, pauseBtn, count)),
        holder),
    }));

    async function load() {
      try {
        const k = [...kinds];
        const rows = k.length ? await api(`/api/events?limit=${MAX}&kinds=${encodeURIComponent(k.join(','))}`) : [];
        if (!ctx.alive) return;
        events = (rows || []).map((e) => ({ ...e, data: typeof e.data === 'string' ? safeParse(e.data) : e.data }));
        // The server persists only some kinds (not bar/log/backtest); add those from the live buffer.
        const persisted = new Set(events.map((e) => `${e.kind}|${e.message}`));
        const extra = stream.recent().filter((e) => kinds.has(e.kind) && !persisted.has(`${e.kind}|${e.message}`));
        if (extra.length) events = [...events, ...extra].sort((a, b) => Date.parse(b.time) - Date.parse(a.time)).slice(0, MAX);
        if (!holder.contains(table)) mount(holder, table);
        render();
      } catch (err) {
        if (ctx.alive) mount(holder, errorBox(err, load));
      }
    }
    await load();

    ctx.on('event', (ev) => {
      // bar events are not persisted by the server; logs from the stream are.
      if (events.some((e) => e.kind === ev.kind && e.message === ev.message && Math.abs(Date.parse(e.time) - Date.parse(ev.time)) < 2000)) return;
      events.unshift(ev);
      if (events.length > MAX) events.pop();
      if (!passes(ev)) { count.textContent = `${events.filter(passes).length} of ${events.length} events`; return; }
      if (paused) { pending += 1; renderPause(); return; }
      list.querySelector('.empty-row')?.remove();
      const tr = row(ev);
      tr.classList.add('row-new');
      list.prepend(tr);
      while (list.children.length > 500) list.lastElementChild.remove();
      count.textContent = `${events.filter(passes).length} of ${events.length} events`;
    });
  },
};

function safeParse(s) {
  if (s == null || typeof s === 'object') return s ?? null;
  try { return JSON.parse(s); } catch { return s ? { raw: s } : null; }
}
