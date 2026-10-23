// Personal watchlist, kept separate from trading.universe and its order controls.
import { h, icon, normalizeSymbol, storage } from './core.js';
import { t as translate } from './i18n.js';

const KEY = 'futu_algo.watchlist';

export function getWatchlist() {
  const saved = storage.get(KEY, []);
  if (!Array.isArray(saved)) return [];
  const bySymbol = new Map();
  for (const entry of saved) {
    const raw = typeof entry === 'string' ? entry : entry?.symbol;
    const symbol = normalizeSymbol(raw);
    if (!symbol || !/^[A-Z]{2}\.[A-Z0-9][A-Z0-9.-]*$/.test(symbol)) continue;
    const name = typeof entry === 'object' && typeof entry?.name === 'string' ? entry.name : '';
    bySymbol.set(symbol, { symbol, name });
  }
  return [...bySymbol.values()];
}

export function isWatched(symbol) {
  const key = normalizeSymbol(symbol);
  return getWatchlist().some((item) => item.symbol === key);
}

export function addToWatchlist(symbol, name = '') {
  const key = normalizeSymbol(symbol);
  if (!key || !/^[A-Z]{2}\.[A-Z0-9][A-Z0-9.-]*$/.test(key)) return false;
  const items = getWatchlist();
  const existing = items.find((item) => item.symbol === key);
  if (existing) {
    if (name && existing.name !== name) {
      storage.set(KEY, items.map((item) => item.symbol === key ? { ...item, name } : item));
    }
    return false;
  }
  storage.set(KEY, [...items, { symbol: key, name: String(name || '') }]);
  return true;
}

export function removeFromWatchlist(symbol) {
  const key = normalizeSymbol(symbol);
  const items = getWatchlist();
  const next = items.filter((item) => item.symbol !== key);
  if (next.length === items.length) return false;
  storage.set(KEY, next);
  return true;
}

/** Small, accessible add/remove control shared by chart, results and the watchlist. */
export function watchlistButton(symbol, name = '', { compact = false, onChange } = {}) {
  const button = h('button', {
    type: 'button', class: compact ? 'icon-btn icon-btn-bordered' : 'btn btn-secondary btn-sm',
    onclick: (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (isWatched(symbol)) removeFromWatchlist(symbol);
      else addToWatchlist(symbol, name);
      render();
      onChange?.();
    },
  });

  function render() {
    const watched = isWatched(symbol);
    const label = translate(watched ? 'Remove from watchlist' : 'Add to watchlist');
    button.title = label;
    button.setAttribute('aria-label', `${label}: ${symbol}`);
    button.setAttribute('aria-pressed', String(watched));
    button.replaceChildren(icon(watched ? 'check' : 'bookmark', 14));
    if (!compact) button.appendChild(h('span', {}, label));
  }

  render();
  return button;
}
