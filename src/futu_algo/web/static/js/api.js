// HTTP + server-sent events. Every mutating request carries X-Futu-Algo: 1 (the server's
// CSRF guard); a console token, when the server requires one, is sent as a Bearer header
// and as ?token= on the event stream (EventSource cannot set headers).

import { storage, createHub, parseJSONMaybe } from './core.js';

const TOKEN_KEY = 'futu_algo.token';
let token = storage.get(TOKEN_KEY, null, 'session');
let tokenPrompt = null; // set by the app: async () => string|null
let tokenPending = null;

export class ApiError extends Error {
  constructor(status, detail, body) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

export function setTokenPrompt(fn) { tokenPrompt = fn; }
export function getToken() { return token; }
export function setToken(t) {
  token = t || null;
  storage.set(TOKEN_KEY, token, 'session');
  stream.reconnect();
}

async function askToken() {
  if (!tokenPrompt) return null;
  if (!tokenPending) {
    tokenPending = tokenPrompt().finally(() => { tokenPending = null; });
  }
  const t = await tokenPending;
  if (t) setToken(t);
  return t;
}

function detailOf(body, status) {
  if (body && typeof body === 'object' && body.detail != null) {
    const d = body.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join('.') || 'body'}: ${e.msg}`).join('; ');
    return JSON.stringify(d);
  }
  if (typeof body === 'string' && body.trim()) return body.trim().slice(0, 300);
  return `Request failed (HTTP ${status})`;
}

/** api('/api/status') ; api('/api/engine/halt', {method: 'POST', body: {...}}) */
export async function api(path, { method = 'GET', body, signal, retried = false } = {}) {
  const headers = { Accept: 'application/json' };
  if (method !== 'GET') {
    headers['X-Futu-Algo'] = '1';
    headers['Content-Type'] = 'application/json';
  }
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(path, {
      method, headers, signal, credentials: 'same-origin',
      body: method === 'GET' ? undefined : JSON.stringify(body ?? {}),
    });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError(0, 'Cannot reach the futu_algo server. Is it running?');
  }
  const text = await res.text();
  let data = text;
  try { data = text ? JSON.parse(text) : null; } catch { /* plain text body */ }
  if (res.status === 401 && !retried) {
    const t = await askToken();
    if (t) return api(path, { method, body, signal, retried: true });
  }
  if (!res.ok) throw new ApiError(res.status, detailOf(data, res.status), data);
  return data;
}

export const post = (path, body) => api(path, { method: 'POST', body });
export const put = (path, body) => api(path, { method: 'PUT', body });
export const del = (path) => api(path, { method: 'DELETE' });

/** Poll a job until done/failed. onProgress(job) on every poll. Resolves with the final job. */
export async function waitJob(id, { onProgress, interval = 700, isAlive = () => true } = {}) {
  for (;;) {
    const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
    if (!isAlive()) return job;
    onProgress?.(job);
    if (job.status === 'done' || job.status === 'failed') return job;
    await new Promise((r) => setTimeout(r, interval));
  }
}

// --------------------------------------------------------------------------- event stream

export const KINDS = ['engine', 'bar', 'signal', 'order', 'fill', 'rejection', 'risk', 'error', 'account', 'screener', 'daily_summary', 'backtest', 'log'];

export function normalizeEvent(ev) {
  return { ...ev, data: parseJSONMaybe(ev.data) || {} };
}

export const stream = (() => {
  const hub = createHub();
  const seen = new Set();
  const seenOrder = [];
  const recent = [];
  let es = null;
  let state = 'connecting';
  let retryTimer = null;

  function setState(s) {
    if (s === state) return;
    state = s;
    hub.emit('state', s);
  }

  function handle(raw) {
    let ev;
    try { ev = normalizeEvent(JSON.parse(raw)); } catch { return; }
    const key = `${ev.id}|${ev.time}`;
    if (seen.has(key)) return;
    seen.add(key);
    seenOrder.push(key);
    if (seenOrder.length > 4000) seen.delete(seenOrder.shift());
    recent.push(ev);
    if (recent.length > 600) recent.shift();
    hub.emit(ev.kind, ev);
    hub.emit('event', ev);
  }

  function connect() {
    clearTimeout(retryTimer);
    if (es) es.close();
    setState('connecting');
    const url = '/api/stream' + (token ? `?token=${encodeURIComponent(token)}` : '');
    es = new EventSource(url);
    es.onopen = () => setState('live');
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setState('offline');
        retryTimer = setTimeout(connect, 5000);
      } else setState('reconnecting');
    };
    es.onmessage = (e) => handle(e.data);
    for (const kind of KINDS) es.addEventListener(kind, (e) => handle(e.data));
  }

  return {
    start: connect,
    reconnect() { if (es) connect(); },
    on: hub.on,
    get state() { return state; },
    recent: () => recent.slice(),
  };
})();
