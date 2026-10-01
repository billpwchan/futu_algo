// Data: the local bar cache, Futu history quota, and a fetch form.

import { h, mount, fmtInt, fmtDate, fmtWhen, fmtDateTime, normalizeSymbol, todayHK } from '../core.js';
import { api, post, waitJob } from '../api.js';
import { app, go } from '../state.js';
import { card, kpi, btn, busy, dataTable, empty, errorBox, field, select, skeleton, callout, toast } from '../ui.js';
import { symLink, TIMEFRAMES } from '../common.js';

const KTYPE_TF = { K_1M: '1M', K_3M: '3M', K_5M: '5M', K_15M: '15M', K_30M: '30M', K_60M: '60M', K_DAY: 'DAY', K_WEEK: 'WEEK', K_MON: 'MON' };

export default {
  title: () => 'Data',
  async mount(root, { ctx }) {
    const quotaHolder = h('div', { class: 'kpis kpis-3' }, skeleton(2));
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
        mount(quotaHolder,
          kpi('History quota used', fmtInt(q.used), { sub: `of ${fmtInt(total)} symbols (30-day window)`, tone: pctUsed > 0.85 ? 'down' : '' }),
          kpi('Remaining', fmtInt(q.remaining), { sub: h('span', { class: 'meter', role: 'meter', 'aria-valuemin': '0', 'aria-valuemax': String(total), 'aria-valuenow': String(q.used), 'aria-label': 'Quota used' }, h('span', { class: 'meter-fill', style: { width: `${Math.round(pctUsed * 100)}%` } })) }),
          kpi('Symbols this window', fmtInt(q.symbols?.length ?? 0), { sub: (q.symbols || []).slice(0, 4).join(', ') + ((q.symbols || []).length > 4 ? ' …' : '') }));
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
            { key: 'ktype', label: 'K-type', cls: 'mono' },
            { key: 'adjust', label: 'Adjust', cls: 'mono hide-sm' },
            { key: 'rows', label: 'Rows', num: true, render: (r) => fmtInt(r.rows) },
            { key: 'coverage', label: 'Coverage', value: (r) => (r.coverage || [])[0], render: (r) => h('span', { class: 'num' }, (r.coverage || []).map(fmtDate).join(' → ')) },
            { key: 'last_bar', label: 'Last bar', render: (r) => h('span', { class: 'num', title: fmtDateTime(r.last_bar) }, fmtDate(r.last_bar)) },
            { key: 'source', label: 'Source', cls: 'hide-sm' },
            { key: 'updated_at', label: 'Updated', render: (r) => h('span', { class: 'num', title: fmtDateTime(r.updated_at) }, fmtWhen(r.updated_at)), cls: 'hide-sm' },
          ],
        });
        t.update(rows || []);
        mount(seriesHolder, card({
          title: 'Cached series', subtitle: `${(rows || []).length} series in the local store`, flush: true,
          actions: btn('', { size: 'sm', tone: 'ghost', iconName: 'refresh', attrs: { 'aria-label': 'Reload' }, onclick: () => { loadSeries(); loadQuota(); } }),
          body: rows?.length ? t.el : empty('No cached data', 'Bars are cached the first time a backtest, chart or the engine needs them. Use the form to prefetch.'),
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
      title: 'Fetch history', subtitle: 'Downloads into the local cache (uses history quota for new symbols)',
      body: app.status?.offline ? h('div', { class: 'stack-sm' }, callout('info', null, 'The server runs offline; fetching needs an OpenD connection.'), form) : form,
    }));

    await Promise.all([loadQuota(), loadSeries()]);
  },
};
