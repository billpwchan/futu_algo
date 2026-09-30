// Screener: presets, run (optionally notify), results table with CSV export, history.

import { h, mount, fmtCompact, fmtPrice, fmtPctPts, fmtNum, fmtInt, fmtDateTime, fmtWhen, signCls, humanize } from '../core.js';
import { api, post, waitJob } from '../api.js';
import { app, go } from '../state.js';
import { card, btn, busy, dataTable, empty, errorBox, loading, badge, callout, skeleton, downloadText, toCSV, toast } from '../ui.js';
import { symLink } from '../common.js';

const PRICE_KEYS = new Set(['cur_price', 'last_price', 'price', 'close', 'open', 'high', 'low']);
const INT_KEYS = new Set(['lot_size', 'volume_today', 'volume']);

function filterText(f) {
  const range = [f.min != null ? `≥ ${fmtCompact(f.min)}` : null, f.max != null ? `≤ ${fmtCompact(f.max)}` : null].filter(Boolean).join(' ');
  const extra = [
    f.days ? `${f.days}d` : null, f.quarter, f.ktype, f.relative_position, f.field2, f.value != null ? `value ${f.value}` : null,
    f.sort ? `sort ${f.sort}` : null, f.consecutive_period ? `${f.consecutive_period} periods` : null,
  ].filter(Boolean).join(' · ');
  return `${f.field}${range ? ` ${range}` : ''}${extra ? ` (${extra})` : ''}`;
}

function formatCell(key, v) {
  if (v == null || v === '') return null;
  if (typeof v !== 'number') return String(v);
  if (key === 'change_pct') return h('span', { class: signCls(v) }, fmtPctPts(v));
  if (key.endsWith('_pct') || key.endsWith('_ratio')) return fmtNum(v, 2);
  if (PRICE_KEYS.has(key)) return h('span', { class: 'mono' }, fmtPrice(v));
  if (INT_KEYS.has(key)) return Math.abs(v) >= 1e7 ? fmtCompact(v) : fmtInt(v);
  if (Math.abs(v) >= 1e6) return h('span', { title: fmtNum(v, 0) }, fmtCompact(v));
  return Number.isInteger(v) ? fmtInt(v) : fmtNum(v, 2);
}

