import { t as translate, getLocale } from '../i18n.js';
// Screener: presets, run (optionally notify), results table with CSV export, history.

import { h, mount, fmtCompact, fmtPrice, fmtPctPts, fmtNum, fmtInt, fmtDateTime, fmtWhen, signCls, humanize } from '../core.js';
import { api, post, waitJob } from '../api.js';
import { app, go } from '../state.js';
import { card, btn, busy, dataTable, empty, errorBox, loading, callout, skeleton, downloadText, toCSV, toast, switchControl, kpi } from '../ui.js';
import { symLink } from '../common.js';
import { watchlistButton } from '../watchlist-store.js';

const PRICE_KEYS = new Set(['cur_price', 'last_price', 'price', 'close', 'open', 'high', 'low']);
const INT_KEYS = new Set(['lot_size', 'volume_today', 'volume']);

function ftoken(kind, text, accent) {
  return h('li', { class: ['ftoken', accent && 'accent'], title: text }, h('b', {}, translate(kind)), h('span', {}, text));
}

function filterText(f) {
  const range = [f.min != null ? `≥ ${fmtCompact(f.min)}` : null, f.max != null ? `≤ ${fmtCompact(f.max)}` : null].filter(Boolean).join(' ');
  const fieldLabel = (field) => translate(field);
  const extra = [
    f.days ? getLocale() === 'en' ? `${f.days}d` : translate('{count} days', { count: f.days }) : null,
    f.quarter ? translate(f.quarter) : null,
    f.ktype ? translate(f.ktype) : null,
    f.relative_position ? translate(f.relative_position) : null,
    f.field2 ? fieldLabel(f.field2) : null,
    f.value != null ? getLocale() === 'en' ? `value ${f.value}` : translate('Value: {value}', { value: f.value }) : null,
    f.sort ? getLocale() === 'en' ? `sort ${f.sort}` : translate('Sort: {direction}', { direction: translate(f.sort) }) : null,
    f.consecutive_period ? getLocale() === 'en' ? `${f.consecutive_period} periods` : translate('{count} periods', { count: f.consecutive_period }) : null,
  ].filter(Boolean).join(' · ');
  return `${fieldLabel(f.field)}${range ? ` ${range}` : ''}${extra ? ` (${extra})` : ''}`;
}

function formatCell(key, v) {
  if (v == null || v === '') return null;
  if (typeof v !== 'number') return key === 'signal' && ['buy today', 'long'].includes(v) ? translate(v) : String(v);
  if (key === 'change_pct') return h('span', { class: signCls(v) }, fmtPctPts(v));
  if (key.endsWith('_pct') || key.endsWith('_ratio')) return fmtNum(v, 2);
  if (PRICE_KEYS.has(key)) return h('span', { class: 'mono' }, fmtPrice(v));
  if (INT_KEYS.has(key)) return Math.abs(v) >= 1e7 ? fmtCompact(v) : fmtInt(v);
  if (Math.abs(v) >= 1e6) return h('span', { title: fmtNum(v, 0) }, fmtCompact(v));
  return Number.isInteger(v) ? fmtInt(v) : fmtNum(v, 2);
}

