// Shared application state: the polled /api/status, page lifecycles, engine actions.

import { createHub, h } from './core.js';
import { api, post, stream } from './api.js';
import { confirmDialog, promptDialog, toast, toastError } from './ui.js';

const hub = createHub();
export const app = {
  status: null,
  statusError: null,
  fetchedAt: 0,
  strategies: null,
};

let inflight = null;
export async function refreshStatus() {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const s = await api('/api/status');
      app.status = s;
      app.statusError = null;
      app.fetchedAt = Date.now();
    } catch (err) {
      app.statusError = err;
    } finally {
      inflight = null;
    }
    hub.emit('status', app.status);
    return app.status;
  })();
  return inflight;
}
export const onStatus = (fn) => hub.on('status', fn);

export function engine() { return app.status?.engine || null; }
export function engineRunning() { return engine()?.state === 'running'; }

/** Current exchange time, interpolated between status polls. */
export function serverNow() {
  if (!app.status?.now) return new Date();
  return new Date(new Date(app.status.now).getTime() + (Date.now() - app.fetchedAt));
}

export async function strategies() {
  if (!app.strategies) app.strategies = await api('/api/strategies');
  return app.strategies;
}

export function go(hash) {
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent('hashchange'));
  else location.hash = hash;
}

// --------------------------------------------------------------------------- page lifecycle

export class PageCtx {
  constructor() {
    this.alive = true;
    this.disposers = [];
    this.children = [];
  }
  add(fn) { this.disposers.push(fn); return fn; }
  on(kind, fn) { return this.add(stream.on(kind, (ev) => this.alive && fn(ev))); }
  onStatus(fn) { return this.add(onStatus((s) => this.alive && fn(s))); }
  every(ms, fn) {
    const id = setInterval(() => { if (this.alive && !document.hidden) fn(); }, ms);
    return this.add(() => clearInterval(id));
  }
  own(chartLike) { this.add(() => chartLike.dispose ? chartLike.dispose() : chartLike.remove()); return chartLike; }
  child() {
    const c = new PageCtx();
    this.children.push(c);
    return c;
  }
  dispose() {
    this.alive = false;
    for (const c of this.children.splice(0)) c.dispose();
    for (const d of this.disposers.splice(0).reverse()) { try { d(); } catch (err) { console.error(err); } }
  }
}

// --------------------------------------------------------------------------- engine actions

async function run(label, fn, success) {
  try {
    const out = await fn();
    if (success) toast(typeof success === 'function' ? success(out) : success, 'success');
    return out;
  } catch (err) {
    toastError(err, label);
    return null;
  } finally {
    refreshStatus();
  }
}

export const actions = {
  start: () => run('Start engine failed', () => post('/api/engine/start'), 'Engine started'),
  async stop() {
    const env = app.status?.engine?.env;
    const ok = await confirmDialog('Stop the trading engine?', 'The engine stops processing bars and managing orders. Open positions stay open and working orders at the broker are not cancelled.', { confirmLabel: 'Stop engine', danger: env === 'REAL' });
    if (!ok) return null;
    return run('Stop engine failed', () => post('/api/engine/stop'), 'Engine stopped');
  },
  async halt() {
    const reason = await promptDialog('Halt new entries', {
      label: 'Reason', value: 'manual (console)', confirmLabel: 'Halt entries',
      message: 'The engine stops opening positions. Exits, stops and working orders keep running.',
    });
    if (reason == null) return null;
    return run('Halt failed', () => post('/api/engine/halt', { reason }), null); // the risk event toasts
  },
  resume: () => run('Resume failed', () => post('/api/engine/resume'), 'Entries resumed'),
  async cancelAll() {
    const ok = await confirmDialog('Cancel all open orders?', 'Every open order placed by the engine will be cancelled at the broker.', { confirmLabel: 'Cancel all orders', danger: true });
    if (!ok) return null;
    return run('Cancel all failed', () => post('/api/engine/cancel-all'), (r) => `Cancelled ${r?.cancelled ?? 0} order(s)`);
  },
  async flatten(symbol) {
    const env = app.status?.engine?.env;
    const what = symbol ? `your ${symbol} position` : 'ALL positions';
    const ok = await confirmDialog(symbol ? `Flatten ${symbol}?` : 'Flatten all positions?',
      h('span', {}, 'The engine sends sell orders to close ', h('strong', {}, what), ' at the configured order price.'),
      { confirmLabel: symbol ? `Flatten ${symbol}` : 'Flatten all', danger: true, detail: env === 'REAL' ? 'This is a REAL money account.' : `Account: ${env || 'unknown'}` });
    if (!ok) return null;
    return run('Flatten failed', () => post('/api/engine/flatten', { symbol: symbol || null }), (r) => `Flattening ${r?.positions ?? 0} position(s)`);
  },
  summary: () => run('Daily summary failed', () => post('/api/engine/summary'), 'Daily summary sent'),
};

export function envLabel(status) {
  const e = status?.engine;
  const mode = e?.mode || status?.trading?.mode;
  const env = e?.env || status?.trading?.env;
  if (mode === 'dry_run') return 'DRY_RUN';
  return env || '—';
}
