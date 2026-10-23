import { t as translate } from '../i18n.js';
// Backtest: parameter form (from the strategy JSON schemas), job progress, saved runs and results.

import {
  h, mount, icon, storage, fmtMoney, fmtSignedMoney, fmtPct, fmtInt, fmtPrice, fmtRatio, fmtNum, fmtDate,
  fmtDateTime, fmtWhen, signCls, paramsText, normalizeSymbol, humanize, todayHK,
} from '../core.js';
import { api, post, del, waitJob } from '../api.js';
import { app, go, strategies } from '../state.js';
import {
  card, kpi, btn, busy, dataTable, empty, errorBox, loading, badge, callout, field, select, segmented, kv,
  toast, toastError, confirmDialog, skeleton, radioCards, switchControl, downloadText, toCSV, tabs,
} from '../ui.js';
import { TIMEFRAMES } from '../common.js';
import { candleChart, equityChart, histogram } from '../charts.js';

const DRAFT_KEY = 'futu_algo.backtestDraft';
const SIZERS = [
  { value: 'equal_weight', label: translate('Equal weight'), hint: translate('Split equity equally across up to max positions') },
  { value: 'fixed_value', label: translate('Fixed value'), hint: translate('A fixed HKD amount per position') },
  { value: 'fixed_lots', label: translate('Fixed lots'), hint: translate('A fixed number of board lots per position') },
  { value: 'percent_equity', label: translate('Percent of equity'), hint: translate('A fraction of current equity per position') },
  { value: 'all_in', label: translate('All in'), hint: translate('Use all available cash (one position)') },
];
const MONTHS = [translate('Jan'), translate('Feb'), translate('Mar'), translate('Apr'), translate('May'), translate('Jun'), translate('Jul'), translate('Aug'), translate('Sep'), translate('Oct'), translate('Nov'), translate('Dec')];

export default {
  title: ({ params }) => (params[0] ? translate('Backtest report') : translate('Backtest')),
  head: ({ params }) => !params[0],
  async mount(root, { params, query, ctx, setTitle }) {
    if (params[0]) return mountResult(root, params[0], ctx, setTitle);
    return mountForm(root, query, ctx);
  },
};

// =========================================================================== form + history

