// Reusable UI pieces: toasts, dialogs, tables, tiles, empty states.

import { h, icon, mount, DASH } from './core.js';

// --------------------------------------------------------------------------- toasts

const TOAST_ICON = { success: 'check', error: 'alert', warning: 'alert', info: 'info' };

export function toast(message, tone = 'info', { title, timeout } = {}) {
  const root = document.getElementById('toasts');
  if (!root) return;
  const close = () => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 180);
  };
  const el = h('div', { class: `toast toast-${tone}`, role: tone === 'error' ? 'alert' : 'status' },
    h('span', { class: 'toast-icon' }, icon(TOAST_ICON[tone] || 'info', 16)),
    h('div', { class: 'toast-body' }, title ? h('div', { class: 'toast-title' }, title) : null, h('div', { class: 'toast-msg' }, message)),
    h('button', { class: 'icon-btn toast-close', type: 'button', 'aria-label': 'Dismiss', onclick: close }, icon('x', 14)),
  );
  root.appendChild(el);
  while (root.children.length > 3) root.firstElementChild.remove();
  setTimeout(close, timeout ?? (tone === 'error' ? 9000 : tone === 'warning' ? 7000 : 4500));
}

export function toastError(err, title = 'Request failed') {
  if (err?.name === 'AbortError') return;
  toast(err?.detail || err?.message || String(err), 'error', { title });
}

// --------------------------------------------------------------------------- dialogs

/**
 * Generic modal on <dialog>. actions: [{label, value, tone}] ; resolves to the chosen value,
 * or null when dismissed. `collect` runs before resolving a non-null value and may return
 * `false` to keep the dialog open (validation).
 */
