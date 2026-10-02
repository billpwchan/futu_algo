// Command palette (⌘K / Ctrl+K or "/") and single-key shortcuts ("g d", "t", "?").

import { h, icon, mount, normalizeSymbol, getPrefs, setPref, isDark } from './core.js';
import { app, actions, engine, go } from './state.js';
import { modal, kbd } from './ui.js';

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const MOD = isMac ? '⌘' : 'Ctrl';

let pagesRef = [];
let dlg = null;

function symbols() {
  const e = engine();
  if (e) return e.symbols.map((s) => ({ symbol: s.symbol, name: s.name }));
  return (app.status?.trading?.symbols || []).map((s) => ({ symbol: s, name: '' }));
}

export function toggleTheme() {
  setPref('theme', isDark() ? 'light' : 'dark');
}

function buildItems() {
  const items = [];
  for (const p of pagesRef) {
    items.push({
      group: 'Go to', label: p.label, icon: p.icon, hint: p.key ? `G ${p.key.toUpperCase()}` : '',
      keywords: `${p.id} ${p.group} ${p.desc || ''}`, run: () => go(`#/${p.id}`),
    });
  }
  for (const s of symbols()) {
    items.push({ group: 'Symbols', label: s.symbol, sub: s.name, icon: 'candles', hint: 'Open chart', keywords: s.name, run: () => go(`#/chart/${encodeURIComponent(s.symbol)}`) });
  }
  const e = engine();
  const running = e?.state === 'running';
  if (running) {
    items.push({ group: 'Engine', label: 'Stop engine', icon: 'stop', run: actions.stop });
    items.push(e.halted
      ? { group: 'Engine', label: 'Resume entries', icon: 'play', run: actions.resume }
      : { group: 'Engine', label: 'Halt new entries', icon: 'pause', run: actions.halt });
    items.push({ group: 'Engine', label: 'Cancel all open orders', icon: 'x', danger: true, run: actions.cancelAll });
    items.push({ group: 'Engine', label: 'Flatten all positions', icon: 'flatten', danger: true, run: () => actions.flatten(null) });
    items.push({ group: 'Engine', label: 'Send daily summary', icon: 'bell', run: actions.summary });
  } else if (!e || e.state === 'stopped' || e.state === 'error') {
    items.push({ group: 'Engine', label: 'Start engine', icon: 'play', run: actions.start });
  }
  items.push({ group: 'Research', label: 'New backtest', icon: 'flask', run: () => go('#/backtest') });
  items.push({ group: 'Research', label: 'Run a screen', icon: 'filter', run: () => go('#/screener') });
  items.push({ group: 'Research', label: 'Fetch history into the cache', icon: 'download', run: () => go('#/data') });
  items.push({ group: 'Preferences', label: isDark() ? 'Switch to light theme' : 'Switch to dark theme', icon: isDark() ? 'sun' : 'moon', hint: 'T', run: toggleTheme });
  const updown = getPrefs().updown;
  items.push({ group: 'Preferences', label: updown === 'red-up' ? 'Use green up / red down' : 'Use red up / green down', icon: 'activity', run: () => setPref('updown', updown === 'red-up' ? 'green-up' : 'red-up') });
  items.push({ group: 'Help', label: 'Keyboard shortcuts', icon: 'keyboard', hint: '?', run: showShortcuts });
  items.push({ group: 'Help', label: 'API documentation', icon: 'external', run: () => window.open('/api/docs', '_blank', 'noopener') });
  return items;
}

/** Subsequence match with bonuses for word starts and contiguous runs; 0 = no match. */
function score(text, q) {
  const t = text.toLowerCase();
  if (!q) return 1;
  const idx = t.indexOf(q);
  if (idx === 0) return 100 - t.length * 0.01;
  if (idx > 0) return (/[\s._-]/.test(t[idx - 1]) ? 80 : 60) - idx * 0.1;
  let ti = 0; let s = 0; let run = 0;
  for (const ch of q) {
    const f = t.indexOf(ch, ti);
    if (f < 0) return 0;
    run = f === ti ? run + 1 : 0;
    s += 1 + run;
    ti = f + 1;
  }
  return 20 + s;
}

