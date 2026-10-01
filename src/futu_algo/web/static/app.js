// futu_algo web console: application shell, hash router, status strip, live event toasts.

import { h, icon, mount, applyPrefs, onPrefs, getPrefs, fmtTime, fmtDate } from './js/core.js';
import { stream, setTokenPrompt } from './js/api.js';
import { app, refreshStatus, onStatus, PageCtx, actions, envLabel, serverNow } from './js/state.js';
import { promptDialog, toast, btn } from './js/ui.js';

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
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard', page: dashboard },
  { id: 'watchlist', label: 'Watchlist', icon: 'list', page: watchlist },
  { id: 'chart', label: 'Chart', icon: 'chart', page: chart },
  { id: 'backtest', label: 'Backtest', icon: 'flask', page: backtest },
  { id: 'screener', label: 'Screener', icon: 'filter', page: screener },
  { id: 'orders', label: 'Orders', icon: 'orders', page: orders },
  { id: 'data', label: 'Data', icon: 'database', page: data },
  { id: 'settings', label: 'Settings', icon: 'settings', page: settings },
  { id: 'logs', label: 'Logs', icon: 'logs', page: logs },
];

const PHASES = {
  continuous: 'Trading', pre_open: 'Pre-open auction', lunch: 'Lunch break', closing_auction: 'Closing auction',
  after_hours: 'After hours', closed: 'Market closed', unknown: 'Unknown',
};
const LOADED_AT = Date.now();

const view = document.getElementById('view');
const titleEl = document.getElementById('page-title');
const navEl = document.getElementById('nav');
const strip = document.getElementById('status-strip');
const banners = document.getElementById('banners');
const conn = document.getElementById('conn');
const menuBtn = document.getElementById('menu-btn');
const scrim = document.getElementById('nav-scrim');

// --------------------------------------------------------------------------- navigation shell

function buildNav() {
  mount(navEl, PAGES.map((p) => h('a', { href: `#/${p.id}`, class: 'nav-link', dataset: { page: p.id } },
    icon(p.icon, 18), h('span', {}, p.label))));
  menuBtn.appendChild(icon('menu', 20));
}

function setNavOpen(open) {
  document.body.classList.toggle('nav-open', open);
  menuBtn.setAttribute('aria-expanded', String(open));
  scrim.hidden = !open;
}
menuBtn.addEventListener('click', () => setNavOpen(!document.body.classList.contains('nav-open')));
scrim.addEventListener('click', () => setNavOpen(false));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && document.body.classList.contains('nav-open')) setNavOpen(false); });

// --------------------------------------------------------------------------- router

let ctx = null;
let currentKey = '';

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  return { id: parts[0] || 'dashboard', params: parts.slice(1), query: new URLSearchParams(qs || '') };
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
  titleEl.textContent = title;
  document.title = `${title} · futu_algo`;
  view.replaceChildren();
  view.scrollTop = 0;
  window.scrollTo(0, 0);
  const root = h('div', { class: `page page-${entry.id}` });
  view.appendChild(root);
  try {
    await entry.page.mount(root, { ...r, ctx, setTitle: (t) => { titleEl.textContent = t; document.title = `${t} · futu_algo`; } });
  } catch (err) {
    console.error(err);
    if (ctx.alive) mount(root, h('div', { class: 'callout callout-error' }, icon('alert'), h('div', {}, `This page failed to render: ${err.message || err}`)));
  }
}
window.addEventListener('hashchange', () => route());

// --------------------------------------------------------------------------- status strip & banners

function pill(state) {
  const tone = { running: 'good', starting: 'warn', stopping: 'warn', stopped: 'muted', error: 'bad' }[state] || 'muted';
  return h('span', { class: `pill pill-${tone}`, title: 'Engine state' }, h('span', { class: 'dot', 'aria-hidden': 'true' }), h('span', { class: 'hide-sm' }, 'Engine '), state);
}