export function modal({ title, body, actions = [], collect, initialFocus, wide = false }) {
  return new Promise((resolve) => {
    let done = false;
    const dlg = h('dialog', { class: ['modal', wide && 'modal-wide'], 'aria-labelledby': 'modal-title' });
    const finish = (value) => {
      if (done) return;
      if (value != null && collect) {
        const out = collect(value);
        if (out === false) return;
        if (out !== undefined) value = out;
      }
      done = true;
      dlg.close();
      dlg.remove();
      resolve(value);
    };
    const form = h('form', { method: 'dialog', class: 'modal-form', onsubmit: (e) => { e.preventDefault(); const primary = actions.find((a) => a.primary) || actions[actions.length - 1]; finish(primary ? primary.value : true); } },
      h('div', { class: 'modal-head' },
        h('h2', { id: 'modal-title', class: 'modal-title' }, title),
        h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Close', onclick: () => finish(null) }, icon('close', 16))),
      h('div', { class: 'modal-body' }, body),
      h('div', { class: 'modal-actions' }, actions.map((a) => h('button', {
        type: a.primary ? 'submit' : 'button',
        class: ['btn', a.tone ? `btn-${a.tone}` : ''],
        onclick: a.primary ? null : () => finish(a.value),
      }, a.label))),
    );
    dlg.appendChild(form);
    dlg.addEventListener('cancel', (e) => { e.preventDefault(); finish(null); });
    dlg.addEventListener('click', (e) => { if (e.target === dlg) finish(null); });
    document.body.appendChild(dlg);
    dlg.showModal();
    const focus = initialFocus ? dlg.querySelector(initialFocus) : dlg.querySelector('.modal-actions .btn:not(.btn-danger)');
    focus?.focus();
  });
}

export async function confirmDialog(title, message, { confirmLabel = 'Confirm', danger = false, detail } = {}) {
  const body = h('div', {}, h('p', { class: 'modal-text' }, message), detail ? h('p', { class: 'modal-detail' }, detail) : null);
  const v = await modal({
    title, body,
    actions: [{ label: 'Cancel', value: null }, { label: confirmLabel, value: true, tone: danger ? 'danger' : 'primary', primary: true }],
    initialFocus: '.modal-actions .btn',
  });
  return v === true;
}

export async function promptDialog(title, { label, value = '', type = 'text', placeholder = '', message, confirmLabel = 'OK', required = true } = {}) {
  const input = h('input', { class: 'input', type, value, placeholder, id: 'prompt-input', autocomplete: 'off' });
  const err = h('div', { class: 'field-error', hidden: true });
  const body = h('div', { class: 'stack-sm' },
    message ? h('p', { class: 'modal-text' }, message) : null,
    h('label', { class: 'field' }, h('span', { class: 'field-label' }, label), input),
    err);
  return modal({
    title, body, initialFocus: '#prompt-input',
    actions: [{ label: 'Cancel', value: null }, { label: confirmLabel, value: 'ok', tone: 'primary', primary: true }],
    collect: () => {
      const v = input.value.trim();
      if (required && !v) { err.textContent = 'Required'; err.hidden = false; return false; }
      return v;
    },
  });
}

// --------------------------------------------------------------------------- small pieces

export function badge(text, tone = 'neutral', attrs = {}) {
  return h('span', { class: `badge badge-${tone}`, ...attrs }, text);
}

export function spinner(label = 'Loading') {
  return h('span', { class: 'spinner', role: 'status', 'aria-label': label });
}

export function loading(text = 'Loading…') {
  return h('div', { class: 'loading' }, spinner(), h('span', {}, text));
}

export function skeleton(rows = 4) {
  return h('div', { class: 'skeleton', 'aria-hidden': 'true' }, Array.from({ length: rows }, (_, i) => h('div', { class: 'skeleton-line', style: { width: `${90 - (i * 13) % 40}%` } })));
}

export function empty(title, text, action, iconName = 'inbox') {
  return h('div', { class: 'empty' },
    iconName ? h('div', { class: 'empty-icon' }, icon(iconName, 20)) : null,
    h('div', { class: 'empty-title' }, title),
    text ? h('div', { class: 'empty-text' }, text) : null,
    action || null);
}

export function errorBox(err, retry) {
  return h('div', { class: 'callout callout-error', role: 'alert' },
    icon('alert', 16),
    h('div', { class: 'callout-body' },
      h('div', { class: 'callout-title' }, err?.status === 404 ? 'Not found' : err?.status === 0 ? 'Server unreachable' : 'Could not load'),
      h('div', {}, err?.detail || err?.message || String(err))),
    retry ? h('button', { class: 'btn btn-sm', type: 'button', onclick: retry }, 'Retry') : null);
}

export function callout(tone, title, body, iconName) {
  return h('div', { class: `callout callout-${tone}` },
    icon(iconName || (tone === 'success' ? 'check' : tone === 'info' ? 'info' : 'alert'), 16),
    h('div', { class: 'callout-body' }, title ? h('div', { class: 'callout-title' }, title) : null, body ? h('div', {}, body) : null));
}

export function card({ title, subtitle, actions, body, cls, id, flush = false }) {
  return h('section', { class: ['card', cls, flush && 'card-flush'], id },
    title || actions ? h('header', { class: 'card-head' },
      h('div', { class: 'card-titles' },
        title ? h('h2', { class: 'card-title' }, title) : null,
        subtitle ? h('div', { class: 'card-sub' }, subtitle) : null),
      actions ? h('div', { class: 'card-actions' }, actions) : null) : null,
    body == null ? null : h('div', { class: 'card-body' }, body));
}

export function kpi(label, value, { sub, tone, subTone, title, extra, cls } = {}) {
  return h('div', { class: ['kpi', cls], title },
    h('div', { class: 'kpi-label' }, label),
    h('div', { class: ['kpi-value', tone] }, value),
    sub != null ? h('div', { class: ['kpi-sub', subTone] }, sub) : null,
    extra || null);
}

/** Signed change chip: delta(+0.0123, '+1.23%') coloured by direction. */
export function delta(v, text, { arrow = true } = {}) {
  const dir = !Number.isFinite(v) || v === 0 ? '' : v > 0 ? 'up' : 'down';
  return h('span', { class: ['delta', dir] }, arrow && dir ? (dir === 'up' ? '▲' : '▼') : null, text);
}

export function kbd(...keys) {
  return h('span', { class: 'kbds' }, keys.map((k) => h('kbd', { class: 'kbd' }, k)));
}

/** 0..1 meter; tone escalates to warn/bad at the given thresholds. */
export function meter(frac, { warnAt = 0.75, badAt = 0.9, label } = {}) {
  const f = Math.max(0, Math.min(1, Number.isFinite(frac) ? frac : 0));
  const tone = f >= badAt ? 'bad' : f >= warnAt ? 'warn' : '';
  return h('span', {
    class: ['meter', tone], role: 'meter', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(f * 100)), 'aria-label': label,
  }, h('span', { class: 'meter-fill', style: { width: `${(f * 100).toFixed(1)}%` } }));
}

/** Checkbox styled as a switch. Returns the label; the input is label.input. */
export function switchControl(label, checked, { onchange, id } = {}) {
  const input = h('input', { type: 'checkbox', checked: !!checked, id, onchange });
  const el = h('label', { class: 'switch' }, input, h('span', { class: 'switch-track', 'aria-hidden': 'true' }), h('span', {}, label));
  el.input = input;
  return el;
}

