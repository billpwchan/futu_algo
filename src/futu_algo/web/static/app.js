// futu_algo web console: application shell, hash router, market session ribbon, engine card,
// live event toasts, command palette and shortcuts.

import { h, icon, mount, applyPrefs, onPrefs, getPrefs, isDark, fmtTime, fmtDate } from './js/core.js';
import { stream, setTokenPrompt } from './js/api.js';
import { app, refreshStatus, onStatus, PageCtx, actions, envLabel, serverNow } from './js/state.js';
import { promptDialog, toast, btn, busy, kbd } from './js/ui.js';
import { initShortcuts, openPalette, toggleTheme, MOD } from './js/palette.js';

import dashboard from './js/pages/dashboard.js';
import watchlist from './js/pages/watchlist.js';
import chart from './js/pages/chart.js';
import backtest from './js/pages/backtest.js';
import screener from './js/pages/screener.js';
import orders from './js/pages/orders.js';
import data from './js/pages/data.js';
import settings from './js/pages/settings.js';
import logs from './js/pages/logs.js';

const PAGES = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard', group: 'Trade', key: 'd', page: dashboard, desc: 'Account, positions and the live engine' },
  { id: 'watchlist', label: 'Watchlist', icon: 'list', group: 'Trade', key: 'w', page: watchlist, desc: 'Every symbol the engine trades, its strategy and its last decision' },
  { id: 'chart', label: 'Chart', icon: 'candles', group: 'Trade', key: 'c', page: chart, desc: 'Candles, strategy indicators and fills' },
  { id: 'orders', label: 'Orders', icon: 'orders', group: 'Trade', key: 'o', page: orders, desc: 'The order blotter, fills and execution intents' },
  { id: 'backtest', label: 'Backtest', icon: 'flask', group: 'Research', key: 'b', page: backtest, desc: 'Board lots, HK statutory costs and tick-table slippage, next-open fills' },
  { id: 'screener', label: 'Screener', icon: 'filter', group: 'Research', key: 's', page: screener, desc: 'Filters run on Futu servers across the whole HK market' },
  { id: 'data', label: 'Data', icon: 'database', group: 'Research', key: 'a', page: data, desc: 'The local K-line cache and your Futu history quota' },
  { id: 'settings', label: 'Settings', icon: 'settings', group: 'System', key: ',', page: settings, desc: 'Configuration, notifications and display preferences' },
  { id: 'logs', label: 'Logs', icon: 'logs', group: 'System', key: 'l', page: logs, desc: 'Engine events, persisted and streamed live' },
];

const PHASES = {
  continuous: 'Trading', pre_open: 'Pre-open auction', lunch: 'Lunch break', closing_auction: 'Closing auction',
  after_hours: 'After hours', closed: 'Market closed', unknown: 'Unknown',
};
const PHASE_TONE = { continuous: 'good', pre_open: 'warn', closing_auction: 'warn', lunch: 'info', after_hours: '', closed: '', unknown: '' };
// Minutes after 09:00 HKT: pre-open auction, morning, lunch, afternoon, closing auction.
const SESSIONS = [
  { from: 0, to: 30, cls: 'auction', label: 'Pre-open 09:00–09:30' },
  { from: 30, to: 180, cls: '', label: 'Morning 09:30–12:00' },
  { from: 180, to: 240, cls: 'lunch', label: 'Lunch 12:00–13:00' },
  { from: 240, to: 420, cls: '', label: 'Afternoon 13:00–16:00' },
  { from: 420, to: 430, cls: 'auction', label: 'Closing auction 16:00–16:10' },
];
let loadedAt = Date.now(); // exchange time at boot; replaced by the server clock once known

const view = document.getElementById('view');
const navEl = document.getElementById('nav');
const crumbs = document.getElementById('crumbs');
const topRight = document.getElementById('topbar-right');
const banners = document.getElementById('banners');
const conn = document.getElementById('conn');
const engineCard = document.getElementById('engine-card');
const menuBtn = document.getElementById('menu-btn');
const scrim = document.getElementById('nav-scrim');
const sideSearch = document.getElementById('side-search');

// --------------------------------------------------------------------------- navigation shell

function buildNav() {
  const out = [];
  let group = null;
  for (const p of PAGES) {
    if (p.group !== group) { group = p.group; out.push(h('div', { class: 'nav-group', role: 'presentation' }, group)); }
    out.push(h('a', { href: `#/${p.id}`, class: 'nav-link', dataset: { page: p.id }, title: `${p.label} (G then ${p.key.toUpperCase()})` },
      icon(p.icon, 18), h('span', {}, p.label), h('span', { class: 'nav-key' }, kbd('G', p.key.toUpperCase()))));
  }
  mount(navEl, out);
  menuBtn.appendChild(icon('menu', 20));
  sideSearch.prepend(icon('search', 15));
  sideSearch.appendChild(kbd(MOD, 'K'));
  sideSearch.addEventListener('click', () => { setNavOpen(false); openPalette(); });
}

