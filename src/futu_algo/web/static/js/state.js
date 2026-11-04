import { t as translate } from './i18n.js';
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
  start: () => run(translate('Start engine failed'), () => post('/api/engine/start'), translate('Engine started')),
  async stop() {
    const env = app.status?.engine?.env;
    const ok = await confirmDialog(translate('Stop the trading engine?'), translate('The engine stops processing bars and managing orders. Open positions stay open and working orders at the broker are not cancelled.'), { confirmLabel: translate('Stop engine'), danger: env === 'REAL' });
    if (!ok) return null;
    return run(translate('Stop engine failed'), () => post('/api/engine/stop'), translate('Engine stopped'));
  },
  async halt() {
    const reason = await promptDialog(translate('Halt new entries'), {
      label: translate('Reason'), value: 'manual (console)', confirmLabel: translate('Halt entries'),
      message: translate('The engine stops opening positions. Exits, stops and working orders keep running.'),
    });
    if (reason == null) return null;
    return run(translate('Halt failed'), () => post('/api/engine/halt', { reason }), null); // the risk event toasts
  },
  resume: () => run(translate('Resume failed'), () => post('/api/engine/resume'), translate('Entries resumed')),
  async cancelAll() {
    const ok = await confirmDialog(translate('Cancel all open orders?'), translate('Every open order placed by the engine will be cancelled at the broker.'), { confirmLabel: translate('Cancel all orders'), danger: true });
    if (!ok) return null;
    return run(translate('Cancel all failed'), () => post('/api/engine/cancel-all'), (r) => translate("Cancelled {0} order(s)", { 0: r?.cancelled ?? 0 }));
  },
  async flatten(symbol) {
    const env = app.status?.engine?.env;
    const what = symbol ? translate("your {0} position", { 0: symbol }) : translate('ALL positions');
    const ok = await confirmDialog(symbol ? translate("Flatten {0}?", { 0: symbol }) : translate('Flatten all positions?'),
      h('span', {}, translate('The engine sends sell orders to close '), h('strong', {}, what), translate(' at the configured order price.')),
      { confirmLabel: symbol ? translate("Flatten {0}", { 0: symbol }) : translate('Flatten all'), danger: true, detail: env === 'REAL' ? translate('This is a REAL money account.') : translate("Account: {0}", { 0: env || 'unknown' }) });
    if (!ok) return null;
    return run(translate('Flatten failed'), () => post('/api/engine/flatten', { symbol: symbol || null }), (r) => translate("Flattening {0} position(s)", { 0: r?.positions ?? 0 }));
  },
  summary: () => run(translate('Daily summary failed'), () => post('/api/engine/summary'), translate('Daily summary sent')),
};

export function envLabel(status) {
  const e = status?.engine;
  const mode = e?.mode || status?.trading?.mode;
  const env = e?.env || status?.trading?.env;
  if (mode === 'dry_run') return 'DRY_RUN';
  return env || '—';
}