/** Inline SVG sparkline. values: numbers; tone: 'up' | 'down' | '' (accent). */
export function sparkline(values, { width = 120, height = 30, tone = '', area = true, baseline } = {}) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.setAttribute('class', 'spark');
  svg.setAttribute('aria-hidden', 'true');
  const vals = (values || []).filter((v) => Number.isFinite(v));
  if (vals.length < 2) return svg;
  let min = Math.min(...vals); let max = Math.max(...vals);
  if (baseline != null) { min = Math.min(min, baseline); max = Math.max(max, baseline); }
  const span = max - min || 1;
  const pad = 3;
  const x = (i) => (i / (vals.length - 1)) * (width - pad * 2) + pad;
  const y = (v) => height - pad - ((v - min) / span) * (height - pad * 2);
  const color = tone === 'up' ? 'var(--up)' : tone === 'down' ? 'var(--down)' : 'var(--accent)';
  const pts = vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const mk = (tag, attrs) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); svg.appendChild(el); return el; };
  if (baseline != null) mk('line', { x1: pad, x2: width - pad, y1: y(baseline), y2: y(baseline), stroke: 'var(--border-2)', 'stroke-width': 1, 'stroke-dasharray': '2 3' });
  if (area) mk('path', { d: `M${pts[0]} L${pts.join(' L')} L${x(vals.length - 1).toFixed(1)},${height} L${x(0).toFixed(1)},${height} Z`, class: 'spark-area', fill: color });
  mk('polyline', { points: pts.join(' '), class: 'spark-line', stroke: color });
  mk('circle', { cx: x(vals.length - 1), cy: y(vals[vals.length - 1]), r: 2.5, class: 'spark-dot', fill: color });
  return svg;
}

/** Radio cards: options [{value, title, sub, desc}] -> element with .value getter. */
export function radioCards(name, options, value, onChange, { label } = {}) {
  const root = h('div', { class: 'rcards', role: 'radiogroup', 'aria-label': label });
  for (const o of options) {
    root.appendChild(h('label', { class: 'rcard' },
      h('input', { type: 'radio', name, value: o.value, checked: o.value === value, onchange: () => { root.current = o.value; onChange?.(o.value); } }),
      h('span', { class: 'rcard-title' }, o.title, o.sub ? h('span', { class: 'mono' }, o.sub) : null),
      o.desc ? h('span', { class: 'rcard-desc' }, o.desc) : null));
  }
  root.current = value;
  return root;
}

export function btn(label, { onclick, tone, size, iconName, type = 'button', disabled, title, attrs } = {}) {
  return h('button', {
    type, class: ['btn', tone && `btn-${tone}`, size && `btn-${size}`], onclick, disabled, title, ...attrs,
  }, iconName ? icon(iconName, size === 'sm' ? 14 : 16) : null, label ? h('span', {}, label) : null);
}

/** Runs an async action with the button disabled + spinner; returns the action result. */
export async function busy(button, fn) {
  if (button.disabled) return undefined;
  button.disabled = true;
  button.classList.add('is-busy');
  try { return await fn(); } finally {
    button.disabled = false;
    button.classList.remove('is-busy');
  }
}

/** Segmented control: options [{value, label}] */
export function segmented(options, value, onChange, { label, size, cls } = {}) {
  const root = h('div', { class: ['segmented', size && `segmented-${size}`, cls], role: 'radiogroup', 'aria-label': label });
  const render = (current) => mount(root, options.map((o) => h('button', {
    type: 'button', role: 'radio', 'aria-checked': String(o.value === current),
    class: ['seg', o.value === current && 'active'],
    onclick: () => { render(o.value); onChange(o.value); },
  }, o.label)));
  render(value);
  root.set = render;
  return root;
}

/** Toggle chips: selected is a Set; onChange(Set). */
export function chips(options, selected, onChange, { label } = {}) {
  const root = h('div', { class: 'chips', role: 'group', 'aria-label': label });
  const render = () => mount(root, options.map((o) => h('button', {
    type: 'button', class: ['chip', selected.has(o.value) && 'active', o.tone && `chip-${o.tone}`],
    'aria-pressed': String(selected.has(o.value)),
    onclick: () => {
      if (selected.has(o.value)) selected.delete(o.value); else selected.add(o.value);
      render();
      onChange(selected);
    },
  }, o.label, o.count != null ? h('span', { class: 'chip-count' }, String(o.count)) : null)));
  render();
  root.refresh = render;
  return root;
}

export function tabs(items, active, onChange) {
  const root = h('div', { class: 'tabs', role: 'tablist' });
  const render = (cur) => mount(root, items.map((it) => h('button', {
    type: 'button', role: 'tab', 'aria-selected': String(it.value === cur), class: ['tab', it.value === cur && 'active'],
    onclick: () => { render(it.value); onChange(it.value); },
  }, it.label, it.count != null ? h('span', { class: 'tab-count' }, String(it.count)) : null)));
  render(active);
  root.set = render;
  return root;
}

