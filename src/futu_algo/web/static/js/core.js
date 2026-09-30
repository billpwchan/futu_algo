// Core helpers: DOM builder, icons, formatters, storage, preferences and a tiny event hub.
// Everything that renders data goes through textContent / DOM building; never innerHTML.

export const HK_TZ = 'Asia/Hong_Kong';
export const HK_OFFSET_S = 8 * 3600; // Hong Kong has no DST

// --------------------------------------------------------------------------- DOM

const PROPS = new Set(['value', 'checked', 'disabled', 'selected', 'hidden', 'indeterminate', 'multiple', 'readOnly', 'required', 'open']);

function isProps(x) {
  return x != null && typeof x === 'object' && !(x instanceof Node) && !Array.isArray(x);
}

function append(el, child) {
  if (child == null || child === false || child === true) return;
  if (Array.isArray(child)) { for (const c of child) append(el, c); return; }
  el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
}

/** h('div', {class: 'x', onclick: fn}, 'text', child, [more]) */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (isProps(props)) applyProps(el, props);
  else children.unshift(props);
  append(el, children);
  return el;
}

function applyProps(el, props) {
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false && !PROPS.has(k)) continue;
    if (k === 'class') el.className = Array.isArray(v) ? v.filter(Boolean).join(' ') : v;
    else if (k === 'style' && typeof v === 'object') {
      for (const [sk, sv] of Object.entries(v)) {
        if (sv == null) continue;
        if (sk.startsWith('--')) el.style.setProperty(sk, sv); else el.style[sk] = sv;
      }
    } else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (PROPS.has(k)) el[k] = v;
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
}

export function mount(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);

// --------------------------------------------------------------------------- icons (inline SVG, stroke based)

const ICONS = {
  dashboard: 'M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  chart: 'M3 3v18h18M7 15l4-4 3 3 5-6',
  flask: 'M9 3h6M10 3v6L4.5 18.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3M7 15h10',
  filter: 'M3 4h18l-7 9v6l-4 2v-8z',
  orders: 'M4 4h16v16H4zM4 9h16M9 9v11',
  database: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  logs: 'M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h5',
  menu: 'M3 6h18M3 12h18M3 18h18',
  close: 'M18 6 6 18M6 6l12 12',
  play: 'M6 4l14 8-14 8z',
  stop: 'M6 6h12v12H6z',
  pause: 'M7 5h3v14H7zM14 5h3v14h-3z',
  x: 'M18 6 6 18M6 6l12 12',
  refresh: 'M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6',
  download: 'M12 3v12M7 10l5 5 5-5M5 21h14',
  trash: 'M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14',
  alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  check: 'M20 6 9 17l-5-5',
  info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01',
  arrowLeft: 'M19 12H5M12 19l-7-7 7-7',
  bell: 'M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0',
  flatten: 'M4 12h16M4 6h16M4 18h10',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3',
};

export function icon(name, size = 16) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.classList.add('icon');
  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', ICONS[name] || ICONS.info);
  svg.appendChild(path);
  return svg;
}

// --------------------------------------------------------------------------- storage (never throws)