async function mountForm(root, query, ctx) {
  const formHolder = h('div', {}, card({ title: translate('New backtest'), body: skeleton(8) }));
  const historyHolder = h('div', { class: 'bt-side' }, card({ title: translate('Saved runs'), body: skeleton(5) }));
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
    if (ctx.alive) mount(formHolder, card({ title: translate('New backtest'), body: errorBox(err, () => mountForm(root, query, ctx)) }));
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
  }, { label: translate('Strategy') });
  const stratInfo = h('div', { class: 'strategy-info' });
  const paramsGrid = h('div', { class: 'form-grid' });
  const paramInputs = new Map();

  function renderParams() {
    const s = byName[stratName];
    paramInputs.clear();
    mount(stratInfo, s.description ? h('p', { class: 'small text-2' }, s.description) : null, h('div', { class: 'meta-line' },
      badge(translate("warm-up {0} bars", { 0: s.warmup_bars }), 'neutral'),
      s.plots?.length ? badge(translate("plots {0}", { 0: s.plots.map((p) => p.label).join(', ') }), 'neutral') : null));
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
    if (!Object.keys(props).length) mount(paramsGrid, h('p', { class: 'muted' }, translate('This strategy has no parameters.')));
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
  const symInput = h('input', { class: 'tag-input mono', type: 'text', placeholder: symbols.length ? translate('Add…') : 'HK.00700, 9988, …', 'aria-label': translate('Add symbols'), autocomplete: 'off', spellcheck: 'false' });
  const symBox = h('div', { class: 'tag-box input', onclick: () => symInput.focus() }, symChips, symInput);
  function renderSyms() {
    mount(symChips, symbols.map((s) => h('span', { class: 'tag mono' }, s,
      h('button', { type: 'button', class: 'tag-x', 'aria-label': translate("Remove {0}", { 0: s }), onclick: (e) => { e.stopPropagation(); symbols = symbols.filter((x) => x !== s); renderSyms(); } }, icon('x', 12)))));
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
    universe.length ? btn(translate('Use trading universe'), { size: 'sm', tone: 'ghost', onclick: () => { symbols = [...universe]; renderSyms(); } }) : null,
    btn(translate('Clear'), { size: 'sm', tone: 'ghost', onclick: () => { symbols = []; renderSyms(); } }));

  // ---------------------------------------------------------------- other fields
  const tfSel = select(TIMEFRAMES.includes(base.timeframe) ? TIMEFRAMES : [base.timeframe, ...TIMEFRAMES], base.timeframe);
  const startIn = h('input', { class: 'input num', type: 'date', value: base.start || '', required: true });
  const endIn = h('input', { class: 'input num', type: 'date', value: base.end || '', max: todayHK() });
  const capitalIn = numInput(base.capital, { min: 1, step: 1000, required: true });
  const benchIn = h('input', { class: 'input mono', type: 'text', value: base.benchmark || '', placeholder: 'none (buy & hold)', spellcheck: 'false' });
  let mode = base.mode || 'portfolio';
  const modeHint = h('span', { class: 'field-hint' });
  const setModeHint = () => { modeHint.textContent = mode === 'scan' ? translate('Each symbol trades alone with the full capital; a COMPOSITE book averages them.') : translate('All symbols share one cash balance; the sizer allocates it.'); };
  const modeSeg = segmented([{ value: 'portfolio', label: translate('Portfolio') }, { value: 'scan', label: translate('Scan') }], mode, (v) => { mode = v; setModeHint(); syncSizing(); }, { label: translate('Mode') });
  setModeHint();

  const sz = base.sizing || {};
  const methodSel = select(SIZERS.map((s) => ({ value: s.value, label: s.label })), sz.method || 'equal_weight');
  const maxPosIn = numInput(sz.max_positions ?? 5, { min: 1, step: 1 });
  const valueIn = numInput(sz.value, { min: 0, step: 1000, placeholder: 'e.g. 100000' });
  const lotsIn = numInput(sz.lots ?? 1, { min: 1, step: 1 });
  const percentIn = numInput(pctIn(sz.percent), { min: 0, max: 100, step: 'any', placeholder: 'e.g. 20' });
  const methodHint = h('span', { class: 'field-hint' });
  const fValue = field(translate('Value per position (HKD)'), valueIn);
  const fLots = field(translate('Lots per position'), lotsIn);
  const fPercent = field(translate('Percent of equity (%)'), percentIn);
  const fMax = field(translate('Max positions'), maxPosIn);
  function syncSizing() {
    const m = methodSel.value;
    methodHint.textContent = mode === 'scan' ? translate('Scan mode sizes every symbol all-in; the sizer is ignored.') : SIZERS.find((s) => s.value === m)?.hint || '';
    fValue.hidden = m !== 'fixed_value';
    fLots.hidden = m !== 'fixed_lots';
    fPercent.hidden = m !== 'percent_equity';
    fMax.hidden = m === 'all_in';
  }
  methodSel.addEventListener('change', syncSizing);
  syncSizing();

  const ex = base.execution || {};
  const fillSel = select([{ value: 'next_open', label: translate('Next bar open') }, { value: 'close', label: translate('Signal bar close') }], ex.fill || 'next_open');
  const slipTicksIn = numInput(ex.slippage_ticks ?? 1, { min: 0, step: 'any' });
  const slipBpsIn = numInput(ex.slippage_bps ?? 0, { min: 0, step: 'any' });
  const freshSw = switchControl(translate('Entries need a fresh signal'), ex.entry_requires_fresh_signal !== false);
  const liqSw = switchControl(translate('Liquidate at the end'), !!ex.liquidate_at_end);
  const freshChk = freshSw.input;
  const liqChk = liqSw.input;

  const xt = base.exits || {};
  const stopIn = numInput(pctIn(xt.stop_loss), { min: 0, max: 99.99, placeholder: 'off' });
  const tpIn = numInput(pctIn(xt.take_profit), { min: 0, placeholder: 'off' });
  const trailIn = numInput(pctIn(xt.trailing_stop), { min: 0, max: 99.99, placeholder: 'off' });
  const maxBarsIn = numInput(xt.max_holding_bars, { min: 1, step: 1, placeholder: 'off' });
  const lookSw = switchControl(translate('Check the strategy for look-ahead bias'), base.check_lookahead !== false);
  const lookChk = lookSw.input;
  const rfIn = numInput(pctIn(base.risk_free_rate ?? 0), { step: 'any' });

  // ---------------------------------------------------------------- submit
  const runBtn = btn(translate('Run backtest'), { type: 'submit', tone: 'primary', iconName: 'play', size: 'lg' });
  const progress = h('div', { class: 'job-progress', hidden: true, 'aria-live': 'polite' });

  function collect() {
    const problems = [];
    if (symInput.value.trim()) { addSyms(symInput.value); symInput.value = ''; }
    if (!symbols.length) problems.push(translate('Add at least one symbol.'));
    if (!startIn.value) problems.push(translate('Start date is required.'));
    if (startIn.value && endIn.value && endIn.value <= startIn.value) problems.push(translate('End date must be after the start date.'));
    const capital = Number(capitalIn.value);
    if (!(capital > 0)) problems.push(translate('Capital must be positive.'));
    const m = methodSel.value;
    if (m === 'fixed_value' && !(Number(valueIn.value) > 0)) problems.push(translate('Fixed value sizing needs a value per position.'));
    if (m === 'percent_equity' && !(Number(percentIn.value) > 0 && Number(percentIn.value) <= 100)) problems.push(translate('Percent of equity must be between 0 and 100.'));
    for (const [key, { control, spec }] of paramInputs) {
      if (control.type === 'number' && control.value !== '' && !control.checkValidity()) problems.push(`${spec.title || key}: ${control.validationMessage}`);
    }
    const sl = pctOrNull(stopIn); const tr = pctOrNull(trailIn);
    if (sl != null && !(sl > 0 && sl < 1)) problems.push(translate('Stop loss must be between 0 and 100%.'));
    if (tr != null && !(tr > 0 && tr < 1)) problems.push(translate('Trailing stop must be between 0 and 100%.'));
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
      mount(err, h('strong', {}, translate('Please fix:')), h('ul', {}, out.problems.map((p) => h('li', {}, p))));
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
          h('div', { class: 'job-text' }, h('div', { class: 'job-title' }, job.title || translate('Backtest')), h('div', { class: 'job-msg' }, `${job.status}${job.message ? ` · ${job.message}` : ''} · ${Math.round((Date.now() - started) / 1000)}s`))));
      try {
        const job = await post('/api/backtests', { overrides: out.overrides });
        renderProgress(job);
        const final = await waitJob(job.id, { onProgress: renderProgress, isAlive: () => ctx.alive });
        if (!ctx.alive) {
          if (final.status === 'done') toast(translate("Backtest finished: {0}", { 0: final.title }), 'success');
          return;
        }
        if (final.status === 'done' && final.result?.id) {
          go(`#/backtest/${encodeURIComponent(final.result.id)}`);
        } else {
          progress.hidden = true;
          mount(err, h('strong', {}, translate('Backtest failed')), h('div', { class: 'pre-wrap' }, final.error || translate('Unknown error')));
          err.hidden = false;
        }
      } catch (ex2) {
        progress.hidden = true;
        mount(err, h('strong', {}, translate('Could not start the backtest')), h('div', { class: 'pre-wrap' }, ex2.detail || ex2.message));
        err.hidden = false;
      }
    });
  }

  let stepNo = 0;
  const section = (title, ...children) => h('fieldset', { class: 'form-section' }, h('legend', {}, h('span', { class: 'step' }, String(++stepNo)), title), ...children);
  const form = h('form', { class: 'bt-form', onsubmit: submit, novalidate: true },
    section(translate('Strategy'), stratSel, stratInfo, paramsGrid),
    section(translate('Universe'),
      field(translate('Symbols'), symBox, { hint: translate('Type or paste codes; Enter or comma adds one. 700 becomes HK.00700.') }),
      symActions,
      h('div', { class: 'form-grid' }, field(translate('Benchmark'), benchIn, { hint: translate('Index or stock; blank compares with buy & hold') }))),
    section(translate('Period & capital'),
      h('div', { class: 'form-grid' },
        field(translate('Timeframe'), tfSel),
        field(translate('Start'), startIn),
        field(translate('End'), endIn, { hint: translate('Blank means today') }),
        field(translate('Capital (HKD)'), capitalIn)),
      h('div', { class: 'field' }, h('span', { class: 'field-label' }, translate('Mode')), modeSeg, modeHint)),
    section(translate('Position sizing'),
      h('div', { class: 'form-grid' }, field(translate('Method'), methodSel), fMax, fValue, fLots, fPercent),
      methodHint),
    section(translate('Execution & exits'),
      h('div', { class: 'form-grid' },
        field(translate('Fill price'), fillSel),
        field(translate('Slippage (ticks)'), slipTicksIn),
        field(translate('Slippage (bps)'), slipBpsIn)),
      h('div', { class: 'checks' }, freshSw, liqSw),
      h('div', { class: 'form-grid' },
        field(translate('Stop loss (%)'), stopIn, { hint: translate('Below entry') }),
        field(translate('Take profit (%)'), tpIn, { hint: translate('Above entry') }),
        field(translate('Trailing stop (%)'), trailIn, { hint: translate('Below the peak') }),
        field(translate('Max holding bars'), maxBarsIn))),
    section(translate('Checks'),
      h('div', { class: 'form-grid' }, field(translate('Risk-free rate (%)'), rfIn, { hint: translate('For Sharpe and Sortino') })),
      h('div', { class: 'checks' }, lookSw)),
    err,
    h('div', { class: 'run-bar' },
      runBtn,
      btn(translate('Reset to config defaults'), { tone: 'ghost', onclick: () => { storage.set(DRAFT_KEY, null); go('#/backtest'); } }),
      progress));

  return card({
    title: fromId ? translate('Edit & re-run') : translate('New backtest'),
    subtitle: fromId ? translate("Settings loaded from run {0}", { 0: fromId }) : translate('Overrides on top of the backtest section of the config'),
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
        class: 'run-item', role: 'link', tabIndex: 0, title: translate("Open run {0}", { 0: r.id }),
        onclick: (e) => { if (!e.target.closest('button')) open(); },
        onkeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) open(); },
      },
      h('div', { class: 'run-title' }, h('span', {}, r.strategy), badge(r.timeframe, 'neutral'), r.mode === 'scan' ? badge('scan', 'accent') : null),
      h('div', { class: ['run-ret', signCls(r.total_return)] }, fmtPct(r.total_return, 1)),
      h('div', { class: 'run-meta', title: syms.join(', ') }, `${syms.slice(0, 3).join(', ')}${syms.length > 3 ? ` +${syms.length - 3}` : ''} · ${fmtWhen(r.finished_at)}`),
      h('div', { class: 'run-stats' }, h('span', {}, 'SR ', h('b', {}, fmtRatio(r.sharpe))), h('span', {}, 'DD ', h('b', {}, fmtPct(r.max_drawdown, 0))), h('span', {}, h('b', {}, fmtInt(r.trades)), ' tr')),
      h('button', {
        type: 'button', class: 'icon-btn icon-btn-danger', 'aria-label': translate("Delete run {0}", { 0: r.id }), title: translate('Delete'),
        onclick: async (e) => { e.stopPropagation(); if (await deleteRun(r.id)) loadHistory(holder, ctx); },
      }, icon('trash', 15)));
    };
    mount(holder, card({
      title: translate('Saved runs'), subtitle: rows.length ? translate('{count} reports on disk', { count: rows.length }) : null, flush: true,
      body: rows.length ? h('div', { class: 'run-list' }, rows.map(item)) : empty(translate('No backtests yet'), translate('Run one with the form; every report is saved and listed here.'), null, 'flask'),
    }));
  } catch (err) {
    if (ctx.alive) mount(holder, card({ title: translate('Saved runs'), body: errorBox(err, () => loadHistory(holder, ctx)) }));
  }
}