export default {
  title: () => translate('Screener'),
  async mount(root, { params, ctx }) {
    const presetsHolder = h('div', {}, card({ title: translate('Presets'), body: skeleton(4) }));
    const resultHolder = h('div', { id: 'screener-result' });
    const historyHolder = h('div', {}, card({ title: translate('History'), body: skeleton(3) }));
    mount(root, h('div', { class: 'screen-layout' }, h('div', { class: 'stack' }, presetsHolder, historyHolder), resultHolder));

    let presets;
    let selected = null;
    const presetName = (name) => presets?.[name]?.labels?.[getLocale()] || translate(name);
    const presetDescription = (preset) => preset.descriptions?.[getLocale()] || translate(preset.description);
    const notifySw = switchControl(translate('Email / Telegram the results'), false, { id: 'screen-notify' });
    const notifyChk = notifySw.input;
    const progress = h('div', { class: 'job-progress', hidden: true, 'aria-live': 'polite' });

    async function loadHistory() {
      try {
        const rows = await api('/api/screener/results');
        if (!ctx.alive) return;
        const t = dataTable({
          caption: translate('Screener history'), emptyText: translate('No saved results'), dense: true, maxHeight: '360px',
          onRowClick: (r) => go(`#/screener/${encodeURIComponent(r.id)}`),
          rowClass: (r) => (r.id === params[0] ? 'row-selected' : null),
          sort: { key: 'run_at', dir: 'desc' },
          columns: [
            { key: 'run_at', label: translate('Run'), render: (r) => h('span', { class: 'num', title: fmtDateTime(r.run_at) }, fmtWhen(r.run_at)) },
            { key: 'preset', label: translate('Preset'), render: (r) => h('span', { class: 'sym' }, presetName(r.preset)) },
            { key: 'count', label: translate('Rows'), num: true },
            { key: 'matched', label: translate('Matched'), num: true, render: (r) => fmtInt(r.matched) },
          ],
        });
        t.update(rows);
        mount(historyHolder, card({ title: translate('History'), subtitle: rows.length ? translate('{count} saved results', { count: rows.length }) : null, body: rows.length ? t.el : empty(translate('No results yet'), translate('Run a preset to screen the HK market.'), null, 'clock'), flush: true }));
      } catch (err) {
        if (ctx.alive) mount(historyHolder, card({ title: translate('History'), body: errorBox(err, loadHistory) }));
      }
    }

    function renderPresets() {
      const names = Object.keys(presets);
      if (!names.length) {
        mount(presetsHolder, card({ title: translate('Presets'), body: empty(translate('No screener presets'), translate('Define presets under screener.presets in the config.'), h('a', { class: 'btn', href: '#/settings' }, translate('Open settings')), 'filter') }));
        return;
      }
      const runBtn = btn(translate('Run screen'), { tone: 'primary', iconName: 'play', onclick: (e) => busy(e.currentTarget, run) });
      const list = h('div', { class: 'preset-list', role: 'radiogroup', 'aria-label': translate('Preset') }, names.map((name) => {
        const p = presets[name];
        const input = h('input', { type: 'radio', name: 'preset', value: name, checked: name === selected, onchange: () => { selected = name; } });
        return h('label', { class: 'preset' },
          input,
          h('div', { class: 'preset-body' },
            h('div', { class: 'preset-name' }, presetName(name)),
            p.description ? h('div', { class: 'preset-desc' }, presetDescription(p)) : null,
            h('ul', { class: 'preset-filters' },
              (p.filters || []).map((f) => ftoken(f.kind, filterText(f))),
              p.plate ? ftoken('plate', p.plate) : null,
              p.confirm_strategy ? ftoken('confirm', translate('{strategy} long on {timeframe}, top {count}', { strategy: p.confirm_strategy.name, timeframe: getLocale() === 'en' ? p.confirm_timeframe : translate(p.confirm_timeframe), count: p.max_confirm }), true) : null),
            h('div', { class: 'preset-meta' }, translate("{0} · up to {1} results", { 0: p.market, 1: p.max_results }))));
      }));
      mount(presetsHolder, card({
        title: translate('Presets'), subtitle: translate('Runs on Futu servers; uses no history quota'),
        body: h('div', { class: 'stack-sm' }, list,
          notifySw,
          h('div', { class: 'form-actions' }, runBtn, progress),
          (app.status?.notifications || []).length ? null : h('p', { class: 'muted small' }, translate('No notification channel is enabled, so results will not be sent.'))),
      }));
    }

    async function run() {
      if (!selected) { toast(translate('Pick a preset first'), 'warning'); return; }
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
          toast(translate("{0} stock(s) matched", { 0: final.result.count }), 'success', { title: translate("Screen {0}", { 0: presetName(selected) }) });
          go(`#/screener/${encodeURIComponent(final.result.id)}`);
        } else {
          mount(resultHolder, card({ title: translate('Screen failed'), body: callout('error', null, final.error || translate('Unknown error')) }));
          return;
        }
      } catch (err) {
        progress.hidden = true;
        mount(resultHolder, card({ title: translate('Screen failed'), body: errorBox(err) }));
      }
    }

    async function showResult(id) {
      mount(resultHolder, card({ title: translate('Result'), body: loading() }));
      try {
        const r = await api(`/api/screener/results/${encodeURIComponent(id)}`);
        if (!ctx.alive) return;
        const rows = r.rows || [];
        const keys = [];
        for (const row of rows) for (const k of Object.keys(row)) if (!keys.includes(k)) keys.push(k);
        const cols = keys.map((k) => {
          const numeric = rows.some((row) => typeof row[k] === 'number');
          return {
            key: k, label: translate(k) === k ? humanize(k) : translate(k), num: numeric,
            render: k === 'symbol' ? (row) => symLink(row.symbol, { tf: 'DAY' }) : k === 'name' ? null : (row) => formatCell(k, row[k]),
            cls: k === 'name' ? 'truncate' : null,
          };
        });
        cols.push({
          key: '_watchlist', label: translate('Watchlist'), sortable: false, cls: 'actions-cell',
          render: (row) => watchlistButton(row.symbol, row.name, { compact: true }),
        });
        const t = dataTable({ caption: translate("Screener result {0}", { 0: id }), columns: cols, emptyText: translate('No stock passed the filters'), maxHeight: '68vh', dense: true, onRowClick: (row) => row.symbol && go(`#/chart/${encodeURIComponent(row.symbol)}?tf=DAY`), rowTitle: (row) => (row.symbol ? translate("Open the {0} chart", { 0: row.symbol }) : '') });
        t.update(rows);
        const chg = rows.map((row) => row.change_pct).filter((v) => typeof v === 'number');
        const up = chg.filter((v) => v > 0).length;
        mount(resultHolder, card({
          title: h('span', {}, translate('Result '), h('span', { class: 'sym' }, presetName(r.preset))),
          subtitle: `${fmtDateTime(r.run_at)} HKT${r.confirmed_with ? ` · ${translate('confirmed with {strategy}', { strategy: r.confirmed_with })}` : ''}`,
          actions: btn('CSV', { size: 'sm', iconName: 'download', disabled: !rows.length, onclick: () => downloadText(`${id}.csv`, toCSV(keys, t.rows)) }),
          body: h('div', {},
            h('div', { class: 'kpis', style: { border: '0', borderRadius: '0', borderBottom: '1px solid var(--border)' } },
              kpi(translate('Matched'), fmtInt(r.matched ?? rows.length), { sub: translate("passed the server filters") }),
              kpi(translate('Shown'), fmtInt(rows.length), { sub: translate(r.confirmed_with ? 'after strategy confirmation' : 'rows in this result') }),
              chg.length ? kpi(translate('Up today'), `${fmtInt(up)} / ${fmtInt(chg.length)}`, { sub: translate("by change %") }) : null),
            r.warnings?.length ? h('div', { class: 'card-pad stack-sm' }, r.warnings.map((w) => callout('warning', null, w))) : null,
            t.el),
          flush: true,
        }));
      } catch (err) {
        if (ctx.alive) mount(resultHolder, card({ title: translate('Result'), body: err.status === 404 ? empty(translate('Result not found'), translate("No saved screener result {0}.", { 0: id }), null, 'filter') : errorBox(err, () => showResult(id)) }));
      }
    }

    try {
      presets = await api('/api/screener/presets');
    } catch (err) {
      if (ctx.alive) mount(presetsHolder, card({ title: translate('Presets'), body: errorBox(err) }));
      presets = null;
    }
    if (!ctx.alive) return;
    if (presets) {
      selected = Object.keys(presets)[0] || null;
      renderPresets();
    }
    loadHistory();
    if (params[0]) showResult(params[0]);
    else mount(resultHolder, card({ title: translate('Result'), body: empty(translate('No result selected'), translate('Run a preset, or open a past result from the history.'), null, 'filter') }));
    ctx.on('screener', () => loadHistory());
  },
};
