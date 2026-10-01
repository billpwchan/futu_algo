// Domain renderers shared by several pages.

import { h, fmtSignedMoney, fmtPct, signCls, fmtWhen, fmtDateTime } from './core.js';
import { badge } from './ui.js';

export function symLink(sym, { tf } = {}) {
  if (!sym) return null;
  return h('a', { href: `#/chart/${encodeURIComponent(sym)}${tf ? `?tf=${encodeURIComponent(tf)}` : ''}`, class: 'sym mono' }, sym);
}

export function sideBadge(side) {
  const s = String(side || '').toUpperCase();
  return h('span', { class: ['side', s === 'BUY' ? 'side-buy' : s === 'SELL' ? 'side-sell' : ''] }, s || '—');
}

const STATE_TONE = {
  pending: 'info', submitted: 'info', partial: 'warn', filled: 'good', cancelled: 'muted', failed: 'bad',
  working: 'info', done: 'good', queued: 'muted', running: 'info',
};
export function stateBadge(state) {
  return badge(state || '—', STATE_TONE[state] || 'neutral');
}

const LEVEL_TONE = { debug: 'muted', info: 'neutral', warning: 'warn', error: 'bad' };
export function levelBadge(level) { return badge(level, LEVEL_TONE[level] || 'neutral'); }

const KIND_TONE = {
  engine: 'info', bar: 'muted', signal: 'accent', order: 'info', fill: 'good', rejection: 'warn', risk: 'warn',
  error: 'bad', account: 'neutral', screener: 'accent', daily_summary: 'neutral', backtest: 'accent', log: 'muted',
};
export function kindBadge(kind) { return badge(kind === 'daily_summary' ? 'summary' : kind, KIND_TONE[kind] || 'neutral', { class: `badge badge-${KIND_TONE[kind] || 'neutral'} kind-badge` }); }

export function pnl(v, { pct } = {}) {
  return h('span', { class: signCls(v) }, pct ? fmtPct(v) : fmtSignedMoney(v));
}

export function timeCell(iso) {
  return h('time', { datetime: iso || '', title: iso ? `${fmtDateTime(iso)} HKT` : '' }, fmtWhen(iso));
}

export function feedItem(ev) {
  const msg = ev.message || '';
  return h('li', { class: ['feed-item', `lvl-${ev.level}`] },
    h('time', { class: 'feed-time num', datetime: ev.time, title: `${fmtDateTime(ev.time)} HKT` }, fmtWhen(ev.time)),
    kindBadge(ev.kind),
    h('span', { class: 'feed-msg' }, msg));
}

export const PHASE_LABEL = {
  continuous: 'Trading', pre_open: 'Pre-open', lunch: 'Lunch', closing_auction: 'Closing auction',
  after_hours: 'After hours', closed: 'Closed', unknown: 'Unknown',
};

export const TIMEFRAMES = ['1M', '3M', '5M', '15M', '30M', '60M', '2H', '4H', 'DAY', 'WEEK', 'MON'];