async function deleteRun(id) {
  const ok = await confirmDialog(translate('Delete this backtest?'), translate("The saved report {0} (result, trades and CSV files) will be removed from disk.", { 0: id }), { confirmLabel: translate('Delete'), danger: true });
  if (!ok) return false;
  try {
    await del(`/api/backtests/${encodeURIComponent(id)}`);
    toast(translate('Backtest deleted'), 'success');
    return true;
  } catch (err) {
    toastError(err, translate('Delete failed'));
    return false;
  }
}

// =========================================================================== results

async function mountResult(root, id, ctx, setTitle) {
  mount(root, loading(translate('Loading backtest…')));
  let res;
  try {
    res = await api(`/api/backtests/${encodeURIComponent(id)}`);
  } catch (err) {
    if (!ctx.alive) return;
    mount(root, h('div', { class: 'stack' },
      h('a', { href: '#/backtest', class: 'back-link' }, icon('arrowLeft', 14), translate('All backtests')),
      err.status === 404 ? card({ body: empty(translate('Backtest not found'), translate("No saved run named {0}. It may have been deleted.", { 0: id }), btn(translate('Back to backtests'), { onclick: () => go('#/backtest') }), 'flask') }) : errorBox(err, () => mountResult(root, id, ctx, setTitle))));
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
      h('a', { href: '#/backtest', class: 'back-link' }, icon('arrowLeft', 14), translate('All backtests')),
      h('h1', { class: 'result-title' }, strat.title || strat.name, h('span', { class: 'title-params mono' }, paramsText(strat.params))),
      h('div', { class: 'meta-line', style: { marginTop: '8px' } },
        badge(cfg.mode, 'accent'), badge(cfg.timeframe, 'neutral'),
        h('span', { class: 'num' }, `${fmtDate(cfg.start)} → ${cfg.end ? fmtDate(cfg.end) : fmtDate(res.finished_at)}`),
        h('span', { title: syms.join(', ') }, syms.length <= 4 ? syms.join(', ') : translate("{0} symbols", { 0: syms.length })),
        h('span', { class: 'num' }, `HK$${fmtMoney(cfg.capital, 0)}`),
        h('span', {}, translate("run {0}", { 0: fmtDateTime(res.finished_at, { seconds: false }) })))),
    h('div', { class: 'page-actions' },
      btn(translate('Edit & re-run'), { iconName: 'sliders', onclick: () => go(`#/backtest?from=${encodeURIComponent(id)}`) }),
      btn('', { tone: 'ghost-danger', iconName: 'trash', title: translate('Delete this report'), attrs: { 'aria-label': translate('Delete this report') }, onclick: async () => { if (await deleteRun(id)) go('#/backtest'); } })));

  const bookBar = h('div', { class: 'book-bar' });
  const bookBody = h('div', { class: 'stack' });
  const symbolSection = h('div');
  const warnings = warningsCard(res);
  const overviewPage = h('div', { class: 'stack' }, bookBody, symbolSection, warnings);
  const profitPage = h('div', { class: 'stack' });
  let activePage = 'overview';
  const reportContent = h('div', {}, overviewPage);
  const reportTabs = tabs([
    { value: 'overview', label: translate('Overview') },
    { value: 'profit', label: translate('Profit composition') },
  ], activePage, (value) => {
    activePage = value;
    mount(reportContent, value === 'profit' ? profitPage : overviewPage);
  });

  mount(root, header, bookBar, reportTabs, reportContent);

  let bookCtx = null;
  function selectBook(name) {
    bookName = name;
    bookCtx?.dispose();
    bookCtx = ctx.child();
    renderBook(bookBody, res, name, bookCtx);
    renderSymbols(symbolSection, res, name, bookCtx);
    renderProfitComposition(profitPage, res, name);
  }
  if (books.length > 1) {
    const opts = books.map((b) => ({ value: b, label: b }));
    mount(bookBar,
      h('span', { class: 'book-label' }, translate('Book')),
      books.length <= 8 ? segmented(opts, bookName, selectBook, { label: translate('Book'), cls: 'segmented-mono' }) : select(opts, bookName, { class: 'input input-sm', onchange: (e) => selectBook(e.target.value), 'aria-label': translate('Book') }),
      h('span', { class: 'muted book-hint' }, cfg.mode === 'scan' ? translate('Scan mode: each symbol trades alone with the full capital; COMPOSITE averages them.') : ''));
    bookBar.after(booksTable(res, (b) => { selectBook(b); bookBar.querySelector('.segmented')?.set?.(b); }));
  } else bookBar.remove();
  selectBook(bookName);
}

