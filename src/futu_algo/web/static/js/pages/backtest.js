// Backtest: parameter form (from the strategy JSON schemas), job progress, saved runs and results.

import {
  h, mount, icon, storage, fmtMoney, fmtSignedMoney, fmtPct, fmtInt, fmtPrice, fmtRatio, fmtNum, fmtDate,
  fmtDateTime, fmtWhen, signCls, paramsText, normalizeSymbol, humanize, todayHK,
} from '../core.js';
import { api, post, del, waitJob } from '../api.js';
import { app, go, strategies } from '../state.js';
import {
  card, kpi, btn, busy, dataTable, empty, errorBox, loading, badge, callout, field, select, segmented, kv,
  toast, toastError, confirmDialog, skeleton, radioCards, switchControl, downloadText, toCSV,
} from '../ui.js';
import { TIMEFRAMES } from '../common.js';
import { candleChart, equityChart, histogram } from '../charts.js';

const DRAFT_KEY = 'futu_algo.backtestDraft';
const SIZERS = [
  { value: 'equal_weight', label: 'Equal weight', hint: 'Split equity equally across up to max positions' },
  { value: 'fixed_value', label: 'Fixed value', hint: 'A fixed HKD amount per position' },
  { value: 'fixed_lots', label: 'Fixed lots', hint: 'A fixed number of board lots per position' },
  { value: 'percent_equity', label: 'Percent of equity', hint: 'A fraction of current equity per position' },
  { value: 'all_in', label: 'All in', hint: 'Use all available cash (one position)' },
];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export default {
  title: ({ params }) => (params[0] ? 'Backtest report' : 'Backtest'),
  head: ({ params }) => !params[0],
  async mount(root, { params, query, ctx, setTitle }) {
    if (params[0]) return mountResult(root, params[0], ctx, setTitle);
    return mountForm(root, query, ctx);
  },
};

// =========================================================================== form + history

async function mountForm(root, query, ctx) {
  const formHolder = h('div', {}, card({ title: 'New backtest', body: skeleton(8) }));
  const historyHolder = h('div', { class: 'bt-side' }, card({ title: 'Saved runs', body: skeleton(5) }));
  mount(root, h('div', { class: 'bt-layout' }, formHolder, historyHolder));

  loadHistory(historyHolder, ctx);

  let defaults; let strats; let base;
  try {
    [defaults, strats] = await Promise.all([api('/api/backtests/defaults'), strategies()]);
    base = defaults;
    const from = query.get('from');
    if (from) {
      const res = await api(`/api/backtests/${encodeURIComponent(from)}`);
      base = { ...defaults, ...res.config, strategy: { name: res.strategy?.name || res.config.strategy?.name, params: res.strategy?.params || res.config.strategy?.params || {} } };
    } else {
      const draft = storage.get(DRAFT_KEY, null);
      if (draft) base = mergeDeep(defaults, draft);
    }
  } catch (err) {
    if (ctx.alive) mount(formHolder, card({ title: 'New backtest', body: errorBox(err, () => mountForm(root, query, ctx)) }));
    return;
  }
  if (!ctx.alive) return;
  mount(formHolder, buildForm(base, defaults, strats, ctx, query.get('from')));
}

function mergeDeep(a, b) {
  const out = { ...a };
  for (const [k, v] of Object.entries(b || {})) {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && a[k] && typeof a[k] === 'object' ? mergeDeep(a[k], v) : v;
  }
  return out;
}

const pctIn = (v) => (v == null ? '' : +(v * 100).toFixed(6));
const numOrNull = (el) => (el.value.trim() === '' ? null : Number(el.value));
const pctOrNull = (el) => (el.value.trim() === '' ? null : Number(el.value) / 100);

function numInput(value, attrs = {}) {
  return h('input', { class: 'input num', type: 'number', inputmode: 'decimal', value: value ?? '', step: 'any', ...attrs });
}