export const storage = {
  get(key, fallback = null, area = 'local') {
    try {
      const s = area === 'session' ? window.sessionStorage : window.localStorage;
      const v = s.getItem(key);
      return v == null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value, area = 'local') {
    try {
      const s = area === 'session' ? window.sessionStorage : window.localStorage;
      if (value == null) s.removeItem(key); else s.setItem(key, JSON.stringify(value));
    } catch { /* storage unavailable: preference lives for this page only */ }
  },
};

// --------------------------------------------------------------------------- event hub

export function createHub() {
  const map = new Map();
  return {
    on(kind, fn) {
      if (!map.has(kind)) map.set(kind, new Set());
      map.get(kind).add(fn);
      return () => map.get(kind)?.delete(fn);
    },
    emit(kind, payload) {
      for (const fn of [...(map.get(kind) || [])]) {
        try { fn(payload); } catch (err) { console.error(err); }
      }
      if (kind !== '*') for (const fn of [...(map.get('*') || [])]) {
        try { fn(payload, kind); } catch (err) { console.error(err); }
      }
    },
  };
}

// --------------------------------------------------------------------------- preferences

const PREF_KEY = 'futu_algo.prefs';
const prefHub = createHub();
let prefs = { theme: 'system', updown: 'green-up', ...storage.get(PREF_KEY, {}) };

export function getPrefs() { return { ...prefs }; }
export function setPref(key, value) {
  prefs = { ...prefs, [key]: value };
  storage.set(PREF_KEY, prefs);
  applyPrefs();
  prefHub.emit('change', prefs);
}
export function onPrefs(fn) { return prefHub.on('change', fn); }
export function applyPrefs() {
  const root = document.documentElement;
  if (prefs.theme === 'light' || prefs.theme === 'dark') root.dataset.theme = prefs.theme;
  else delete root.dataset.theme;
  root.dataset.updown = prefs.updown === 'red-up' ? 'red-up' : 'green-up';
}
export function isDark() {
  if (prefs.theme === 'dark') return true;
  if (prefs.theme === 'light') return false;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

// --------------------------------------------------------------------------- formatting

const nfCache = new Map();
function nf(min, max, extra = {}) {
  const key = `${min}|${max}|${JSON.stringify(extra)}`;
  if (!nfCache.has(key)) nfCache.set(key, new Intl.NumberFormat('en-US', { minimumFractionDigits: min, maximumFractionDigits: max, ...extra }));
  return nfCache.get(key);
}
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
export const DASH = '—';

export function fmtMoney(v, dp = 2) { return isNum(v) ? nf(dp, dp).format(v) : DASH; }
export function fmtSignedMoney(v, dp = 2) { return isNum(v) ? (v > 0 ? '+' : v < 0 ? '−' : '') + nf(dp, dp).format(Math.abs(v)) : DASH; }
export function fmtInt(v) { return isNum(v) ? nf(0, 0).format(v) : DASH; }
export function fmtNum(v, dp = 2) { return isNum(v) ? nf(dp, dp).format(v) : DASH; }
/** Up to `max` decimals, at least `min`: HK prices carry 2-3 decimals. */
export function fmtPrice(v, min = 2, max = 3) { return isNum(v) ? nf(min, max).format(v) : DASH; }
/** fraction -> signed percent (0.0123 -> +1.23%). */
export function fmtPct(v, dp = 2, signed = true) {
  if (!isNum(v)) return DASH;
  const p = v * 100;
  const s = nf(dp, dp).format(Math.abs(p));
  return (p > 0 && signed ? '+' : p < 0 ? '−' : '') + s + '%';
}
/** value already in percent units (screener change_pct). */
export function fmtPctPts(v, dp = 2) { return isNum(v) ? fmtPct(v / 100, dp) : DASH; }
export function fmtCompact(v, dp = 2) {
  if (!isNum(v)) return DASH;
  return nf(0, dp, { notation: 'compact', compactDisplay: 'short' }).format(v);
}
export function fmtRatio(v, dp = 2) { return isNum(v) ? nf(dp, dp).format(v) : DASH; }
export function signCls(v) { return !isNum(v) || v === 0 ? '' : v > 0 ? 'up' : 'down'; }

const dtf = new Intl.DateTimeFormat('en-GB', {
  timeZone: HK_TZ, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
const utcDtf = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});
function partsOf(fmt, d) {
  const o = {};
  for (const p of fmt.formatToParts(d)) o[p.type] = p.value;
  return o;
}
function toDate(v) {
  if (v == null || v === '') return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}
/** ISO (any offset) -> 'YYYY-MM-DD HH:mm:ss' in Hong Kong time. */
export function fmtDateTime(v, { seconds = true } = {}) {
  const d = toDate(v);
  if (!d) return DASH;
  const p = partsOf(dtf, d);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}${seconds ? ':' + p.second : ''}`;
}
export function fmtTime(v, { seconds = true } = {}) {
  const d = toDate(v);
  if (!d) return DASH;
  const p = partsOf(dtf, d);
  return `${p.hour}:${p.minute}${seconds ? ':' + p.second : ''}`;
}
export function fmtDate(v) {
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  const d = toDate(v);
  if (!d) return DASH;
  const p = partsOf(dtf, d);
  return `${p.year}-${p.month}-${p.day}`;
}
/** Smart: time only when the timestamp is today (HK), else date + time. */
export function fmtWhen(v) {
  const d = toDate(v);
  if (!d) return DASH;
  return fmtDate(d) === fmtDate(new Date()) ? fmtTime(d) : fmtDateTime(d, { seconds: false });
}
/** Chart epoch seconds (exchange wall time encoded as UTC) -> text. */
export function fmtChartTime(sec, withTime = true) {
  const p = partsOf(utcDtf, new Date(sec * 1000));
  const date = `${p.year}-${p.month}-${p.day}`;
  return withTime && (p.hour !== '00' || p.minute !== '00') ? `${date} ${p.hour}:${p.minute}` : date;
}
/** ISO timestamp -> chart epoch seconds (HK wall time as UTC). */
export function hkEpoch(v) {
  const d = toDate(v);
  return d ? Math.floor(d.getTime() / 1000) + HK_OFFSET_S : null;
}
export function todayHK() { return fmtDate(new Date()); }
export function relTime(v) {
  const d = toDate(v);
  if (!d) return DASH;
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (Math.abs(s) < 60) return `${s}s ago`;
  if (Math.abs(s) < 3600) return `${Math.round(s / 60)}m ago`;
  if (Math.abs(s) < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
export function humanize(key) {
  return String(key).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()).replace(/\bPct\b/, '%').replace(/\bPe\b/, 'PE').replace(/\bTtm\b/, 'TTM');
}
export function paramsText(params) {
  if (!params || typeof params !== 'object') return '';
  return Object.entries(params).map(([k, v]) => `${k}=${v}`).join(', ');
}
export function debounce(fn, ms) {
  let t = null;
  const d = (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  d.cancel = () => clearTimeout(t);
  return d;
}
/** Leading+trailing throttle. */
export function throttle(fn, ms) {
  let last = 0; let t = null;
  return (...args) => {
    const now = Date.now();
    const wait = ms - (now - last);
    if (wait <= 0) { last = now; fn(...args); }
    else if (!t) t = setTimeout(() => { t = null; last = Date.now(); fn(...args); }, wait);
  };
}
export function parseJSONMaybe(v) {
  if (typeof v !== 'string') return v;
  try { return JSON.parse(v); } catch { return v; }
}
export function normalizeSymbol(s) {
  const t = String(s || '').trim().toUpperCase();
  if (!t) return '';
  if (/^\d{1,5}$/.test(t)) return 'HK.' + t.padStart(5, '0');
  if (/^\d{1,5}\.HK$/.test(t)) return 'HK.' + t.split('.')[0].padStart(5, '0');
  const m = /^HK\.(\d{1,5})$/.exec(t);
  if (m) return 'HK.' + m[1].padStart(5, '0');
  return t;
}