function renderStrip() {
  const s = app.status;
  if (!s) {
    mount(strip, app.statusError ? h('span', { class: 'pill pill-bad' }, h('span', { class: 'dot' }), 'Offline') : h('span', { class: 'pill pill-muted' }, 'Loading…'));
    return;
  }
  const e = s.engine;
  const env = envLabel(s);
  const phase = e?.phase || s.phase;
  const toClose = s.minutes_to_close;
  mount(strip,
    pill(e ? e.state : 'stopped'),
    h('span', { class: `env env-${env.toLowerCase()}`, title: `Trading environment (${s.trading?.mode})` }, env),
    e?.halted ? h('span', { class: 'pill pill-bad hide-sm', title: e.halt_reason }, 'Halted') : null,
    h('span', { class: ['phase', `phase-${phase}`, 'hide-sm'], title: toClose != null && phase === 'continuous' ? `${Math.round(toClose)} min to close` : '' },
      h('span', { class: 'dot', 'aria-hidden': 'true' }), PHASES[phase] || phase),
    h('span', { class: 'clock num', id: 'clock', title: 'Exchange time (Hong Kong)' }, clockText()),
  );
}

function clockText() {
  const now = serverNow();
  return `${fmtTime(now)} HKT`;
}
setInterval(() => {
  const c = document.getElementById('clock');
  if (c) { c.textContent = clockText(); c.title = `Exchange time: ${fmtDate(serverNow())} ${fmtTime(serverNow())} (Asia/Hong_Kong)`; }
}, 1000);

function renderBanners() {
  const s = app.status;
  const e = s?.engine;
  const items = [];
  if (app.statusError && !s) {
    items.push(h('div', { class: 'banner banner-bad', role: 'alert' }, icon('alert'), h('span', {}, `Cannot load status: ${app.statusError.detail || app.statusError.message}`)));
  } else if (app.statusError) {
    items.push(h('div', { class: 'banner banner-warn', role: 'status' }, icon('alert'), h('span', {}, 'Lost connection to the server; showing the last known state.')));
  }
  if (e?.halted) {
    items.push(h('div', { class: 'banner banner-bad', role: 'alert' },
      icon('shield'),
      h('span', { class: 'banner-text' }, h('strong', {}, 'New entries halted'), e.halt_reason ? ` — ${e.halt_reason}` : ''),
      btn('Resume', { size: 'sm', onclick: () => actions.resume() })));
  }
  if (e?.state === 'error' && e.last_error) {
    items.push(h('div', { class: 'banner banner-bad', role: 'alert' }, icon('alert'), h('span', { class: 'banner-text' }, h('strong', {}, 'Engine error'), ` — ${e.last_error}`)));
  }
  if (envLabel(s) === 'REAL') {
    items.push(h('div', { class: 'banner banner-real' }, icon('alert'), h('span', {}, h('strong', {}, 'REAL account'), ' — orders use real money.')));
  }
  mount(banners, items);
}

onStatus(() => {
  renderStrip();
  renderBanners();
  const v = document.getElementById('version');
  if (v && app.status) v.textContent = `v${app.status.version}`;
});

// --------------------------------------------------------------------------- live stream: connection + toasts

const CONN_TEXT = { live: 'Live', connecting: 'Connecting…', reconnecting: 'Reconnecting…', offline: 'Stream offline' };
function renderConn(state) {
  conn.className = `conn conn-${state}`;
  conn.querySelector('.conn-text').textContent = CONN_TEXT[state] || state;
}
stream.on('state', renderConn);

function fresh(ev) {
  const t = Date.parse(ev.time);
  return Number.isFinite(t) && t >= LOADED_AT - 3000;
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

function rerender() { route({ force: true }); }
onPrefs(() => { applyPrefs(); rerender(); });
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (getPrefs().theme === 'system') rerender(); });

// --------------------------------------------------------------------------- token

setTokenPrompt(() => promptDialog('Console token required', {
  label: 'Token', type: 'password', confirmLabel: 'Unlock',
  message: 'This server requires the console token (the value of the environment variable named by web.token_env).',
}));

// --------------------------------------------------------------------------- boot

function boot() {
  applyPrefs();
  buildNav();
  renderStrip();
  if (!window.LightweightCharts) console.warn('Lightweight Charts failed to load; charts are disabled');
  refreshStatus().then(() => {
    stream.start();
    route({ force: true });
  });
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 3000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshStatus(); });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