function buildForm(base, defaults, strats, ctx, fromId) {
  const err = h('div', { class: 'form-error', role: 'alert', hidden: true });
  const byName = Object.fromEntries(strats.map((s) => [s.name, s]));
  let stratName = byName[base.strategy?.name] ? base.strategy.name : strats[0]?.name;
  let paramValues = { ...(base.strategy?.params || {}) };

  // ---------------------------------------------------------------- strategy
  const stratSel = radioCards('bt-strategy', strats.map((s) => ({ value: s.name, title: s.title, sub: s.name, desc: s.description })), stratName, (v) => {
    stratName = v;
    paramValues = stratName === base.strategy?.name ? { ...(base.strategy?.params || {}) } : {};
    renderParams();
  }, { label: 'Strategy' });
  const stratInfo = h('div', { class: 'strategy-info' });
  const paramsGrid = h('div', { class: 'form-grid' });
  const paramInputs = new Map();

  function renderParams() {
    const s = byName[stratName];
    paramInputs.clear();
    mount(stratInfo, s.description ? h('p', { class: 'small text-2' }, s.description) : null, h('div', { class: 'meta-line' },
      badge(`warm-up ${s.warmup_bars} bars`, 'neutral'),
      s.plots?.length ? badge(`plots ${s.plots.map((p) => p.label).join(', ')}`, 'neutral') : null));
    const props = s.schema?.properties || {};
    mount(paramsGrid, Object.entries(props).map(([key, spec]) => {
      const cur = paramValues[key] ?? spec.default ?? s.params?.[key];
      let control;
      if (Array.isArray(spec.enum)) {
        control = select(spec.enum.map((v) => ({ value: v, label: String(v) })), cur);
      } else if (spec.type === 'boolean') {
        control = switchControl(spec.title || humanize(key), !!cur).input;
      } else if (spec.type === 'integer' || spec.type === 'number') {
        const min = spec.minimum ?? spec.exclusiveMinimum;
        const max = spec.maximum ?? spec.exclusiveMaximum;
        control = numInput(cur, { min, max, step: spec.type === 'integer' ? 1 : 'any', required: true });
      } else {
        control = h('input', { class: 'input', type: 'text', value: cur ?? '' });
      }
      paramInputs.set(key, { control, spec });
      const range = [spec.minimum != null ? `≥ ${spec.minimum}` : spec.exclusiveMinimum != null ? `> ${spec.exclusiveMinimum}` : null,
        spec.maximum != null ? `≤ ${spec.maximum}` : null].filter(Boolean).join(', ');
      const hint = [spec.description, range && `(${range})`].filter(Boolean).join(' ');
      if (spec.type === 'boolean') return h('div', { class: 'field' }, control.parentElement);
      return field(spec.title || humanize(key), control, { hint: hint || null });
    }));
    if (!Object.keys(props).length) mount(paramsGrid, h('p', { class: 'muted' }, 'This strategy has no parameters.'));
  }
  renderParams();

  function readParams() {
    const out = {};
    for (const [key, { control, spec }] of paramInputs) {
      if (spec.type === 'boolean') out[key] = control.checked;
      else if (spec.type === 'integer') out[key] = control.value === '' ? spec.default : parseInt(control.value, 10);
      else if (spec.type === 'number') out[key] = control.value === '' ? spec.default : Number(control.value);
      else out[key] = control.value;
    }
    return out;
  }

  // ---------------------------------------------------------------- symbols (chips)
  let symbols = [...(base.symbols || [])];
  const symChips = h('div', { class: 'tag-list' });
  const symInput = h('input', { class: 'tag-input mono', type: 'text', placeholder: symbols.length ? 'Add…' : 'HK.00700, 9988, …', 'aria-label': 'Add symbols', autocomplete: 'off', spellcheck: 'false' });
  const symBox = h('div', { class: 'tag-box input', onclick: () => symInput.focus() }, symChips, symInput);
  function renderSyms() {
    mount(symChips, symbols.map((s) => h('span', { class: 'tag mono' }, s,
      h('button', { type: 'button', class: 'tag-x', 'aria-label': `Remove ${s}`, onclick: (e) => { e.stopPropagation(); symbols = symbols.filter((x) => x !== s); renderSyms(); } }, icon('x', 12)))));
  }
  function addSyms(text) {
    for (const part of text.split(/[\s,;]+/)) {
      const s = normalizeSymbol(part);
      if (s && !symbols.includes(s)) symbols.push(s);
    }
    renderSyms();
  }
  symInput.addEventListener('keydown', (e) => {
    if (['Enter', ',', ' ', 'Tab'].includes(e.key) && symInput.value.trim()) {
      if (e.key !== 'Tab') e.preventDefault();
      addSyms(symInput.value); symInput.value = '';
    } else if (e.key === 'Backspace' && !symInput.value && symbols.length) {
      symbols.pop(); renderSyms();
    }
  });
  symInput.addEventListener('blur', () => { if (symInput.value.trim()) { addSyms(symInput.value); symInput.value = ''; } });
  symInput.addEventListener('paste', (e) => {
    const text = e.clipboardData?.getData('text');
    if (text && /[\s,;]/.test(text)) { e.preventDefault(); addSyms(text); }
  });
  renderSyms();
  const universe = app.status?.trading?.symbols || [];
  const symActions = h('div', { class: 'inline-actions' },
    universe.length ? btn('Use trading universe', { size: 'sm', tone: 'ghost', onclick: () => { symbols = [...universe]; renderSyms(); } }) : null,
    btn('Clear', { size: 'sm', tone: 'ghost', onclick: () => { symbols = []; renderSyms(); } }));

  // ---------------------------------------------------------------- other fields
  const tfSel = select(TIMEFRAMES.includes(base.timeframe) ? TIMEFRAMES : [base.timeframe, ...TIMEFRAMES], base.timeframe);
  const startIn = h('input', { class: 'input num', type: 'date', value: base.start || '', required: true });
  const endIn = h('input', { class: 'input num', type: 'date', value: base.end || '', max: todayHK() });
  const capitalIn = numInput(base.capital, { min: 1, step: 1000, required: true });
  const benchIn = h('input', { class: 'input mono', type: 'text', value: base.benchmark || '', placeholder: 'none (buy & hold)', spellcheck: 'false' });
  let mode = base.mode || 'portfolio';
  const modeHint = h('span', { class: 'field-hint' });
  const setModeHint = () => { modeHint.textContent = mode === 'scan' ? 'Each symbol trades alone with the full capital; a COMPOSITE book averages them.' : 'All symbols share one cash balance; the sizer allocates it.'; };
  const modeSeg = segmented([{ value: 'portfolio', label: 'Portfolio' }, { value: 'scan', label: 'Scan' }], mode, (v) => { mode = v; setModeHint(); syncSizing(); }, { label: 'Mode' });
  setModeHint();

  const sz = base.sizing || {};
  const methodSel = select(SIZERS.map((s) => ({ value: s.value, label: s.label })), sz.method || 'equal_weight');
  const maxPosIn = numInput(sz.max_positions ?? 5, { min: 1, step: 1 });
  const valueIn = numInput(sz.value, { min: 0, step: 1000, placeholder: 'e.g. 100000' });
  const lotsIn = numInput(sz.lots ?? 1, { min: 1, step: 1 });
  const percentIn = numInput(pctIn(sz.percent), { min: 0, max: 100, step: 'any', placeholder: 'e.g. 20' });
  const methodHint = h('span', { class: 'field-hint' });
  const fValue = field('Value per position (HKD)', valueIn);
  const fLots = field('Lots per position', lotsIn);
  const fPercent = field('Percent of equity (%)', percentIn);
  const fMax = field('Max positions', maxPosIn);
  function syncSizing() {
    const m = methodSel.value;
    methodHint.textContent = mode === 'scan' ? 'Scan mode sizes every symbol all-in; the sizer is ignored.' : SIZERS.find((s) => s.value === m)?.hint || '';
    fValue.hidden = m !== 'fixed_value';
    fLots.hidden = m !== 'fixed_lots';
    fPercent.hidden = m !== 'percent_equity';
    fMax.hidden = m === 'all_in';
  }
  methodSel.addEventListener('change', syncSizing);
  syncSizing();

  const ex = base.execution || {};
  const fillSel = select([{ value: 'next_open', label: 'Next bar open' }, { value: 'close', label: 'Signal bar close' }], ex.fill || 'next_open');
  const slipTicksIn = numInput(ex.slippage_ticks ?? 1, { min: 0, step: 'any' });
  const slipBpsIn = numInput(ex.slippage_bps ?? 0, { min: 0, step: 'any' });
  const freshSw = switchControl('Entries need a fresh signal', ex.entry_requires_fresh_signal !== false);
  const liqSw = switchControl('Liquidate at the end', !!ex.liquidate_at_end);
  const freshChk = freshSw.input;
  const liqChk = liqSw.input;

  const xt = base.exits || {};
  const stopIn = numInput(pctIn(xt.stop_loss), { min: 0, max: 99.99, placeholder: 'off' });
  const tpIn = numInput(pctIn(xt.take_profit), { min: 0, placeholder: 'off' });
  const trailIn = numInput(pctIn(xt.trailing_stop), { min: 0, max: 99.99, placeholder: 'off' });
  const maxBarsIn = numInput(xt.max_holding_bars, { min: 1, step: 1, placeholder: 'off' });
  const lookSw = switchControl('Check the strategy for look-ahead bias', base.check_lookahead !== false);
  const lookChk = lookSw.input;
  const rfIn = numInput(pctIn(base.risk_free_rate ?? 0), { step: 'any' });

  // ---------------------------------------------------------------- submit
  const runBtn = btn('Run backtest', { type: 'submit', tone: 'primary', iconName: 'play', size: 'lg' });
  const progress = h('div', { class: 'job-progress', hidden: true, 'aria-live': 'polite' });

  function collect() {
    const problems = [];
    if (symInput.value.trim()) { addSyms(symInput.value); symInput.value = ''; }
    if (!symbols.length) problems.push('Add at least one symbol.');
    if (!startIn.value) problems.push('Start date is required.');
    if (startIn.value && endIn.value && endIn.value <= startIn.value) problems.push('End date must be after the start date.');
    const capital = Number(capitalIn.value);
    if (!(capital > 0)) problems.push('Capital must be positive.');
    const m = methodSel.value;
    if (m === 'fixed_value' && !(Number(valueIn.value) > 0)) problems.push('Fixed value sizing needs a value per position.');
    if (m === 'percent_equity' && !(Number(percentIn.value) > 0 && Number(percentIn.value) <= 100)) problems.push('Percent of equity must be between 0 and 100.');
    for (const [key, { control, spec }] of paramInputs) {
      if (control.type === 'number' && control.value !== '' && !control.checkValidity()) problems.push(`${spec.title || key}: ${control.validationMessage}`);
    }
    const sl = pctOrNull(stopIn); const tr = pctOrNull(trailIn);
    if (sl != null && !(sl > 0 && sl < 1)) problems.push('Stop loss must be between 0 and 100%.');
    if (tr != null && !(tr > 0 && tr < 1)) problems.push('Trailing stop must be between 0 and 100%.');
    if (problems.length) return { problems };
    return {
      overrides: {
        symbols: [...symbols],
        strategy: { name: stratName, params: readParams() },
        timeframe: tfSel.value,
        start: startIn.value,
        end: endIn.value || null,
        capital,
        mode,
        benchmark: normalizeSymbol(benchIn.value) || null,
        sizing: {
          method: m,
          max_positions: parseInt(maxPosIn.value, 10) || 1,
          value: m === 'fixed_value' ? Number(valueIn.value) : numOrNull(valueIn),
          lots: parseInt(lotsIn.value, 10) || 1,
          percent: m === 'percent_equity' ? Number(percentIn.value) / 100 : pctOrNull(percentIn),
        },
        execution: {
          fill: fillSel.value,
          slippage_ticks: Number(slipTicksIn.value) || 0,
          slippage_bps: Number(slipBpsIn.value) || 0,
          entry_requires_fresh_signal: freshChk.checked,
          liquidate_at_end: liqChk.checked,
        },
        exits: {
          stop_loss: sl,
          take_profit: pctOrNull(tpIn),
          trailing_stop: tr,
          max_holding_bars: maxBarsIn.value === '' ? null : parseInt(maxBarsIn.value, 10),
        },
        check_lookahead: lookChk.checked,
        risk_free_rate: (Number(rfIn.value) || 0) / 100,
      },
    };
  }

  async function submit(e) {
    e.preventDefault();
    const out = collect();
    if (out.problems) {
      mount(err, h('strong', {}, 'Please fix:'), h('ul', {}, out.problems.map((p) => h('li', {}, p))));
      err.hidden = false;
      err.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      return;
    }
    err.hidden = true;
    storage.set(DRAFT_KEY, out.overrides);
    await busy(runBtn, async () => {
      const started = Date.now();
      progress.hidden = false;
      const renderProgress = (job) => mount(progress,
        h('div', { class: 'job-row' },
          h('span', { class: 'spinner' }),
          h('div', { class: 'job-text' }, h('div', { class: 'job-title' }, job.title || 'Backtest'), h('div', { class: 'job-msg' }, `${job.status}${job.message ? ` · ${job.message}` : ''} · ${Math.round((Date.now() - started) / 1000)}s`))));
      try {
        const job = await post('/api/backtests', { overrides: out.overrides });
        renderProgress(job);
        const final = await waitJob(job.id, { onProgress: renderProgress, isAlive: () => ctx.alive });
        if (!ctx.alive) {
          if (final.status === 'done') toast(`Backtest finished: ${final.title}`, 'success');
          return;
        }
        if (final.status === 'done' && final.result?.id) {
          go(`#/backtest/${encodeURIComponent(final.result.id)}`);
        } else {
          progress.hidden = true;
          mount(err, h('strong', {}, 'Backtest failed'), h('div', { class: 'pre-wrap' }, final.error || 'Unknown error'));
          err.hidden = false;
        }
      } catch (ex2) {
        progress.hidden = true;
        mount(err, h('strong', {}, 'Could not start the backtest'), h('div', { class: 'pre-wrap' }, ex2.detail || ex2.message));
        err.hidden = false;
      }
    });
  }

  let stepNo = 0;
  const section = (title, ...children) => h('fieldset', { class: 'form-section' }, h('legend', {}, h('span', { class: 'step' }, String(++stepNo)), title), ...children);
  const form = h('form', { class: 'bt-form', onsubmit: submit, novalidate: true },
    section('Strategy', stratSel, stratInfo, paramsGrid),
    section('Universe',
      field('Symbols', symBox, { hint: 'Type or paste codes; Enter or comma adds one. 700 becomes HK.00700.' }),
      symActions,
      h('div', { class: 'form-grid' }, field('Benchmark', benchIn, { hint: 'Index or stock; blank compares with buy & hold' }))),
    section('Period & capital',
      h('div', { class: 'form-grid' },
        field('Timeframe', tfSel),
        field('Start', startIn),
        field('End', endIn, { hint: 'Blank means today' }),
        field('Capital (HKD)', capitalIn)),
      h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Mode'), modeSeg, modeHint)),
    section('Position sizing',
      h('div', { class: 'form-grid' }, field('Method', methodSel), fMax, fValue, fLots, fPercent),
      methodHint),
    section('Execution & exits',
      h('div', { class: 'form-grid' },
        field('Fill price', fillSel),
        field('Slippage (ticks)', slipTicksIn),
        field('Slippage (bps)', slipBpsIn)),
      h('div', { class: 'checks' }, freshSw, liqSw),
      h('div', { class: 'form-grid' },
        field('Stop loss (%)', stopIn, { hint: 'Below entry' }),
        field('Take profit (%)', tpIn, { hint: 'Above entry' }),
        field('Trailing stop (%)', trailIn, { hint: 'Below the peak' }),
        field('Max holding bars', maxBarsIn))),
    section('Checks',
      h('div', { class: 'form-grid' }, field('Risk-free rate (%)', rfIn, { hint: 'For Sharpe and Sortino' })),
      h('div', { class: 'checks' }, lookSw)),
    err,
    h('div', { class: 'run-bar' },
      runBtn,
      btn('Reset to config defaults', { tone: 'ghost', onclick: () => { storage.set(DRAFT_KEY, null); go('#/backtest'); } }),
      progress));

  return card({
    title: fromId ? 'Edit & re-run' : 'New backtest',
    subtitle: fromId ? `Settings loaded from run ${fromId}` : 'Overrides on top of the backtest section of the config',
    body: form,
    cls: 'bt-card',
    flush: true,
  });
}

async function loadHistory(holder, ctx) {
  try {
    const rows = (await api('/api/backtests')) || [];
    if (!ctx.alive) return;
    rows.sort((a, b) => String(b.finished_at).localeCompare(String(a.finished_at)));
    const item = (r) => {
      const syms = r.symbols || [];
      const open = () => go(`#/backtest/${encodeURIComponent(r.id)}`);
      return h('div', {
        class: 'run-item', role: 'link', tabIndex: 0, title: `Open run ${r.id}`,
        onclick: (e) => { if (!e.target.closest('button')) open(); },
        onkeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) open(); },
      },
      h('div', { class: 'run-title' }, h('span', {}, r.strategy), badge(r.timeframe, 'neutral'), r.mode === 'scan' ? badge('scan', 'accent') : null),
      h('div', { class: ['run-ret', signCls(r.total_return)] }, fmtPct(r.total_return, 1)),
      h('div', { class: 'run-meta', title: syms.join(', ') }, `${syms.slice(0, 3).join(', ')}${syms.length > 3 ? ` +${syms.length - 3}` : ''} · ${fmtWhen(r.finished_at)}`),
      h('div', { class: 'run-stats' }, h('span', {}, 'SR ', h('b', {}, fmtRatio(r.sharpe))), h('span', {}, 'DD ', h('b', {}, fmtPct(r.max_drawdown, 0))), h('span', {}, h('b', {}, fmtInt(r.trades)), ' tr')),
      h('button', {
        type: 'button', class: 'icon-btn icon-btn-danger', 'aria-label': `Delete run ${r.id}`, title: 'Delete',
        onclick: async (e) => { e.stopPropagation(); if (await deleteRun(r.id)) loadHistory(holder, ctx); },
      }, icon('trash', 15)));
    };
    mount(holder, card({
      title: 'Saved runs', subtitle: rows.length ? `${rows.length} report${rows.length === 1 ? '' : 's'} on disk` : null, flush: true,
      body: rows.length ? h('div', { class: 'run-list' }, rows.map(item)) : empty('No backtests yet', 'Run one with the form; every report is saved and listed here.', null, 'flask'),
    }));
  } catch (err) {
    if (ctx.alive) mount(holder, card({ title: 'Saved runs', body: errorBox(err, () => loadHistory(holder, ctx)) }));
  }
}