function booksTable(res, onPick) {
  const rows = Object.entries(res.books).map(([name, b]) => ({ name, ...b.metrics }));
  const t = dataTable({
    caption: translate('Books'),
    sort: { key: 'total_return', dir: 'desc' },
    onRowClick: (r) => onPick(r.name),
    dense: true,
    maxHeight: '300px',
    columns: [
      { key: 'name', label: translate('Book'), render: (r) => h('span', { class: 'sym' }, r.name) },
      { key: 'total_return', label: translate('Return'), num: true, render: (r) => h('span', { class: signCls(r.total_return) }, fmtPct(r.total_return)) },
      { key: 'cagr', label: 'CAGR', num: true, render: (r) => fmtPct(r.cagr), cls: 'hide-sm' },
      { key: 'sharpe', label: translate('Sharpe'), num: true, render: (r) => fmtRatio(r.sharpe) },
      { key: 'max_drawdown', label: translate('Max DD'), num: true, render: (r) => fmtPct(r.max_drawdown, 1) },
      { key: 'win_rate', label: translate('Win rate'), num: true, render: (r) => fmtPct(r.win_rate, 0, false), cls: 'hide-sm' },
      { key: 'trades', label: translate('Trades'), num: true },
      { key: 'buy_hold_return', label: translate('Buy & hold'), num: true, render: (r) => h('span', { class: signCls(r.buy_hold_return) }, fmtPct(r.buy_hold_return)), cls: 'hide-sm' },
    ],
  });
  t.update(rows);
  return card({ title: translate('Books'), subtitle: translate('Select a row to inspect that book'), body: t.el, flush: true });
}

function symbolDisplay(res, symbol) {
  const name = res.symbols?.[symbol]?.name;
  return h('span', { class: 'sym' }, symbol, name ? h('span', { class: 'sym-inline-name' }, ` ${name}`) : null);
}

function renderProfitComposition(holder, res, bookName) {
  const book = res.books[bookName] || {};
  const trades = book.trades || [];
  const fills = book.fills || [];
  const bySymbol = new Map();
  for (const trade of trades) {
    const row = bySymbol.get(trade.symbol) || {
      symbol: trade.symbol, closed_trades: 0, open_trades: 0, wins: 0,
      closed_pnl: 0, open_pnl: 0, pnl: 0, fees: 0,
    };
    if (trade.is_open) {
      row.open_trades += 1;
      row.open_pnl += trade.pnl || 0;
    } else {
      row.closed_trades += 1;
      row.closed_pnl += trade.pnl || 0;
      row.wins += trade.pnl > 0 ? 1 : 0;
    }
    row.pnl += trade.pnl || 0;
    row.fees += trade.fees || 0;
    bySymbol.set(trade.symbol, row);
  }
  const symbols = [...bySymbol.values()].sort((a, b) => b.pnl - a.pnl);
  let selectedSymbol = symbols[0]?.symbol || null;
  const detailTitle = h('span');
  const tradeTable = dataTable({
    caption: translate('Round-trip details'), emptyText: translate('No trades for this symbol'), dense: true, maxHeight: '420px',
    sort: { key: 'entry_time', dir: 'desc' },
    columns: [
      { key: 'status', label: translate('Position status'), render: (t) => t.is_open ? badge(translate('Open position'), 'info') : badge(translate('Closed position'), 'neutral') },
      { key: 'entry_time', label: translate('Entry'), render: (t) => fmtDateTime(t.entry_time) },
      { key: 'exit_time', label: translate('Exit'), render: (t) => t.is_open ? '—' : fmtDateTime(t.exit_time) },
      { key: 'quantity', label: translate('Qty'), num: true, render: (t) => fmtInt(t.is_open ? (t.open_quantity || t.quantity) : t.quantity) },
      { key: 'entry_price', label: translate('Entry px'), num: true, render: (t) => fmtPrice(t.entry_price) },
      { key: 'exit_price', label: translate('Exit / mark px'), num: true, render: (t) => fmtPrice(t.exit_price) },
      { key: 'pnl', label: translate('Net P/L'), num: true, render: (t) => h('span', { class: signCls(t.pnl) }, fmtSignedMoney(t.pnl, 0)) },
      { key: 'fees', label: translate('Fees'), num: true, render: (t) => fmtMoney(t.fees, 0) },
      { key: 'exit_reason', label: translate('Close reason'), render: (t) => t.is_open ? translate('Not closed') : translate(t.exit_reason || '—') },
    ],
  });
  const fillTable = dataTable({
    caption: translate('Entry and exit operations'), emptyText: translate('No operations for this symbol'), dense: true, maxHeight: '360px',
    sort: { key: 'time', dir: 'desc' },
    columns: [
      { key: 'time', label: translate('Time'), render: (f) => fmtDateTime(f.time) },
      { key: 'side', label: translate('Side'), render: (f) => translate(f.side) },
      { key: 'quantity', label: translate('Qty'), num: true, render: (f) => fmtInt(f.quantity) },
      { key: 'price', label: translate('Price'), num: true, render: (f) => fmtPrice(f.price) },
      { key: 'value', label: translate('Value'), num: true, render: (f) => fmtMoney(f.value, 0) },
      { key: 'fees', label: translate('Fees'), num: true, render: (f) => fmtMoney(f.fees, 0) },
      { key: 'reason', label: translate('Reason'), render: (f) => translate(f.reason || '—') },
    ],
  });
  function updateDetails() {
    mount(detailTitle, selectedSymbol ? symbolDisplay(res, selectedSymbol) : translate('Select a symbol'));
    tradeTable.update(trades.filter((t) => t.symbol === selectedSymbol));
    fillTable.update(fills.filter((f) => f.symbol === selectedSymbol));
  }
  const summaryTable = dataTable({
    caption: translate('Profit composition by symbol'), emptyText: translate('No trades in this backtest'), dense: true,
    sort: { key: 'pnl', dir: 'desc' },
    onRowClick: (row) => { selectedSymbol = row.symbol; updateDetails(); },
    rowClass: (row) => row.symbol === selectedSymbol ? 'row-selected' : null,
    rowTitle: () => translate('Select a symbol to inspect its entries and exits'),
    columns: [
      { key: 'symbol', label: translate('Symbol'), render: (r) => symbolDisplay(res, r.symbol) },
      { key: 'closed_trades', label: translate('Closed trades'), num: true },
      { key: 'open_trades', label: translate('Open positions'), num: true },
      { key: 'wins', label: translate('Wins'), num: true },
      { key: 'closed_pnl', label: translate('Closed P/L'), num: true, render: (r) => h('span', { class: signCls(r.closed_pnl) }, fmtSignedMoney(r.closed_pnl, 0)) },
      { key: 'open_pnl', label: translate('Open P/L'), num: true, render: (r) => h('span', { class: signCls(r.open_pnl) }, fmtSignedMoney(r.open_pnl, 0)) },
      { key: 'pnl', label: translate('Total net P/L'), num: true, render: (r) => h('span', { class: signCls(r.pnl) }, fmtSignedMoney(r.pnl, 0)) },
      { key: 'fees', label: translate('Fees'), num: true, render: (r) => fmtMoney(r.fees, 0) },
    ],
  });
  summaryTable.update(symbols);
  updateDetails();
  const totalPnl = symbols.reduce((sum, row) => sum + row.pnl, 0);
  const closedPnl = symbols.reduce((sum, row) => sum + row.closed_pnl, 0);
  const openPnl = symbols.reduce((sum, row) => sum + row.open_pnl, 0);
  const fees = symbols.reduce((sum, row) => sum + row.fees, 0);
  mount(holder,
    h('div', { class: 'kpis kpis-bt' },
      kpi(translate('Total net P/L'), fmtSignedMoney(totalPnl, 0), { tone: signCls(totalPnl), sub: translate('Closed and marked open positions') }),
      kpi(translate('Closed P/L'), fmtSignedMoney(closedPnl, 0), { tone: signCls(closedPnl) }),
      kpi(translate('Open P/L'), fmtSignedMoney(openPnl, 0), { tone: signCls(openPnl), sub: translate('Marked to the end of the backtest') }),
      kpi(translate('Fees'), fmtMoney(fees, 0))),
    card({ title: translate('Profit composition by symbol'), subtitle: translate('P/L is net of fees; select a symbol for its trade and operation details.'), body: summaryTable.el, flush: true }),
    card({ title: detailTitle, subtitle: translate('Round trips show entry and exit; operations list every individual fill.'), body: h('div', { class: 'stack-sm' }, tradeTable.el, fillTable.el), flush: true }));
}