export function field(label, control, { hint, cls, error } = {}) {
  return h('label', { class: ['field', cls] },
    h('span', { class: 'field-label' }, label),
    control,
    hint ? h('span', { class: 'field-hint' }, hint) : null,
    error || null);
}

export function select(options, value, attrs = {}) {
  return h('select', { class: 'input', ...attrs }, options.map((o) => {
    const opt = typeof o === 'object' ? o : { value: o, label: o };
    return h('option', { value: opt.value, selected: String(opt.value) === String(value) }, opt.label);
  }));
}

export function kv(pairs) {
  return h('dl', { class: 'kv' }, pairs.filter(Boolean).map(([k, v]) => [h('dt', {}, k), h('dd', {}, v ?? DASH)]));
}

export function downloadText(filename, text, type = 'text/csv') {
  const blob = new Blob([text], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: filename, style: { display: 'none' } });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}

export function toCSV(columns, rows) {
  const esc = (v) => {
    if (v == null) return '';
    const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return '﻿' + [columns.map(esc).join(','), ...rows.map((r) => columns.map((c) => esc(r[c])).join(','))].join('\r\n');
}

// --------------------------------------------------------------------------- data table

/**
 * columns: [{key, label, num, value(row), render(row), sortable, cls, title, width}]
 * Returns {el, update(rows)}; keeps the sort across updates.
 */
export function dataTable({ columns, rows = [], emptyText = 'No rows', sort, onRowClick, rowClass, maxHeight, caption, dense = false, rowTitle }) {
  let state = sort ? { ...sort } : null;
  let data = rows;
  const thead = h('thead');
  const tbody = h('tbody');
  const table = h('table', { class: ['table', dense && 'table-dense'] }, caption ? h('caption', { class: 'sr-only' }, caption) : null, thead, tbody);
  const wrap = h('div', { class: 'table-wrap', style: maxHeight ? { maxHeight } : null }, table);

  const valueOf = (col, row) => (col.value ? col.value(row) : row[col.key]);

  function renderHead() {
    mount(thead, h('tr', {}, columns.map((col) => {
      const sortable = col.sortable !== false;
      const active = state && state.key === col.key;
      const ariaSort = active ? (state.dir === 'asc' ? 'ascending' : 'descending') : null;
      const inner = sortable
        ? h('button', {
          type: 'button', class: 'th-sort',
          onclick: () => {
            state = active ? { key: col.key, dir: state.dir === 'asc' ? 'desc' : 'asc' } : { key: col.key, dir: col.num ? 'desc' : 'asc' };
            renderHead();
            renderBody();
          },
        }, col.label, h('span', { class: 'sort-ind', 'aria-hidden': 'true' }, active ? (state.dir === 'asc' ? '▲' : '▼') : ''))
        : col.label;
      return h('th', { class: [col.num && 'num', /hide-sm/.test(col.cls || '') && 'hide-sm'], scope: 'col', 'aria-sort': ariaSort, title: col.title, style: col.width ? { width: col.width } : null }, inner);
    })));
  }

  function sorted() {
    if (!state) return data;
    const col = columns.find((c) => c.key === state.key);
    if (!col) return data;
    const dir = state.dir === 'asc' ? 1 : -1;
    return [...data].sort((a, b) => {
      const va = valueOf(col, a); const vb = valueOf(col, b);
      const na = va == null || va === '' || (typeof va === 'number' && Number.isNaN(va));
      const nb = vb == null || vb === '' || (typeof vb === 'number' && Number.isNaN(vb));
      if (na && nb) return 0;
      if (na) return 1;
      if (nb) return -1;
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
      return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir;
    });
  }

  function renderBody() {
    const list = sorted();
    if (!list.length) {
      mount(tbody, h('tr', { class: 'empty-row' }, h('td', { colspan: columns.length }, emptyText)));
      return;
    }
    mount(tbody, list.map((row) => {
      const tr = h('tr', { class: [rowClass?.(row), onRowClick && 'clickable'], title: rowTitle?.(row) },
        columns.map((col) => {
          let content = col.render ? col.render(row) : valueOf(col, row);
          if (content == null || content === '') content = DASH;
          return h('td', { class: [col.num && 'num', col.cls] }, content);
        }));
      if (onRowClick) {
        tr.tabIndex = 0;
        tr.addEventListener('click', (e) => { if (!e.target.closest('button, a, input, select')) onRowClick(row, e); });
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target === tr) onRowClick(row, e); });
      }
      return tr;
    }));
  }

  renderHead();
  renderBody();
  return {
    el: wrap,
    update(next) { data = next || []; renderBody(); },
    get rows() { return sorted(); },
  };
}