async function deleteRun(id) {
  const ok = await confirmDialog('Delete this backtest?', `The saved report ${id} (result, trades and CSV files) will be removed from disk.`, { confirmLabel: 'Delete', danger: true });
  if (!ok) return false;
  try {
    await del(`/api/backtests/${encodeURIComponent(id)}`);
    toast('Backtest deleted', 'success');
    return true;
  } catch (err) {
    toastError(err, 'Delete failed');
    return false;
  }
}

// =========================================================================== results

async function mountResult(root, id, ctx, setTitle) {
  mount(root, loading('Loading backtest…'));
  let res;
  try {
    res = await api(`/api/backtests/${encodeURIComponent(id)}`);
  } catch (err) {
    if (!ctx.alive) return;
    mount(root, h('div', { class: 'stack' },
      h('a', { href: '#/backtest', class: 'back-link' }, icon('arrowLeft', 14), 'All backtests'),
      err.status === 404 ? card({ body: empty('Backtest not found', `No saved run named ${id}. It may have been deleted.`, btn('Back to backtests', { onclick: () => go('#/backtest') }), 'flask') }) : errorBox(err, () => mountResult(root, id, ctx, setTitle))));
    return;
  }
  if (!ctx.alive) return;
  const cfg = res.config || {};
  const strat = res.strategy || {};
  setTitle(`${strat.title || strat.name} · ${cfg.timeframe}`);
  const books = Object.keys(res.books || {});
  let bookName = res.primary && res.books[res.primary] ? res.primary : books[0];
  const syms = cfg.symbols || [];

  const header = h('section', { class: 'card result-head' },
    h('div', { style: { flex: '1 1 420px', minWidth: '0' } },
      h('a', { href: '#/backtest', class: 'back-link' }, icon('arrowLeft', 14), 'All backtests'),
      h('h1', { class: 'result-title' }, strat.title || strat.name, h('span', { class: 'title-params mono' }, paramsText(strat.params))),
      h('div', { class: 'meta-line', style: { marginTop: '8px' } },
        badge(cfg.mode, 'accent'), badge(cfg.timeframe, 'neutral'),
        h('span', { class: 'num' }, `${fmtDate(cfg.start)} → ${cfg.end ? fmtDate(cfg.end) : fmtDate(res.finished_at)}`),
        h('span', { title: syms.join(', ') }, syms.length <= 4 ? syms.join(', ') : `${syms.length} symbols`),
        h('span', { class: 'num' }, `HK$${fmtMoney(cfg.capital, 0)}`),
        h('span', {}, `run ${fmtDateTime(res.finished_at, { seconds: false })}`))),
    h('div', { class: 'page-actions' },
      btn('Edit & re-run', { iconName: 'sliders', onclick: () => go(`#/backtest?from=${encodeURIComponent(id)}`) }),
      btn('', { tone: 'ghost-danger', iconName: 'trash', title: 'Delete this report', attrs: { 'aria-label': 'Delete this report' }, onclick: async () => { if (await deleteRun(id)) go('#/backtest'); } })));

  const bookBar = h('div', { class: 'book-bar' });
  const bookBody = h('div', { class: 'stack' });
  const symbolSection = h('div');
  const warnings = warningsCard(res);

  mount(root, header, bookBar, bookBody, symbolSection, warnings);

  let bookCtx = null;
  function selectBook(name) {
    bookName = name;
    bookCtx?.dispose();
    bookCtx = ctx.child();
    renderBook(bookBody, res, name, bookCtx);
    renderSymbols(symbolSection, res, name, bookCtx);
  }
  if (books.length > 1) {
    const opts = books.map((b) => ({ value: b, label: b }));
    mount(bookBar,
      h('span', { class: 'book-label' }, 'Book'),
      books.length <= 8 ? segmented(opts, bookName, selectBook, { label: 'Book', cls: 'segmented-mono' }) : select(opts, bookName, { class: 'input input-sm', onchange: (e) => selectBook(e.target.value), 'aria-label': 'Book' }),
      h('span', { class: 'muted book-hint' }, cfg.mode === 'scan' ? 'Scan mode: each symbol trades alone with the full capital; COMPOSITE averages them.' : ''));
    bookBar.after(booksTable(res, (b) => { selectBook(b); bookBar.querySelector('.segmented')?.set?.(b); }));
  } else bookBar.remove();
  selectBook(bookName);
}