function renderBook(holder, res, name, ctx) {
  const book = res.books[name];
  const m = book.metrics || {};
  const excess = m.excess_return ?? (m.benchmark_total_return != null ? m.total_return - m.benchmark_total_return : null);
  const benchName = book.benchmark_name || translate('Benchmark');
  const startEq = m.start_equity ?? res.config?.capital;

  const tear = h('div', { class: 'tear' },
    kpi(translate('Total return'), fmtPct(m.total_return), {
      cls: 'tear-hero', tone: signCls(m.total_return),
      sub: h('span', {}, translate("HK${0} final · ", { 0: fmtMoney(m.final_equity, 0) }), h('span', { class: signCls(excess) }, translate("{0} vs {1}", { 0: fmtPct(excess), 1: benchName }))),
    }),
    kpi('CAGR', fmtPct(m.cagr), { tone: signCls(m.cagr), sub: translate("{0} years", { 0: fmtNum(m.years, 2) }) }),
    kpi(translate('Sharpe'), fmtRatio(m.sharpe), { sub: `Sortino ${fmtRatio(m.sortino)}` }),
    kpi(translate('Max drawdown'), fmtPct(m.max_drawdown), { tone: 'down', sub: m.max_drawdown_days != null ? translate("{0} days to recover", { 0: fmtInt(m.max_drawdown_days) }) : translate("never recovered") }),
    kpi(translate('Win rate'), fmtPct(m.win_rate, 1, false), { sub: translate("Profit factor {0}", { 0: fmtRatio(m.profit_factor) }) }),
    kpi(translate('Trades'), fmtInt(m.trades), { sub: translate('avg {bars} bars held · {open} open', { bars: fmtNum(m.avg_bars_held, 1), open: m.open_trades || 0 }) }));

  const secondary = h('div', { class: 'kpis kpis-bt' },
    kpi(translate('Volatility'), fmtPct(m.volatility, 1, false), { sub: translate("annualised") }),
    kpi(translate('Calmar'), fmtRatio(m.calmar), { sub: translate('CAGR / max DD') }),
    kpi(translate('Expectancy'), fmtSignedMoney(m.expectancy, 0), { tone: signCls(m.expectancy), sub: translate("payoff {0}", { 0: fmtRatio(m.payoff_ratio) }) }),
    kpi(translate('Exposure'), fmtPct(m.exposure, 1, false), { sub: translate("in market {0}", { 0: fmtPct(m.time_in_market, 0, false) }) }),
    kpi(translate('Fees'), `HK$${fmtMoney(m.total_fees, 0)}`, { sub: translate("{0} of capital", { 0: fmtPct(m.fees_pct_of_capital, 2, false) }) }),
    kpi(benchName, fmtPct(m.benchmark_total_return ?? m.buy_hold_return), { tone: signCls(m.benchmark_total_return ?? m.buy_hold_return), sub: m.beta != null ? `beta ${fmtRatio(m.beta)} · alpha ${fmtPct(m.alpha)}` : translate("same period") }));

  // equity chart: the strategy as a baseline around starting equity, comparisons as lines
  const chartEl = h('div', { class: 'chart chart-lg' });
  const lines = [{ name: translate('Strategy'), data: book.equity || [] }];
  if (book.benchmark?.length) lines.push({ name: benchName, data: book.benchmark });
  if (book.buy_hold?.length && benchName !== translate('Buy & hold')) lines.push({ name: translate('Buy & hold'), data: book.buy_hold, style: 2 });
  const equityCard = card({
    title: translate('Equity curve'), subtitle: translate("{0} · shaded against starting capital · drawdown below · click the legend to toggle", { 0: book.currency || 'HKD' }),
    body: h('div', { class: 'chart-wrap' }, book.equity?.length ? chartEl : empty(translate('No equity data'))), cls: 'card-chart',
  });

  // trade return distribution
  const trades = book.trades || [];
  const closedTrades = trades.filter((t) => !t.is_open && Number.isFinite(t.return_pct));
  const rets = closedTrades.map((t) => t.return_pct).sort((a, b) => a - b);
  const median = rets.length ? rets[Math.floor(rets.length / 2)] : null;
  const mean = rets.length ? rets.reduce((a, b) => a + b, 0) / rets.length : null;
  const distEl = h('div', { class: 'viz-wrap' });
  const distCard = card({
    title: translate('Trade returns'), subtitle: rets.length ? translate("{0} closed trades · mean {1} · median {2}", { 0: fmtInt(rets.length), 1: fmtPct(mean), 2: fmtPct(median) }) : translate('No closed trades'),
    body: rets.length ? distEl : empty(translate('No closed trades'), null, null, 'activity'),
  });

  const monthlyCard = card({
    title: translate('Monthly returns'),
    actions: h('span', { class: 'heat-legend' }, translate("loss"), h('span', { class: 'heat-scale', 'aria-hidden': 'true' }), translate("gain")),
    body: monthlyTable(book.monthly || {}), flush: true,
  });

  // trades
  const tradeSyms = [...new Set(trades.map((t) => t.symbol))].sort();
  let symFilter = '';
  const tradeGroupsBody = h('tbody');
  const expandedSymbols = new Set();
  const tradeDetailColumns = [
    { key: 'entry_time', label: translate('Entry'), render: (t) => h('span', { class: 'num' }, fmtDate(t.entry_time)) },
    { key: 'exit_time', label: translate('Exit'), render: (t) => (t.is_open ? badge('open', 'info') : h('span', { class: 'num' }, fmtDate(t.exit_time))) },
    { key: 'quantity', label: translate('Qty'), num: true, render: (t) => fmtInt(t.quantity) },
    { key: 'entry_price', label: translate('Entry px'), num: true, render: (t) => fmtPrice(t.entry_price) },
    { key: 'exit_price', label: translate('Exit px'), num: true, render: (t) => fmtPrice(t.exit_price) },
    { key: 'pnl', label: translate('P/L'), num: true, render: (t) => h('span', { class: signCls(t.pnl) }, fmtSignedMoney(t.pnl, 0)) },
    { key: 'return_pct', label: translate('Return'), num: true, render: (t) => h('span', { class: signCls(t.return_pct) }, fmtPct(t.return_pct)) },
    { key: 'fees', label: translate('Fees'), num: true, render: (t) => fmtMoney(t.fees, 0), cls: 'hide-sm' },
    { key: 'bars_held', label: translate('Bars'), num: true, cls: 'hide-sm' },
    { key: 'mae_pct', label: 'MAE', num: true, render: (t) => fmtPct(t.mae_pct, 1), cls: 'hide-sm', title: translate('Maximum adverse excursion') },
    { key: 'mfe_pct', label: 'MFE', num: true, render: (t) => fmtPct(t.mfe_pct, 1), cls: 'hide-sm', title: translate('Maximum favourable excursion') },
    { key: 'exit_reason', label: translate('Close reason'), render: (t) => badge(translate(t.exit_reason), t.exit_reason === 'signal' ? 'neutral' : t.exit_reason === 'open' ? 'info' : 'warn') },
  ];
  function renderTradeGroups() {
    const visibleTrades = symFilter ? trades.filter((t) => t.symbol === symFilter) : trades;
    const grouped = new Map();
    for (const trade of visibleTrades) {
      const group = grouped.get(trade.symbol) || { symbol: trade.symbol, trades: [], closed: 0, open: 0, wins: 0, pnl: 0, fees: 0 };
      group.trades.push(trade);
      if (trade.is_open) group.open += 1;
      else { group.closed += 1; group.wins += trade.pnl > 0 ? 1 : 0; }
      group.pnl += trade.pnl || 0;
      group.fees += trade.fees || 0;
      grouped.set(trade.symbol, group);
    }
    const groups = [...grouped.values()].sort((a, b) => b.pnl - a.pnl);
    if (!groups.length) {
      mount(tradeGroupsBody, h('tr', { class: 'empty-row' }, h('td', { colspan: 8 }, translate('No trades'))));
      return;
    }
    const rendered = [];
    for (const group of groups) {
      group.trades.sort((a, b) => String(b.entry_time).localeCompare(String(a.entry_time)));
      const expanded = expandedSymbols.has(group.symbol);
      const closedRows = group.trades.filter((t) => !t.is_open).length;
      const rate = closedRows ? group.wins / closedRows : null;
      rendered.push(h('tr', {
        class: ['clickable', expanded && 'row-selected'],
        title: translate('Select a symbol to expand trade details'),
        'aria-expanded': String(expanded),
        onclick: () => { expanded ? expandedSymbols.delete(group.symbol) : expandedSymbols.add(group.symbol); renderTradeGroups(); },
      },
      h('td', {}, symbolDisplay(res, group.symbol)),
      h('td', { class: 'num' }, fmtInt(group.trades.length)),
      h('td', { class: 'num' }, fmtInt(group.closed)),
      h('td', { class: 'num' }, fmtInt(group.open)),
      h('td', { class: 'num' }, fmtPct(rate, 1, false)),
      h('td', { class: ['num', signCls(group.pnl)] }, fmtSignedMoney(group.pnl, 0)),
      h('td', { class: 'num' }, fmtMoney(group.fees, 0)),
      h('td', {}, h('button', {
        type: 'button', class: 'trade-expand',
        'aria-label': translate(expanded ? 'Collapse trade details' : 'Expand trade details'),
        onclick: (e) => { e.stopPropagation(); expanded ? expandedSymbols.delete(group.symbol) : expandedSymbols.add(group.symbol); renderTradeGroups(); },
      }, expanded ? '−' : '+'))));
      if (expanded) {
        const details = dataTable({ caption: translate('Trades'), rows: group.trades, columns: tradeDetailColumns, sort: { key: 'entry_time', dir: 'desc' }, dense: true });
        rendered.push(h('tr', { class: 'trade-detail-row' }, h('td', { colspan: 8, class: 'trade-detail-cell' }, details.el)));
      }
    }
    mount(tradeGroupsBody, rendered);
  }
  const tradeGroupsTable = h('div', { class: 'table-wrap trade-groups-wrap' }, h('table', { class: 'table table-dense' },
    h('thead', {}, h('tr', {},
      h('th', { scope: 'col' }, translate('Symbol')),
      h('th', { scope: 'col', class: 'num' }, translate('Trades')),
      h('th', { scope: 'col', class: 'num' }, translate('Closed trades')),
      h('th', { scope: 'col', class: 'num' }, translate('Open positions')),
      h('th', { scope: 'col', class: 'num' }, translate('Win rate')),
      h('th', { scope: 'col', class: 'num' }, translate('P/L')),
      h('th', { scope: 'col', class: 'num' }, translate('Fees')),
      h('th', { scope: 'col' }, translate('Details')))), tradeGroupsBody));
  function applyTradeFilter() { renderTradeGroups(); }
  renderTradeGroups();
  const wins = trades.filter((t) => !t.is_open && t.pnl > 0).length;
  const tradeCsvFields = [
    ['symbol', translate('Symbol')], ['name', translate('Name')],
    ['entry_time', translate('Entry time')], ['exit_time', translate('Exit time')],
    ['quantity', translate('Qty')], ['open_quantity', translate('Open quantity')],
    ['entry_price', translate('Entry px')], ['exit_price', translate('Exit px')],
    ['pnl', translate('P/L')], ['return_pct', translate('Return')], ['fees', translate('Fees')],
    ['bars_held', translate('Bars held')], ['days_held', translate('Days held')],
    ['exit_reason', translate('Close reason')], ['is_open', translate('Position open')],
    ['mae_pct', translate('MAE')], ['mfe_pct', translate('MFE')],
  ];
  const tradesCard = card({
    title: translate('Trades'), subtitle: translate("{0} round trips · {1} of {2} closed trades won", { 0: fmtInt(trades.length), 1: wins, 2: closedTrades.length }),
    actions: [
      tradeSyms.length > 1 ? select([{ value: '', label: translate('All symbols') }, ...tradeSyms.map((s) => ({ value: s, label: `${s}${res.symbols?.[s]?.name ? ` ${res.symbols[s].name}` : ''}` }))], '', { 'aria-label': translate('Filter trades by symbol'), class: 'input input-sm', onchange: (e) => { symFilter = e.target.value; applyTradeFilter(); } }) : null,
      btn(translate('Export CSV'), { size: 'sm', iconName: 'download', disabled: !trades.length, onclick: () => {
        const columns = tradeCsvFields.map(([, label]) => label);
        const rows = (symFilter ? trades.filter((t) => t.symbol === symFilter) : trades).map((trade) => Object.fromEntries(tradeCsvFields.map(([key, label]) => [label,
          key === 'name' ? (res.symbols?.[trade.symbol]?.name || '') : trade[key],
        ])));
        downloadText(`${res.id || 'backtest'}-${name}-trades.csv`, toCSV(columns, rows));
      } }),
    ],
    body: tradeGroupsTable, flush: true,
  });

  // drawdown periods + extra metrics
  const dds = [...(book.drawdowns || [])].sort((a, b) => (a.depth ?? 0) - (b.depth ?? 0)).slice(0, 6);
  let selectedDd = dds[0] || null;
  const ddDetail = h('div');
  const ddTable = dataTable({
    caption: translate('Worst drawdowns'), emptyText: translate('No drawdowns'), dense: true,
    onRowClick: (d) => { selectedDd = d; renderDrawdownDetail(); },
    rowClass: (d) => d === selectedDd ? 'row-selected' : null,
    rowTitle: () => translate('Show per-symbol P/L and operations for this drawdown'),
    columns: [
      { key: 'depth', label: translate('Depth'), num: true, render: (d) => h('span', { class: 'down' }, fmtPct(d.depth, 1)) },
      { key: 'start', label: translate('Peak'), render: (d) => h('span', { class: 'num' }, fmtDate(d.start)) },
      { key: 'trough', label: translate('Trough'), render: (d) => h('span', { class: 'num' }, fmtDate(d.trough)) },
      { key: 'end', label: translate('Recovered'), render: (d) => (d.recovered ? h('span', { class: 'num' }, fmtDate(d.end)) : badge('not yet', 'warn')) },
      { key: 'days', label: translate('Days'), num: true, render: (d) => fmtInt(d.days) },
    ],
  });
  ddTable.update(dds);
  const ddSymbolTable = dataTable({
    caption: translate('P/L by symbol'), emptyText: translate('No closed trades in this drawdown'), dense: true,
    columns: [
      { key: 'symbol', label: translate('Symbol'), render: (r) => symbolDisplay(res, r.symbol) },
      { key: 'closed_trades', label: translate('Closed trades'), num: true },
      { key: 'wins', label: translate('Wins'), num: true },
      { key: 'pnl', label: translate('P/L'), num: true, render: (r) => h('span', { class: signCls(r.pnl) }, fmtSignedMoney(r.pnl, 0)) },
    ],
  });
  const ddFillsTable = dataTable({
    caption: translate('Operations during drawdown'), emptyText: translate('No operations in this drawdown'), dense: true, maxHeight: '300px',
    sort: { key: 'time', dir: 'desc' },
    columns: [
      { key: 'time', label: translate('Time'), render: (f) => fmtDateTime(f.time) },
      { key: 'symbol', label: translate('Symbol'), render: (f) => symbolDisplay(res, f.symbol) },
      { key: 'side', label: translate('Side'), render: (f) => translate(f.side) },
      { key: 'quantity', label: translate('Qty'), num: true, render: (f) => fmtInt(f.quantity) },
      { key: 'price', label: translate('Price'), num: true, render: (f) => fmtPrice(f.price) },
      { key: 'value', label: translate('Value'), num: true, render: (f) => fmtMoney(f.value, 0) },
      { key: 'fees', label: translate('Fees'), num: true, render: (f) => fmtMoney(f.fees, 0), cls: 'hide-sm' },
      { key: 'reason', label: translate('Reason') },
    ],
  });
  function renderDrawdownDetail() {
    if (!selectedDd) {
      ddDetail.replaceChildren(empty(translate('Select a drawdown period to inspect its symbols and operations.')));
      return;
    }
    const start = Date.parse(selectedDd.start);
    const end = Date.parse(selectedDd.end || book.equity?.[book.equity.length - 1]?.time || selectedDd.trough);
    const intervalFills = (book.fills || []).filter((f) => {
      const time = Date.parse(f.time);
      return Number.isFinite(time) && time >= start && time <= end;
    });
    const bySymbol = new Map();
    for (const trade of book.trades || []) {
      const exit = Date.parse(trade.exit_time || '');
      if (trade.is_open || !Number.isFinite(exit) || exit < start || exit > end) continue;
      const row = bySymbol.get(trade.symbol) || { symbol: trade.symbol, closed_trades: 0, wins: 0, pnl: 0 };
      row.closed_trades += 1;
      row.wins += trade.pnl > 0 ? 1 : 0;
      row.pnl += trade.pnl || 0;
      bySymbol.set(trade.symbol, row);
    }
    ddSymbolTable.update([...bySymbol.values()].sort((a, b) => a.pnl - b.pnl));
    ddFillsTable.update(intervalFills);
    const intervalText = `${fmtDate(selectedDd.start)} – ${fmtDate(selectedDd.end || book.equity?.[book.equity.length - 1]?.time || selectedDd.trough)}`;
    mount(ddDetail, h('div', { class: 'stack-sm' },
      h('p', { class: 'muted small' }, translate('Selected drawdown: {range} · {depth}. P/L is assigned by trade exit time and includes each full round trip.', { range: intervalText, depth: fmtPct(selectedDd.depth, 1) })),
      card({ title: translate('P/L by symbol'), body: ddSymbolTable.el, flush: true }),
      card({ title: translate('Operations during drawdown'), body: ddFillsTable.el, flush: true })));
  }
  renderDrawdownDetail();
  const extra = kv([
    [translate('Start equity'), fmtMoney(m.start_equity, 0)],
    [translate('Final equity'), fmtMoney(m.final_equity, 0)],
    [translate('Realized P/L'), h('span', { class: signCls(m.realized_pnl) }, fmtSignedMoney(m.realized_pnl, 0))],
    [translate('Unrealized P/L'), h('span', { class: signCls(m.unrealized_pnl) }, fmtSignedMoney(m.unrealized_pnl, 0))],
    [translate('Turnover'), `${fmtNum(m.turnover, 2)}×`],
    [translate('Avg win / loss'), `${fmtMoney(m.avg_win, 0)} / ${fmtMoney(m.avg_loss, 0)}`],
    [translate('Largest win / loss'), `${fmtMoney(m.largest_win, 0)} / ${fmtMoney(m.largest_loss, 0)}`],
    [translate('Max consecutive W / L'), `${fmtInt(m.max_consecutive_wins)} / ${fmtInt(m.max_consecutive_losses)}`],
    ['VaR / CVaR 95%', `${fmtPct(m.var_95)} / ${fmtPct(m.cvar_95)}`],
    [translate('Best / worst bar'), `${fmtPct(m.best_bar)} / ${fmtPct(m.worst_bar)}`],
    m.information_ratio != null ? [translate('Information ratio'), fmtRatio(m.information_ratio)] : null,
    m.exit_reasons ? [translate('Exit reasons'), Object.entries(m.exit_reasons).map(([k, v]) => `${k} ${v}`).join(', ')] : null,
  ]);

  mount(holder,
    tear,
    secondary,
    equityCard,
    monthlyCard,
    h('div', { class: 'grid-2' },
      card({ title: translate('Statistics'), body: extra }),
      h('div', { class: 'stack' }, distCard, card({ title: translate('Worst drawdowns'), body: h('div', { class: 'stack-sm' }, ddTable.el, ddDetail), flush: true }))),
    tradesCard);

  if (book.equity?.length && window.LightweightCharts) {
    ctx.own(equityChart(chartEl, { lines, drawdown: book.drawdown, baseline: startEq }));
  }
  if (rets.length) ctx.own(histogram(distEl, rets));
}