export default {
  title: () => 'Screener',
  async mount(root, { params, ctx }) {
    const presetsHolder = h('div', {}, card({ title: 'Presets', body: skeleton(4) }));
    const resultHolder = h('div');
    const historyHolder = h('div', {}, card({ title: 'History', body: skeleton(3) }));
    mount(root, h('div', { class: 'screen-layout' }, h('div', { class: 'stack' }, presetsHolder, historyHolder), resultHolder));

    let presets;
    let selected = null;
    const notifyChk = h('input', { type: 'checkbox', id: 'screen-notify' });
    const progress = h('div', { class: 'job-progress', hidden: true, 'aria-live': 'polite' });

    async function loadHistory() {
      try {
        const rows = await api('/api/screener/results');
        if (!ctx.alive) return;
        const t = dataTable({
          caption: 'Screener history', emptyText: 'No saved results', dense: true, maxHeight: '360px',
          onRowClick: (r) => go(`#/screener/${encodeURIComponent(r.id)}`),
          rowClass: (r) => (r.id === params[0] ? 'row-selected' : null),
          columns: [
            { key: 'run_at', label: 'Run', render: (r) => h('span', { class: 'num', title: fmtDateTime(r.run_at) }, fmtWhen(r.run_at)) },
            { key: 'preset', label: 'Preset', cls: 'mono' },
            { key: 'count', label: 'Rows', num: true },
            { key: 'matched', label: 'Matched', num: true },
          ],
        });
        t.update(rows);
        mount(historyHolder, card({ title: 'History', subtitle: `${rows.length} saved result(s)`, body: rows.length ? t.el : empty('No results yet', 'Run a preset to screen the HK market.'), flush: true }));
      } catch (err) {
        if (ctx.alive) mount(historyHolder, card({ title: 'History', body: errorBox(err, loadHistory) }));
      }
    }

    function renderPresets() {
      const names = Object.keys(presets);
      if (!names.length) {
        mount(presetsHolder, card({ title: 'Presets', body: empty('No screener presets', 'Define presets under screener.presets in the config.') }));
        return;
      }
      const runBtn = btn('Run screen', { tone: 'primary', iconName: 'play', onclick: (e) => busy(e.currentTarget, run) });
      const list = h('div', { class: 'preset-list', role: 'radiogroup', 'aria-label': 'Preset' }, names.map((name) => {
        const p = presets[name];
        const input = h('input', { type: 'radio', name: 'preset', value: name, checked: name === selected, onchange: () => { selected = name; } });
        return h('label', { class: 'preset' },
          input,
          h('div', { class: 'preset-body' },
            h('div', { class: 'preset-name mono' }, name),
            p.description ? h('div', { class: 'preset-desc' }, p.description) : null,
            h('ul', { class: 'preset-filters' },
              (p.filters || []).map((f) => h('li', {}, badge(f.kind, 'neutral'), h('span', { class: 'mono' }, filterText(f)))),
              p.plate ? h('li', {}, badge('plate', 'neutral'), h('span', { class: 'mono' }, p.plate)) : null,
              p.confirm_strategy ? h('li', {}, badge('confirm', 'accent'), h('span', {}, `${p.confirm_strategy.name} long on ${p.confirm_timeframe} (top ${p.max_confirm})`)) : null),
            h('div', { class: 'preset-meta muted' }, `${p.market} · max ${p.max_results} results`)));
      }));
      mount(presetsHolder, card({
        title: 'Presets', subtitle: 'Filters run on Futu servers across the whole market (no K-line quota)',
        body: h('div', { class: 'stack-sm' }, list,
          h('div', { class: 'form-actions' },
            runBtn,
            h('label', { class: 'check' }, notifyChk, h('span', {}, 'Email / Telegram the results')),
            progress),
          (app.status?.notifications || []).length ? null : h('p', { class: 'muted small' }, 'No notification channel is enabled, so results will not be sent.')),
      }));
    }

    async function run() {
      if (!selected) { toast('Pick a preset first', 'warning'); return; }
      const started = Date.now();
      progress.hidden = false;
      const show = (job) => mount(progress, h('div', { class: 'job-row' }, h('span', { class: 'spinner' }),
        h('div', { class: 'job-text' }, h('div', { class: 'job-title' }, job.title), h('div', { class: 'job-msg' }, `${job.status}${job.message ? ` · ${job.message}` : ''} · ${Math.round((Date.now() - started) / 1000)}s`))));
      try {
        const job = await post('/api/screener/run', { preset: selected, notify: notifyChk.checked });
        show(job);
        const final = await waitJob(job.id, { onProgress: show, isAlive: () => ctx.alive });
        if (!ctx.alive) return;
        progress.hidden = true;
        if (final.status === 'done' && final.result?.id) {
          toast(`${final.result.count} stock(s) matched`, 'success', { title: `Screen ${selected}` });
          go(`#/screener/${encodeURIComponent(final.result.id)}`);
        } else {
          mount(resultHolder, card({ title: 'Screen failed', body: callout('error', null, final.error || 'Unknown error') }));
        }
      } catch (err) {
        progress.hidden = true;
        mount(resultHolder, card({ title: 'Screen failed', body: errorBox(err) }));
      }
    }

    async function showResult(id) {
      mount(resultHolder, card({ title: 'Result', body: loading() }));
      try {
        const r = await api(`/api/screener/results/${encodeURIComponent(id)}`);
        if (!ctx.alive) return;
        const rows = r.rows || [];
        const keys = [];
        for (const row of rows) for (const k of Object.keys(row)) if (!keys.includes(k)) keys.push(k);
        const cols = keys.map((k) => {
          const numeric = rows.some((row) => typeof row[k] === 'number');
          return {
            key: k, label: humanize(k), num: numeric,
            render: k === 'symbol' ? (row) => symLink(row.symbol, { tf: 'DAY' }) : k === 'name' ? null : (row) => formatCell(k, row[k]),
            cls: k === 'name' ? 'truncate' : null,
          };
        });
        const t = dataTable({ caption: `Screener result ${id}`, columns: cols, emptyText: 'No stock passed the filters', sort: keys.includes('change_pct') ? null : null, maxHeight: '70vh', dense: true });
        t.update(rows);
        mount(resultHolder, card({
          title: h('span', {}, 'Result · ', h('span', { class: 'mono' }, r.preset)),
          subtitle: `${fmtDateTime(r.run_at)} HKT · ${rows.length} row(s) of ${r.matched ?? '?'} matched${r.confirmed_with ? ` · confirmed with ${r.confirmed_with}` : ''}`,
          actions: btn('CSV', { size: 'sm', tone: 'secondary', iconName: 'download', disabled: !rows.length, onclick: () => downloadText(`${id}.csv`, toCSV(keys, t.rows)) }),
          body: h('div', {}, r.warnings?.length ? h('div', { class: 'card-pad stack-sm' }, r.warnings.map((w) => callout('warning', null, w))) : null, t.el),
          flush: true,
        }));
      } catch (err) {
        if (ctx.alive) mount(resultHolder, card({ title: 'Result', body: err.status === 404 ? empty('Result not found', `No saved screener result ${id}.`) : errorBox(err, () => showResult(id)) }));
      }
    }

    try {
      presets = await api('/api/screener/presets');
    } catch (err) {
      if (ctx.alive) mount(presetsHolder, card({ title: 'Presets', body: errorBox(err) }));
      presets = null;
    }
    if (!ctx.alive) return;
    if (presets) {
      selected = Object.keys(presets)[0] || null;
      renderPresets();
    }
    loadHistory();
    if (params[0]) showResult(params[0]);
    else mount(resultHolder, card({ title: 'Result', body: empty('No result selected', 'Run a preset or open a past result from the history.') }));
    ctx.on('screener', () => loadHistory());
  },
};