function booksTable(res, onPick) {
  const rows = Object.entries(res.books).map(([name, b]) => ({ name, ...b.metrics }));
  const t = dataTable({
    caption: 'Books',
    sort: { key: 'total_return', dir: 'desc' },
    onRowClick: (r) => onPick(r.name),
    dense: true,
    maxHeight: '300px',
    columns: [
      { key: 'name', label: 'Book', render: (r) => h('span', { class: 'sym' }, r.name) },
      { key: 'total_return', label: 'Return', num: true, render: (r) => h('span', { class: signCls(r.total_return) }, fmtPct(r.total_return)) },
      { key: 'cagr', label: 'CAGR', num: true, render: (r) => fmtPct(r.cagr), cls: 'hide-sm' },
      { key: 'sharpe', label: 'Sharpe', num: true, render: (r) => fmtRatio(r.sharpe) },
      { key: 'max_drawdown', label: 'Max DD', num: true, render: (r) => fmtPct(r.max_drawdown, 1) },
      { key: 'win_rate', label: 'Win rate', num: true, render: (r) => fmtPct(r.win_rate, 0, false), cls: 'hide-sm' },
      { key: 'trades', label: 'Trades', num: true },
      { key: 'buy_hold_return', label: 'Buy & hold', num: true, render: (r) => h('span', { class: signCls(r.buy_hold_return) }, fmtPct(r.buy_hold_return)), cls: 'hide-sm' },
    ],
  });
  t.update(rows);
  return card({ title: 'Books', subtitle: 'Select a row to inspect that book', body: t.el, flush: true });
}

