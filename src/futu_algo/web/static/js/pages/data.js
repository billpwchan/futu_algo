// Data: the local bar cache, Futu history quota, and a fetch form.

import { h, mount, fmtInt, fmtDate, fmtWhen, fmtDateTime, normalizeSymbol, todayHK } from '../core.js';
import { api, post, waitJob } from '../api.js';
import { app, go } from '../state.js';
import { card, btn, busy, dataTable, empty, errorBox, field, select, skeleton, callout, toast, meter } from '../ui.js';
import { symLink, TIMEFRAMES } from '../common.js';

const KTYPE_TF = { K_1M: '1M', K_3M: '3M', K_5M: '5M', K_15M: '15M', K_30M: '30M', K_60M: '60M', K_DAY: 'DAY', K_WEEK: 'WEEK', K_MON: 'MON' };

export default {
  title: () => 'Data',
  async mount(root, { ctx }) {
    const quotaHolder = h('div', {}, card({ body: skeleton(3) }));
    const seriesHolder = h('div', {}, card({ title: 'Cached series', body: skeleton(6) }));
    const formHolder = h('div');
    mount(root, quotaHolder, h('div', { class: 'grid-2-1' }, seriesHolder, formHolder));

    async function loadQuota() {
      try {
        const q = await api('/api/data/quota');
        if (!ctx.alive) return;
        if (q.offline) { mount(quotaHolder, callout('info', 'Offline mode', 'data.offline is on: bars come from the local cache only and no quota is used.')); return; }
        if (q.error) { mount(quotaHolder, callout('warning', 'Quota unavailable', q.error)); return; }
        const total = (q.used ?? 0) + (q.remaining ?? 0);
        const pctUsed = total ? q.used / total : 0;
        const symbols = q.symbols || [];
        mount(quotaHolder, card({
          title: 'History quota', subtitle: 'Distinct symbols downloaded from Futu in the last 30 days',
          body: h('div', { class: 'grid-1-2' },
            h('div', { class: 'quota-main' },
              h('div', { class: 'quota-figure' }, fmtInt(q.used), h('small', {}, ` of ${fmtInt(total)} used`)),
              meter(pctUsed, { label: 'History quota used', warnAt: 0.75, badAt: 0.9 }),
              h('div', { class: 'muted small' }, `${fmtInt(q.remaining)} symbols left. Re-fetching a symbol already in the window is free.`)),
            h('div', { class: 'stack-xs' },
              h('div', { class: 'section-label' }, `In this window (${fmtInt(symbols.length)})`),
              symbols.length
                ? h('div', { class: 'chips' }, symbols.slice(0, 40).map((sym) => h('a', { class: 'chip', href: `#/chart/${encodeURIComponent(sym)}?tf=DAY` }, sym)), symbols.length > 40 ? h('span', { class: 'muted small' }, `+${symbols.length - 40} more`) : null)
                : h('p', { class: 'muted small' }, 'No symbols downloaded in the last 30 days.'))),
        }));
      } catch (err) {
        if (ctx.alive) mount(quotaHolder, errorBox(err, loadQuota));
      }
    }

    async function loadSeries() {
      try {
        const rows = await api('/api/data/series');
        if (!ctx.alive) return;
        const t = dataTable({
          caption: 'Cached series', emptyText: 'Nothing cached', sort: { key: 'symbol', dir: 'asc' }, maxHeight: '64vh', dense: true,
          onRowClick: (r) => go(`#/chart/${encodeURIComponent(r.symbol)}?tf=${KTYPE_TF[r.ktype] || 'DAY'}`),
          rowTitle: (r) => `Open ${r.symbol} chart`,
          columns: [
            { key: 'symbol', label: 'Symbol', render: (r) => symLink(r.symbol, { tf: KTYPE_TF[r.ktype] }) },
            { key: 'ktype', label: 'K-type', render: (r) => h('span', { class: 'badge badge-neutral kind-badge' }, KTYPE_TF[r.ktype] || r.ktype) },
            { key: 'adjust', label: 'Adjust', cls: 'mono muted hide-sm' },
            { key: 'rows', label: 'Rows', num: true, render: (r) => fmtInt(r.rows) },
            { key: 'coverage', label: 'Coverage', value: (r) => (r.coverage || [])[0], render: (r) => h('span', { class: 'num' }, (r.coverage || []).map(fmtDate).join(' → ')) },
            { key: 'last_bar', label: 'Last bar', render: (r) => h('span', { class: 'num', title: fmtDateTime(r.last_bar) }, fmtDate(r.last_bar)) },
            { key: 'source', label: 'Source', cls: 'hide-sm' },
            { key: 'updated_at', label: 'Updated', render: (r) => h('span', { class: 'num', title: fmtDateTime(r.updated_at) }, fmtWhen(r.updated_at)), cls: 'hide-sm' },
          ],
        });
        t.update(rows || []);
        mount(seriesHolder, card({
          title: 'Cached series', subtitle: `${fmtInt((rows || []).length)} series · ${fmtInt((rows || []).reduce((a, r) => a + (r.rows || 0), 0))} bars in the local Parquet store`, flush: true,
          actions: btn('', { size: 'sm', tone: 'ghost', iconName: 'refresh', attrs: { 'aria-label': 'Reload' }, onclick: () => { loadSeries(); loadQuota(); } }),
          body: rows?.length ? t.el : empty('No cached data', 'Bars are cached the first time a backtest, chart or the engine needs them. Use the form to prefetch.', null, 'database'),
        }));
      } catch (err) {
        if (ctx.alive) mount(seriesHolder, card({ title: 'Cached series', body: errorBox(err, loadSeries) }));
      }
    }

    // ---------------------------------------------------------------- fetch form
    const symsIn = h('textarea', { class: 'input mono', rows: 3, placeholder: 'HK.00700, HK.09988 …', spellcheck: 'false', required: true }, (app.status?.trading?.symbols || []).join(', '));
    const tfSel = select(TIMEFRAMES, 'DAY');
    const d = new Date(); d.setFullYear(d.getFullYear() - 2);
    const startIn = h('input', { class: 'input num', type: 'date', value: d.toISOString().slice(0, 10), required: true });
    const endIn = h('input', { class: 'input num', type: 'date', value: '', max: todayHK() });
    const err = h('div', { class: 'form-error', role: 'alert', hidden: true });
    const progress = h('div', { class: 'job-progress', hidden: true, 'aria-live': 'polite' });
    const result = h('div');
    const fetchBtn = btn('Fetch bars', { type: 'submit', tone: 'primary', iconName: 'download' });
    const form = h('form', {
      class: 'stack-sm', novalidate: true,
      onsubmit: (e) => {
        e.preventDefault();
        busy(fetchBtn, async () => {
          const symbols = symsIn.value.split(/[\s,;]+/).map(normalizeSymbol).filter(Boolean);
          const problems = [];
          if (!symbols.length) problems.push('Enter at least one symbol.');
          if (!startIn.value) problems.push('Start date is required.');
          if (endIn.value && startIn.value && endIn.value < startIn.value) problems.push('End must be after start.');
          if (problems.length) { err.textContent = problems.join(' '); err.hidden = false; return; }
          err.hidden = true;
          mount(result);
          const started = Date.now();
          progress.hidden = false;
          const show = (job) => mount(progress, h('div', { class: 'job-row' }, h('span', { class: 'spinner' }), h('div', { class: 'job-text' }, h('div', { class: 'job-title' }, job.title), h('div', { class: 'job-msg' }, `${job.status}${job.message ? ` · ${job.message}` : ''} · ${Math.round((Date.now() - started) / 1000)}s`))));
          try {
            const job = await post('/api/data/fetch', { symbols, timeframe: tfSel.value, start: startIn.value, end: endIn.value || null });
            show(job);
            const final = await waitJob(job.id, { onProgress: show, isAlive: () => ctx.alive });
            if (!ctx.alive) return;
            progress.hidden = true;
            if (final.status === 'done') {
              const bars = final.result?.bars || {};
              toast(`Fetched ${Object.keys(bars).length} symbol(s)`, 'success');
              mount(result, callout('success', 'Fetch complete', h('ul', { class: 'plain-list' }, Object.entries(bars).map(([s, n]) => h('li', {}, h('span', { class: 'mono' }, s), `: ${fmtInt(n)} bars`)))),
                (final.result?.warnings || []).map((w) => callout('warning', null, w)));
              loadSeries(); loadQuota();
            } else mount(result, callout('error', 'Fetch failed', final.error || 'Unknown error'));
          } catch (ex) {
            progress.hidden = true;
            mount(result, callout('error', 'Fetch failed', ex.detail || ex.message));
          }
        });
      },
    },
    field('Symbols', symsIn, { hint: 'Comma or space separated' }),
    h('div', { class: 'form-grid' }, field('Timeframe', tfSel), field('Start', startIn), field('End', endIn, { hint: 'Blank = today' })),
    err,
    h('div', { class: 'form-actions' }, fetchBtn, progress),
    result);
    mount(formHolder, card({
      title: 'Fetch history', subtitle: 'Download K-lines into the local cache; new symbols use history quota',
      body: app.status?.offline ? h('div', { class: 'stack-sm' }, callout('info', null, 'The server runs offline; fetching needs an OpenD connection.'), form) : form,
    }));

    await Promise.all([loadQuota(), loadSeries()]);
  },
};