function monthlyTable(monthly) {
  const years = Object.keys(monthly).sort();
  if (!years.length) return empty(translate('No monthly data'), null, null, 'clock');
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
    h('caption', { class: 'sr-only' }, translate('Monthly returns by year')),
    h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, ''), MONTHS.map((mo) => h('th', { scope: 'col', class: 'num' }, mo)), h('th', { scope: 'col', class: 'num' }, translate('Year')))),
    h('tbody', {}, years.map((y) => h('tr', {}, h('th', { scope: 'row', class: 'num' }, y), Array.from({ length: 12 }, (_, i) => cell(monthly[y][String(i + 1)])), cell(monthly[y].year, true))))));
}

function renderSymbols(holder, res, bookName, ctx) {
  const syms = Object.keys(res.symbols || {});
  if (!syms.length) { holder.replaceChildren(); return; }
  let current = res.symbols[bookName] ? bookName : syms[0];
  const chartEl = h('div', { class: 'chart chart-lg' });
  const wrap = h('div', { class: 'chart-wrap' }, chartEl);
  const sub = h('span');
  const openLink = h('a', { class: 'link-sm' }, translate('Open chart'), icon('arrowUpRight', 13));
  let chartCtx = null;
  const draw = () => {
    chartCtx?.dispose();
    chartCtx = ctx.child();
    const s = res.symbols[current];
    const book = res.books[bookName];
    const bookSyms = new Set((book?.trades || []).map((t) => t.symbol));
    sub.textContent = translate('{name} · lot {lot} · {bars} bars · {fills} fills', { name: s.name || current, lot: fmtInt(s.lot_size), bars: fmtInt(s.candles.length), fills: fmtInt(s.markers.length) }) + (bookSyms.size && !bookSyms.has(current) ? translate(' (not traded in this book)') : '');
    openLink.href = `#/chart/${encodeURIComponent(current)}?tf=${encodeURIComponent(res.config?.timeframe || 'DAY')}`;
    if (!s.candles.length || !window.LightweightCharts) { mount(wrap, empty(translate('No bars for this symbol'))); return; }
    mount(wrap, chartEl);
    chartCtx.own(candleChart(chartEl, { ...s, symbol: current, markerText: false }));
  };
  const picker = syms.length > 1
    ? (syms.length <= 6
      ? segmented(syms.map((s) => ({ value: s, label: s })), current, (v) => { current = v; draw(); }, { label: translate('Symbol'), size: 'sm', cls: 'segmented-mono' })
      : select(syms.map((s) => ({ value: s, label: s })), current, { class: 'input input-sm', 'aria-label': translate('Symbol'), onchange: (e) => { current = e.target.value; draw(); } }))
    : null;
  mount(holder, card({ title: translate('Price & fills'), subtitle: sub, actions: [picker, openLink], body: wrap, cls: 'card-chart' }));
  draw();
}