function renderBook(holder, res, name, ctx) {
  const book = res.books[name];
  const m = book.metrics || {};
  const excess = m.excess_return ?? (m.benchmark_total_return != null ? m.total_return - m.benchmark_total_return : null);
  const benchName = book.benchmark_name || 'Benchmark';
  const startEq = m.start_equity ?? res.config?.capital;

  const tear = h('div', { class: 'tear' },
    kpi('Total return', fmtPct(m.total_return), {
      cls: 'tear-hero', tone: signCls(m.total_return),
      sub: h('span', {}, `HK$${fmtMoney(m.final_equity, 0)} final · `, h('span', { class: signCls(excess) }, `${fmtPct(excess)} vs ${benchName}`)),
    }),
    kpi('CAGR', fmtPct(m.cagr), { tone: signCls(m.cagr), sub: `${fmtNum(m.years, 2)} years` }),
    kpi('Sharpe', fmtRatio(m.sharpe), { sub: `Sortino ${fmtRatio(m.sortino)}` }),
    kpi('Max drawdown', fmtPct(m.max_drawdown), { tone: 'down', sub: m.max_drawdown_days != null ? `${fmtInt(m.max_drawdown_days)} days to recover` : 'never recovered' }),
    kpi('Win rate', fmtPct(m.win_rate, 1, false), { sub: `Profit factor ${fmtRatio(m.profit_factor)}` }),
    kpi('Trades', fmtInt(m.trades), { sub: `avg ${fmtNum(m.avg_bars_held, 1)} bars held${m.open_trades ? ` · ${m.open_trades} open` : ''}` }));

  const secondary = h('div', { class: 'kpis kpis-bt' },
    kpi('Volatility', fmtPct(m.volatility, 1, false), { sub: 'annualised' }),
    kpi('Calmar', fmtRatio(m.calmar), { sub: 'CAGR / max DD' }),
    kpi('Expectancy', fmtSignedMoney(m.expectancy, 0), { tone: signCls(m.expectancy), sub: `payoff ${fmtRatio(m.payoff_ratio)}` }),
    kpi('Exposure', fmtPct(m.exposure, 1, false), { sub: `in market ${fmtPct(m.time_in_market, 0, false)}` }),
    kpi('Fees', `HK$${fmtMoney(m.total_fees, 0)}`, { sub: `${fmtPct(m.fees_pct_of_capital, 2, false)} of capital` }),
    kpi(benchName, fmtPct(m.benchmark_total_return ?? m.buy_hold_return), { tone: signCls(m.benchmark_total_return ?? m.buy_hold_return), sub: m.beta != null ? `beta ${fmtRatio(m.beta)} · alpha ${fmtPct(m.alpha)}` : 'same period' }));

  // equity chart: the strategy as a baseline around starting equity, comparisons as lines
  const chartEl = h('div', { class: 'chart chart-lg' });
  const lines = [{ name: 'Strategy', data: book.equity || [] }];
  if (book.benchmark?.length) lines.push({ name: benchName, data: book.benchmark });
  if (book.buy_hold?.length && benchName !== 'Buy & hold') lines.push({ name: 'Buy & hold', data: book.buy_hold, style: 2 });
  const equityCard = card({
    title: 'Equity curve', subtitle: `${book.currency || 'HKD'} · shaded against starting capital · drawdown below · click the legend to toggle`,
    body: h('div', { class: 'chart-wrap' }, book.equity?.length ? chartEl : empty('No equity data')), cls: 'card-chart',
  });

  // trade return distribution
  const trades = book.trades || [];
  const closedTrades = trades.filter((t) => !t.is_open && Number.isFinite(t.return_pct));
  const rets = closedTrades.map((t) => t.return_pct).sort((a, b) => a - b);
  const median = rets.length ? rets[Math.floor(rets.length / 2)] : null;
  const mean = rets.length ? rets.reduce((a, b) => a + b, 0) / rets.length : null;
  const distEl = h('div', { class: 'viz-wrap' });
  const distCard = card({
    title: 'Trade returns', subtitle: rets.length ? `${fmtInt(rets.length)} closed trades · mean ${fmtPct(mean)} · median ${fmtPct(median)}` : 'No closed trades',
    body: rets.length ? distEl : empty('No closed trades', null, null, 'activity'),
  });

  const monthlyCard = card({
    title: 'Monthly returns',
    actions: h('span', { class: 'heat-legend' }, 'loss', h('span', { class: 'heat-scale', 'aria-hidden': 'true' }), 'gain'),
    body: monthlyTable(book.monthly || {}), flush: true,
  });

  // trades
  const tradeSyms = [...new Set(trades.map((t) => t.symbol))].sort();
  let symFilter = '';
  const tradeTable = dataTable({
    caption: 'Trades',
    emptyText: 'No trades',
    sort: { key: 'entry_time', dir: 'desc' },
    dense: true,
    maxHeight: '480px',
    columns: [
      { key: 'symbol', label: 'Symbol', render: (t) => h('span', { class: 'sym' }, t.symbol) },
      { key: 'entry_time', label: 'Entry', render: (t) => h('span', { class: 'num' }, fmtDate(t.entry_time)) },
      { key: 'exit_time', label: 'Exit', render: (t) => (t.is_open ? badge('open', 'info') : h('span', { class: 'num' }, fmtDate(t.exit_time))) },
      { key: 'quantity', label: 'Qty', num: true, render: (t) => fmtInt(t.quantity) },
      { key: 'entry_price', label: 'Entry px', num: true, render: (t) => fmtPrice(t.entry_price) },
      { key: 'exit_price', label: 'Exit px', num: true, render: (t) => fmtPrice(t.exit_price) },
      { key: 'pnl', label: 'P/L', num: true, render: (t) => h('span', { class: signCls(t.pnl) }, fmtSignedMoney(t.pnl, 0)) },
      { key: 'return_pct', label: 'Return', num: true, render: (t) => h('span', { class: signCls(t.return_pct) }, fmtPct(t.return_pct)) },
      { key: 'fees', label: 'Fees', num: true, render: (t) => fmtMoney(t.fees, 0), cls: 'hide-sm' },
      { key: 'bars_held', label: 'Bars', num: true, cls: 'hide-sm' },
      { key: 'mae_pct', label: 'MAE', num: true, render: (t) => fmtPct(t.mae_pct, 1), cls: 'hide-sm', title: 'Maximum adverse excursion' },
      { key: 'mfe_pct', label: 'MFE', num: true, render: (t) => fmtPct(t.mfe_pct, 1), cls: 'hide-sm', title: 'Maximum favourable excursion' },
      { key: 'exit_reason', label: 'Exit', render: (t) => badge(t.exit_reason, t.exit_reason === 'signal' ? 'neutral' : t.exit_reason === 'open' ? 'info' : 'warn') },
    ],
  });
  const applyTradeFilter = () => tradeTable.update(symFilter ? trades.filter((t) => t.symbol === symFilter) : trades);
  applyTradeFilter();
  const wins = trades.filter((t) => !t.is_open && t.pnl > 0).length;
  const tradesCard = card({
    title: 'Trades', subtitle: `${fmtInt(trades.length)} round trips · ${wins} of ${closedTrades.length} closed trades won`,
    actions: [
      tradeSyms.length > 1 ? select([{ value: '', label: 'All symbols' }, ...tradeSyms.map((s) => ({ value: s, label: s }))], '', { 'aria-label': 'Filter trades by symbol', class: 'input input-sm', onchange: (e) => { symFilter = e.target.value; applyTradeFilter(); } }) : null,
      btn('CSV', { size: 'sm', iconName: 'download', disabled: !trades.length, onclick: () => downloadText(`${res.id || 'backtest'}-${name}-trades.csv`, toCSV(Object.keys(trades[0] || {}), tradeTable.rows)) }),
    ],
    body: tradeTable.el, flush: true,
  });

  // drawdown periods + extra metrics
  const dds = [...(book.drawdowns || [])].sort((a, b) => (a.depth ?? 0) - (b.depth ?? 0)).slice(0, 6);
  const ddTable = dataTable({
    caption: 'Worst drawdowns', emptyText: 'No drawdowns', dense: true,
    columns: [
      { key: 'depth', label: 'Depth', num: true, render: (d) => h('span', { class: 'down' }, fmtPct(d.depth, 1)) },
      { key: 'start', label: 'Peak', render: (d) => h('span', { class: 'num' }, fmtDate(d.start)) },
      { key: 'trough', label: 'Trough', render: (d) => h('span', { class: 'num' }, fmtDate(d.trough)) },
      { key: 'end', label: 'Recovered', render: (d) => (d.recovered ? h('span', { class: 'num' }, fmtDate(d.end)) : badge('not yet', 'warn')) },
      { key: 'days', label: 'Days', num: true, render: (d) => fmtInt(d.days) },
    ],
  });
  ddTable.update(dds);
  const extra = kv([
    ['Start equity', fmtMoney(m.start_equity, 0)],
    ['Final equity', fmtMoney(m.final_equity, 0)],
    ['Realized P/L', h('span', { class: signCls(m.realized_pnl) }, fmtSignedMoney(m.realized_pnl, 0))],
    ['Unrealized P/L', h('span', { class: signCls(m.unrealized_pnl) }, fmtSignedMoney(m.unrealized_pnl, 0))],
    ['Turnover', `${fmtNum(m.turnover, 2)}×`],
    ['Avg win / loss', `${fmtMoney(m.avg_win, 0)} / ${fmtMoney(m.avg_loss, 0)}`],
    ['Largest win / loss', `${fmtMoney(m.largest_win, 0)} / ${fmtMoney(m.largest_loss, 0)}`],
    ['Max consecutive W / L', `${fmtInt(m.max_consecutive_wins)} / ${fmtInt(m.max_consecutive_losses)}`],
    ['VaR / CVaR 95%', `${fmtPct(m.var_95)} / ${fmtPct(m.cvar_95)}`],
    ['Best / worst bar', `${fmtPct(m.best_bar)} / ${fmtPct(m.worst_bar)}`],
    m.information_ratio != null ? ['Information ratio', fmtRatio(m.information_ratio)] : null,
    m.exit_reasons ? ['Exit reasons', Object.entries(m.exit_reasons).map(([k, v]) => `${k} ${v}`).join(', ')] : null,
  ]);

  mount(holder,
    tear,
    secondary,
    equityCard,
    monthlyCard,
    h('div', { class: 'grid-2' },
      card({ title: 'Statistics', body: extra }),
      h('div', { class: 'stack' }, distCard, card({ title: 'Worst drawdowns', body: ddTable.el, flush: true }))),
    tradesCard);

  if (book.equity?.length && window.LightweightCharts) {
    ctx.own(equityChart(chartEl, { lines, drawdown: book.drawdown, baseline: startEq }));
  }
  if (rets.length) ctx.own(histogram(distEl, rets));
}

