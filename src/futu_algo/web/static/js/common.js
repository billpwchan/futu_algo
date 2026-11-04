import { t as translate } from './i18n.js';
// Domain renderers shared by several pages.

import { h, fmtSignedMoney, fmtPct, signCls, fmtWhen, fmtDateTime } from './core.js';
import { badge } from './ui.js';

export function symLink(sym, { tf } = {}) {
  if (!sym) return null;
  return h('a', { href: `#/chart/${encodeURIComponent(sym)}${tf ? `?tf=${encodeURIComponent(tf)}` : ''}`, class: 'sym' }, sym);
}

/** Symbol code over its name, as used in every blotter. */
export function symCell(sym, name, opts) {
  return h('div', { class: 'sym-cell' }, symLink(sym, opts), name ? h('span', { class: 'sym-name', title: name }, name) : null);
}

export function sideBadge(side) {
  const s = String(side || '').toUpperCase();
  return h('span', { class: ['side', s === 'BUY' ? 'side-buy' : s === 'SELL' ? 'side-sell' : ''] }, translate(s || '—'));
}

const STATE_TONE = {
  pending: 'info', submitted: 'info', partial: 'warn', filled: 'good', cancelled: 'muted', failed: 'bad',
  working: 'info', done: 'good', queued: 'muted', running: 'info',
};
export function stateBadge(state) {
  return badge(translate(state || '—'), STATE_TONE[state] || 'neutral');
}

const LEVEL_TONE = { debug: 'muted', info: 'neutral', warning: 'warn', error: 'bad' };
export function levelBadge(level) { return h('span', { class: ['lvl-badge', `lvl-${level}`] }, translate(level === 'warning' ? 'warn' : level)); }
export { LEVEL_TONE };

const KIND_TONE = {
  engine: 'info', bar: 'muted', signal: 'accent', order: 'info', fill: 'good', rejection: 'warn', risk: 'warn',
  error: 'bad', account: 'neutral', screener: 'accent', daily_summary: 'neutral', backtest: 'accent', log: 'muted',
};
export function kindBadge(kind) { return badge(translate(kind === 'daily_summary' ? 'summary' : kind), KIND_TONE[kind] || 'neutral', { class: `badge badge-${KIND_TONE[kind] || 'neutral'} kind-badge` }); }

export function pnl(v, { pct } = {}) {
  return h('span', { class: signCls(v) }, pct ? fmtPct(v) : fmtSignedMoney(v));
}

export function timeCell(iso) {
  return h('time', { datetime: iso || '', title: iso ? `${fmtDateTime(iso)} HKT` : '' }, fmtWhen(iso));
}

export function eventMessage(ev) {
  const message = ev.message || '';
  let match = /^(BUY|SELL) (\d+) ([A-Z]+\.[A-Z0-9.-]+) blocked: order value ([\d,.]+) > buying power ([\d,.]+)$/.exec(message);
  if (match) return translate('Order blocked: {side} {quantity} shares of {symbol}; value {value} exceeds buying power {buyingPower}', {
    side: translate(match[1]), quantity: match[2], symbol: match[3], value: match[4], buyingPower: match[5],
  });
  match = /^([A-Z]+\.[A-Z0-9.-]+) (BUY|SELL) \(([^,]+), signal=([^)]*)\) (.+)$/.exec(message);
  if (match) {
    const shares = /^(\d+) shares$/.exec(match[5]);
    return translate('Signal: {symbol} {side} ({strategy}, signal={signal}), {detail}', {
      symbol: match[1], side: translate(match[2]), strategy: translate(match[3]), signal: match[4],
      detail: shares ? translate('{count} shares', { count: shares[1] }) : translate(match[5]),
    });
  }
  match = /^(BUY|SELL) (\d+) ([A-Z]+\.[A-Z0-9.-]+): (.+)$/.exec(message);
  if (match) return translate('{side} order: {quantity} shares of {symbol} ({reason})', {
    side: translate(match[1]), quantity: match[2], symbol: match[3], reason: translate(match[4]),
  });
  match = /^New trading day (\d{4}-\d{2}-\d{2}); starting equity ([\d,.]+)$/.exec(message);
  if (match) return translate('New trading day {day}; starting equity {equity}', { day: match[1], equity: match[2] });
  match = /^Engine running: (.+)$/.exec(message);
  if (match) return translate('Engine running: {symbols}', { symbols: match[1] });
  match = /^Engine starting \(([^,]+), ([^,]+), (\d+) symbols\)$/.exec(message);
  if (match) return translate('Engine starting ({env}, {timeframe}, {count} symbols)', {
    env: translate(match[1]), timeframe: match[2], count: match[3],
  });
  match = /^New entries halted: (.+)$/.exec(message);
  if (match) return translate('New entries halted: {reason}', { reason: translate(match[1]) });
  match = /^Entries resumed \((.+)\)$/.exec(message);
  if (match) return translate('Entries resumed ({reason})', { reason: translate(match[1]) });
  match = /^Trading universe hot-reloaded: (.*)$/.exec(message);
  if (match) return translate('Trading universe hot-reloaded: {symbols}', { symbols: match[1] });
  match = /^(.+) shares$/.exec(message);
  if (match) return translate('{count} shares', { count: match[1] });
  return translate(message);
}

export function feedItem(ev) {
  const msg = eventMessage(ev);
  const kind = ev.kind === 'daily_summary' ? 'summary' : ev.kind;
  return h('li', { class: ['feed-item', `lvl-${ev.level}`, `k-${ev.kind}`] },
    h('span', { class: 'feed-dot', 'aria-hidden': 'true' }),
    h('div', { class: 'feed-main' },
      h('div', { class: 'feed-kind' }, translate(kind), ev.symbol ? ` · ${ev.symbol}` : ''),
      h('div', { class: 'feed-msg' }, msg)),
    h('time', { class: 'feed-time', datetime: ev.time, title: `${fmtDateTime(ev.time)} HKT` }, fmtWhen(ev.time)));
}

export const PHASE_LABEL = {
  continuous: translate('Trading'), pre_open: translate('Pre-open'), lunch: translate('Lunch'), closing_auction: translate('Closing auction'),
  after_hours: translate('After hours'), closed: translate('Closed'), unknown: translate('Unknown'),
};

export const TIMEFRAMES = ['1M', '3M', '5M', '15M', '30M', '60M', '2H', '4H', 'DAY', 'WEEK', 'MON'];