function setNavOpen(open) {
  document.body.classList.toggle('nav-open', open);
  menuBtn.setAttribute('aria-expanded', String(open));
  scrim.hidden = !open;
}
menuBtn.addEventListener('click', () => setNavOpen(!document.body.classList.contains('nav-open')));
scrim.addEventListener('click', () => setNavOpen(false));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && document.body.classList.contains('nav-open')) setNavOpen(false); });

// --------------------------------------------------------------------------- top bar

const sessionEl = h('div', { class: 'session' });
const clockEl = h('span', { class: 'clock', title: 'Exchange time (Asia/Hong_Kong)' });
const enginePill = h('span', { class: 'engine-pill-wrap' });
const themeBtn = h('button', { class: 'icon-btn', type: 'button', onclick: () => toggleTheme() });
const searchTop = h('button', { class: 'icon-btn search-top', type: 'button', 'aria-label': 'Search', title: `Search (${MOD}+K)`, onclick: () => openPalette() }, icon('search', 17));

function renderThemeBtn() {
  const dark = isDark();
  themeBtn.replaceChildren(icon(dark ? 'sun' : 'moon', 17));
  themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  themeBtn.title = `${dark ? 'Light' : 'Dark'} theme (T)`;
}

function buildTopbar() {
  mount(topRight, sessionEl, clockEl, enginePill, searchTop, themeBtn);
  renderThemeBtn();
}

function hkMinutes(d) {
  const [hh, mm, ss] = fmtTime(d).split(':').map(Number);
  return hh * 60 + mm + (ss || 0) / 60;
}