function monthlyTable(monthly) {
  const years = Object.keys(monthly).sort();
  if (!years.length) return empty('No monthly data', null, null, 'clock');
  let maxAbs = 0;
  for (const y of years) for (let i = 1; i <= 12; i++) { const v = monthly[y][String(i)]; if (typeof v === 'number') maxAbs = Math.max(maxAbs, Math.abs(v)); }
  const cell = (v, isYear = false) => {
    if (typeof v !== 'number') return h('td', { class: 'num heat-empty' }, '');
    const intensity = maxAbs ? Math.min(1, Math.abs(v) / (isYear ? Math.max(maxAbs * 3, Math.abs(v)) : maxAbs)) : 0;
    const pct = Math.round(8 + intensity * 52);
    const color = v >= 0 ? 'var(--up)' : 'var(--down)';
    return h('td', { class: ['num', 'heat', isYear && 'heat-year'], style: { background: `color-mix(in srgb, ${color} ${pct}%, var(--surface))` }, title: fmtPct(v, 2) }, fmtPct(v, 1));
  };
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table heatmap' },
    h('caption', { class: 'sr-only' }, 'Monthly returns by year'),
    h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, ''), MONTHS.map((mo) => h('th', { scope: 'col', class: 'num' }, mo)), h('th', { scope: 'col', class: 'num' }, 'Year'))),
    h('tbody', {}, years.map((y) => h('tr', {}, h('th', { scope: 'row', class: 'num' }, y), Array.from({ length: 12 }, (_, i) => cell(monthly[y][String(i + 1)])), cell(monthly[y].year, true))))));
}