export function openPalette(initial = '') {
  if (dlg) { dlg.querySelector('input')?.focus(); return; }
  const all = buildItems();
  let shown = [];
  let active = 0;
  const input = h('input', {
    class: 'palette-input', type: 'text', placeholder: 'Search pages, symbols and actions…', value: initial,
    role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'palette-list', 'aria-autocomplete': 'list', autocomplete: 'off', spellcheck: 'false',
  });
  const list = h('div', { class: 'palette-list', id: 'palette-list', role: 'listbox', 'aria-label': 'Results' });
  dlg = h('dialog', { class: 'palette', 'aria-label': 'Command palette' },
    h('div', { class: 'palette-input-row' }, icon('search', 18), input, kbd('esc')),
    list,
    h('div', { class: 'palette-foot' },
      h('span', {}, kbd('↑'), kbd('↓'), 'navigate'), h('span', {}, kbd('↵'), 'open'), h('span', {}, kbd(MOD, 'K'), 'toggle')));

  const close = () => {
    if (!dlg) return;
    const d = dlg;
    dlg = null;
    d.close();
    d.remove();
  };
  const runItem = (it) => {
    close();
    if (it) Promise.resolve().then(it.run);
  };

  function render() {
    const q = input.value.trim().toLowerCase();
    const scored = all.map((it) => ({ it, s: Math.max(score(it.label, q), q ? score(`${it.sub || ''} ${it.keywords || ''}`, q) * 0.7 : 0) }))
      .filter((x) => x.s > 0);
    if (q) scored.sort((a, b) => b.s - a.s);
    shown = scored.map((x) => x.it);
    const sym = normalizeSymbol(input.value);
    const digits = (input.value.match(/\d/g) || []).length;
    if (digits >= 3 && /^HK\.\d{5}$/.test(sym) && !shown.some((it) => it.label === sym)) {
      shown.unshift({ group: 'Symbols', label: sym, icon: 'candles', hint: 'Open chart', run: () => go(`#/chart/${encodeURIComponent(sym)}`) });
    }
    if (q) shown = shown.slice(0, 40);
    active = Math.min(active, Math.max(0, shown.length - 1));
    if (!shown.length) { mount(list, h('div', { class: 'palette-empty' }, `No results for “${input.value.trim()}”`)); input.removeAttribute('aria-activedescendant'); return; }
    const out = [];
    let group = null;
    shown.forEach((it, i) => {
      if (!q && it.group !== group) { group = it.group; out.push(h('div', { class: 'palette-group', role: 'presentation' }, group)); }
      out.push(h('div', {
        class: ['palette-item', it.danger && 'danger'], role: 'option', id: `pi-${i}`, 'aria-selected': String(i === active),
        onclick: () => runItem(it), onmousemove: () => { if (active !== i) { active = i; paint(); } },
      },
      h('span', { class: 'pi-icon' }, icon(it.icon || 'chevronRight', 15)),
      h('span', { class: 'pi-label' }, it.label, it.sub ? h('span', { class: 'muted' }, `  ${it.sub}`) : null),
      it.hint ? h('span', { class: 'pi-hint' }, it.hint) : null));
    });
    mount(list, out);
    paint();
  }
  function paint() {
    for (const el of list.querySelectorAll('.palette-item')) {
      const on = el.id === `pi-${active}`;
      el.setAttribute('aria-selected', String(on));
      if (on) { el.scrollIntoView({ block: 'nearest' }); input.setAttribute('aria-activedescendant', el.id); }
    }
  }
  input.addEventListener('input', () => { active = 0; render(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = (active + 1) % Math.max(1, shown.length); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + shown.length) % Math.max(1, shown.length); paint(); }
    else if (e.key === 'Enter') { e.preventDefault(); runItem(shown[active]); }
  });
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); close(); });
  dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
  document.body.appendChild(dlg);
  dlg.showModal();
  render();
  input.focus();
  input.select();
}

export function showShortcuts() {
  const row = (label, ...keys) => [h('span', {}, label), kbd(...keys)];
  const body = h('div', { class: 'shortcut-list' },
    row('Command palette', MOD, 'K'),
    row('Search', '/'),
    pagesRef.filter((p) => p.key).map((p) => row(`Go to ${p.label}`, 'G', p.key.toUpperCase())),
    row('Toggle light / dark theme', 'T'),
    row('This help', '?'));
  modal({ title: 'Keyboard shortcuts', body, actions: [{ label: 'Close', value: true, primary: true }] });
}

function typing(e) {
  const t = e.target;
  return t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
}

export function initShortcuts(pages) {
  pagesRef = pages;
  let gAt = 0;
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (dlg) { dlg.close(); dlg.remove(); dlg = null; } else openPalette();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey || typing(e) || document.querySelector('dialog[open]')) return;
    if (e.key === '/') { e.preventDefault(); openPalette(); return; }
    if (e.key === '?') { e.preventDefault(); showShortcuts(); return; }
    if (e.key === 't' && Date.now() - gAt > 1200) { toggleTheme(); return; }
    if (e.key === 'g') { gAt = Date.now(); return; }
    if (Date.now() - gAt < 1200) {
      const p = pages.find((x) => x.key === e.key.toLowerCase());
      gAt = 0;
      if (p) { e.preventDefault(); go(`#/${p.id}`); }
    }
  });
}