function fmtDuration(min) {
  const m = Math.max(0, Math.round(min));
  return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m` : `${m}m`;
}

function renderSession() {
  const s = app.status;
  const phase = s?.engine?.phase || s?.phase || 'unknown';
  const now = serverNow();
  const t = hkMinutes(now) - 9 * 60;
  const open = phase !== 'closed' && phase !== 'unknown';
  let sub = '';
  if (phase === 'continuous' && s?.minutes_to_close != null) sub = `Closes in ${fmtDuration(s.minutes_to_close)}`;
  else if (phase === 'lunch') sub = `Resumes in ${fmtDuration(240 - t)}`;
  else if (phase === 'pre_open') sub = `Opens in ${fmtDuration(30 - t)}`;
  else if (phase === 'closing_auction') sub = 'Auction until 16:10';
  else if (phase === 'after_hours') sub = 'Session over';
  const total = 430;
  mount(sessionEl,
    h('div', { class: 'session-text' },
      h('span', { class: 'session-phase' }, h('span', { class: ['dot', `dot-${PHASE_TONE[phase] || ''}`, phase === 'continuous' && 'dot-live'] }), PHASES[phase] || phase),
      sub ? h('span', { class: 'session-sub' }, sub) : null),
    h('div', { class: 'ribbon', role: 'img', 'aria-label': `HK session timeline, ${PHASES[phase] || phase}` },
      h('div', { class: 'ribbon-ticks', 'aria-hidden': 'true' },
        h('span', { style: { left: '0%' } }, '09:00'), h('span', { class: 'mid', style: { left: `${(180 / total) * 100}%` } }, '12:00'), h('span', { class: 'end', style: { left: '100%' } }, '16:10')),
      h('div', { class: 'ribbon-track' }, SESSIONS.map((seg) => {
        const frac = !open ? 0 : Math.max(0, Math.min(1, (t - seg.from) / (seg.to - seg.from)));
        return h('div', { class: ['ribbon-seg', seg.cls], style: { flex: `${seg.to - seg.from} 1 0` }, title: seg.label },
          h('i', { style: { width: `${(frac * 100).toFixed(1)}%` } }));
      })),
      open && t >= 0 && t <= total ? h('span', { class: 'ribbon-now', style: { left: `${((t / total) * 100).toFixed(2)}%` } }) : null));
}

function renderClock() {
  const now = serverNow();
  mount(clockEl, fmtTime(now), h('small', {}, 'HKT'));
  clockEl.title = `Exchange time: ${fmtDate(now)} ${fmtTime(now)} (Asia/Hong_Kong)`;
}
setInterval(() => { renderClock(); if (new Date().getSeconds() % 10 === 0) renderSession(); }, 1000);

const ENGINE_TONE = { running: 'good', starting: 'warn', stopping: 'warn', stopped: '', error: 'bad' };
function uptime(iso) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  return `up ${fmtDuration((serverNow().getTime() - t) / 60000)}`;
}

function renderEngine() {
  const s = app.status;
  const e = s?.engine;
  const state = e ? e.state : s ? 'stopped' : app.statusError ? 'offline' : 'loading';
  const env = envLabel(s);
  const tone = e?.halted ? 'warn' : ENGINE_TONE[state] ?? '';
  const label = e?.halted ? 'Entries halted' : state === 'offline' ? 'Server offline' : `Engine ${state}`;
  const syms = e ? e.symbols.length : s?.trading?.symbols?.length ?? 0;
  const tf = e?.timeframe || s?.trading?.timeframe || '';
  const canStart = s && (!e || e.state === 'stopped' || e.state === 'error');
  mount(engineCard,
    h('div', { class: 'engine-card-top' },
      h('span', { class: ['dot', `dot-${tone}`, state === 'running' && !e?.halted && 'dot-live'], 'aria-hidden': 'true' }),
      h('span', { class: 'engine-card-title' }, label),
      h('span', { class: 'engine-card-up' }, e?.state === 'running' ? uptime(e.started_at) : '')),
    h('div', { class: 'engine-card-meta' },
      env !== '—' ? h('span', { class: ['env', `env-${env.toLowerCase()}`], title: `Trading environment (${s?.trading?.mode})` }, env) : null,
      h('span', {}, `${syms} symbols · ${tf}`)),
    canStart ? btn('Start engine', { tone: 'primary', size: 'sm', iconName: 'play', onclick: (ev) => busy(ev.currentTarget, actions.start) }) : null);
  mount(enginePill, h('span', { class: ['pill', `pill-${tone || 'muted'}`, 'engine-pill'], title: label },
    h('span', { class: 'dot', 'aria-hidden': 'true' }), env !== '—' ? env : state));
}

function renderBanners() {
  const s = app.status;
  const e = s?.engine;
  const items = [];
  if (app.statusError && !s) {
    items.push(h('div', { class: 'banner banner-bad', role: 'alert' }, icon('alert'), h('span', { class: 'banner-text' }, `Cannot load status: ${app.statusError.detail || app.statusError.message}`)));
  } else if (app.statusError) {
    items.push(h('div', { class: 'banner banner-warn', role: 'status' }, icon('alert'), h('span', { class: 'banner-text' }, 'Lost connection to the server; showing the last known state.')));
  }
  if (e?.halted) {
    items.push(h('div', { class: 'banner banner-warn', role: 'alert' },
      icon('shield'),
      h('span', { class: 'banner-text' }, h('strong', {}, 'New entries halted'), e.halt_reason ? ` — ${e.halt_reason}` : ''),
      btn('Resume entries', { size: 'sm', onclick: (ev) => busy(ev.currentTarget, actions.resume) })));
  }
  if (e?.state === 'error' && e.last_error) {
    items.push(h('div', { class: 'banner banner-bad', role: 'alert' }, icon('alert'), h('span', { class: 'banner-text' }, h('strong', {}, 'Engine error'), ` — ${e.last_error}`)));
  }
  if (envLabel(s) === 'REAL') {
    items.push(h('div', { class: 'banner banner-real' }, icon('alert'), h('span', { class: 'banner-text' }, h('strong', {}, 'REAL account'), ' — orders use real money.')));
  }
  mount(banners, items);
}

onStatus(() => {
  renderSession();
  renderEngine();
  renderBanners();
  const v = document.getElementById('version');
  if (v && app.status) v.textContent = `v${app.status.version}`;
});

// --------------------------------------------------------------------------- router

let ctx = null;
let currentKey = '';

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  return { id: parts[0] || 'dashboard', params: parts.slice(1), query: new URLSearchParams(qs || '') };
}

function setCrumbs(entry, title) {
  mount(crumbs, h('span', { class: 'hide-sm' }, entry.group), h('span', { class: 'sep hide-sm', 'aria-hidden': 'true' }, '/'), h('strong', {}, title));
  document.title = `${title} · futu_algo`;
}

async function route({ force = false } = {}) {
  const r = parseHash();
  const entry = PAGES.find((p) => p.id === r.id);
  if (!entry) { location.replace('#/dashboard'); return; }
  const key = location.hash;
  if (!force && key === currentKey && ctx) return;
  currentKey = key;
  ctx?.dispose();
  ctx = new PageCtx();
  setNavOpen(false);
  for (const a of navEl.querySelectorAll('.nav-link')) {
    const on = a.dataset.page === entry.id;
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  const title = entry.page.title?.(r) || entry.label;
  setCrumbs(entry, title);
  view.replaceChildren();
  window.scrollTo(0, 0);

  const titleEl = h('h1', { class: 'page-title', id: 'page-title' }, title);
  const descEl = h('p', { class: 'page-desc' }, entry.desc);
  const actionsEl = h('div', { class: 'page-actions' });
  const showHead = entry.page.head?.(r) !== false;
  const head = h('header', { class: 'page-head', hidden: !showHead }, h('div', { class: 'page-head-text' }, titleEl, descEl), actionsEl);
  const root = h('div', { class: `page page-${entry.id}` }, head);
  view.appendChild(root);
  const body = h('div', { class: 'stack page-body' });
  root.appendChild(body);
  const setTitle = (t) => { titleEl.textContent = t; setCrumbs(entry, t); };
  const setDesc = (d) => { if (typeof d === 'string') descEl.textContent = d; else mount(descEl, d); };
  try {
    await entry.page.mount(body, { ...r, ctx, setTitle, setDesc, actions: actionsEl });
  } catch (err) {
    console.error(err);
    if (ctx.alive) mount(body, h('div', { class: 'callout callout-error' }, icon('alert'), h('div', {}, `This page failed to render: ${err.message || err}`)));
  }
}
window.addEventListener('hashchange', () => route());

// --------------------------------------------------------------------------- live stream: connection + toasts

const CONN_TEXT = { live: 'Live', connecting: 'Connecting…', reconnecting: 'Reconnecting…', offline: 'Stream offline' };
function renderConn(state) {
  conn.className = `conn conn-${state}`;
  conn.querySelector('.conn-text').textContent = CONN_TEXT[state] || state;
}
stream.on('state', renderConn);

function fresh(ev) {
  const t = Date.parse(ev.time);
  return Number.isFinite(t) && t >= loadedAt - 3000;
}
let statusSoon = null;
function statusRefreshSoon() {
  clearTimeout(statusSoon);
  statusSoon = setTimeout(refreshStatus, 250);
}
stream.on('event', (ev) => {
  if (['engine', 'risk', 'account', 'fill', 'error'].includes(ev.kind)) statusRefreshSoon();
  if (!fresh(ev)) return;
  switch (ev.kind) {
    case 'fill': toast(ev.message, 'success', { title: 'Fill' }); break;
    case 'rejection': toast(ev.message, 'warning', { title: 'Order rejected' }); break;
    case 'error': toast(ev.message, 'error', { title: 'Error' }); break;
    case 'risk': if (ev.level !== 'info') toast(ev.message, 'warning', { title: 'Risk' }); break;
    case 'engine': if (ev.level === 'error' || ev.level === 'warning') toast(ev.message, ev.level === 'error' ? 'error' : 'warning', { title: 'Engine' }); break;
    default: break;
  }
});

// --------------------------------------------------------------------------- theme & preferences

function rerender() { renderThemeBtn(); route({ force: true }); }
onPrefs(() => { applyPrefs(); rerender(); });
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (getPrefs().theme === 'system') rerender(); });

// --------------------------------------------------------------------------- token

setTokenPrompt(() => promptDialog('Console token required', {
  label: 'Token', type: 'password', confirmLabel: 'Unlock',
  message: 'This server requires the console token (the value of the environment variable named by web.token_env).',
}));

// --------------------------------------------------------------------------- boot

async function fontsReady() {
  // Charts draw text on canvas, which does not re-render when a web font arrives late.
  if (!document.fonts?.load) return;
  const timeout = new Promise((r) => setTimeout(r, 1500));
  await Promise.race([Promise.all([document.fonts.load('500 12px Geist'), document.fonts.load('500 12px "Geist Mono"')]).catch(() => {}), timeout]);
}

function boot() {
  applyPrefs();
  buildNav();
  buildTopbar();
  initShortcuts(PAGES);
  renderEngine();
  renderClock();
  if (!window.LightweightCharts) console.warn('Lightweight Charts failed to load; charts are disabled');
  Promise.all([refreshStatus(), fontsReady()]).then(() => {
    // Event times are exchange (engine) time, which differs from this browser's clock in demo mode.
    const now = Date.parse(app.status?.now);
    if (Number.isFinite(now)) loadedAt = now;
    stream.start();
    route({ force: true });
  });
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 3000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshStatus(); });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