function renderSymbols(holder, res, bookName, ctx) {
  const syms = Object.keys(res.symbols || {});
  if (!syms.length) { holder.replaceChildren(); return; }
  let current = res.symbols[bookName] ? bookName : syms[0];
  const chartEl = h('div', { class: 'chart chart-lg' });
  const wrap = h('div', { class: 'chart-wrap' }, chartEl);
  const sub = h('span');
  const openLink = h('a', { class: 'link-sm' }, 'Open chart', icon('arrowUpRight', 13));
  let chartCtx = null;
  const draw = () => {
    chartCtx?.dispose();
    chartCtx = ctx.child();
    const s = res.symbols[current];
    const book = res.books[bookName];
    const bookSyms = new Set((book?.trades || []).map((t) => t.symbol));
    sub.textContent = `${s.name || ''}${s.name ? ' · ' : ''}lot ${fmtInt(s.lot_size)} · ${fmtInt(s.candles.length)} bars · ${fmtInt(s.markers.length)} fills${bookSyms.size && !bookSyms.has(current) ? ' (not traded in this book)' : ''}`;
    openLink.href = `#/chart/${encodeURIComponent(current)}?tf=${encodeURIComponent(res.config?.timeframe || 'DAY')}`;
    if (!s.candles.length || !window.LightweightCharts) { mount(wrap, empty('No bars for this symbol')); return; }
    mount(wrap, chartEl);
    chartCtx.own(candleChart(chartEl, { ...s, symbol: current, markerText: false }));
  };
  const picker = syms.length > 1
    ? (syms.length <= 6
      ? segmented(syms.map((s) => ({ value: s, label: s })), current, (v) => { current = v; draw(); }, { label: 'Symbol', size: 'sm', cls: 'segmented-mono' })
      : select(syms.map((s) => ({ value: s, label: s })), current, { class: 'input input-sm', 'aria-label': 'Symbol', onchange: (e) => { current = e.target.value; draw(); } }))
    : null;
  mount(holder, card({ title: 'Price & fills', subtitle: sub, actions: [picker, openLink], body: wrap, cls: 'card-chart' }));
  draw();
}