function warningsCard(res) {
  const items = [];
  const la = res.lookahead;
  if (la) items.push(la.ok ? callout('success', translate('Look-ahead check passed'), la.summary) : callout('error', translate('Look-ahead bias detected'), translate("{0}. Results are not trustworthy until the strategy is fixed.", { 0: la.summary })));
  else items.push(callout('info', translate('Look-ahead check skipped'), translate('Enable "Check the strategy for look-ahead bias" to verify the strategy.')));
  for (const w of res.warnings || []) items.push(callout('warning', null, w));
  const costs = res.costs || {};
  const hk = costs.HK || {};
  const costLine = costs.model === 'simple'
    ? translate('Simple cost model')
    : translate('HK commission {rate} (min {min}), platform fee {fee}, statutory fees {statutory}', { rate: fmtPct(hk.commission_rate, 3, false), min: fmtMoney(hk.commission_min), fee: fmtMoney(hk.platform_fee), statutory: translate(hk.include_statutory ? 'included' : 'excluded') });
  const ex = res.config?.execution || {};
  return card({
    title: translate('Checks & assumptions'), subtitle: translate('{count} warnings', { count: (res.warnings || []).length }),
    body: h('div', { class: 'stack-sm' }, items, kv([
      [translate('Costs'), costLine],
      [translate('Fills'), translate('{fill}, slippage {ticks} tick(s) + {bps} bps', { fill: translate(String(ex.fill || '').replace('_', ' ')), ticks: ex.slippage_ticks ?? 0, bps: ex.slippage_bps ?? 0 })],
    ])),
  });
}