function warningsCard(res) {
  const items = [];
  const la = res.lookahead;
  if (la) items.push(la.ok ? callout('success', 'Look-ahead check passed', la.summary) : callout('error', 'Look-ahead bias detected', `${la.summary}. Results are not trustworthy until the strategy is fixed.`));
  else items.push(callout('info', 'Look-ahead check skipped', 'Enable "Check the strategy for look-ahead bias" to verify the strategy.'));
  for (const w of res.warnings || []) items.push(callout('warning', null, w));
  const costs = res.costs || {};
  const hk = costs.HK || {};
  const costLine = costs.model === 'simple'
    ? 'Simple cost model'
    : `HK commission ${fmtPct(hk.commission_rate, 3, false)} (min ${fmtMoney(hk.commission_min)}), platform fee ${fmtMoney(hk.platform_fee)}, statutory fees ${hk.include_statutory ? 'included' : 'excluded'}`;
  const ex = res.config?.execution || {};
  return card({
    title: 'Checks & assumptions', subtitle: `${(res.warnings || []).length} warning${(res.warnings || []).length === 1 ? '' : 's'}`,
    body: h('div', { class: 'stack-sm' }, items, kv([
      ['Costs', costLine],
      ['Fills', `${String(ex.fill || '').replace('_', ' ')}, slippage ${ex.slippage_ticks ?? 0} tick(s) + ${ex.slippage_bps ?? 0} bps`],
    ])),
  });
}
