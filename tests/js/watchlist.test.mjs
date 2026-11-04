import test from 'node:test';
import assert from 'node:assert/strict';

const values = new Map();
globalThis.window = {
  localStorage: {
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, value); },
    removeItem(key) { values.delete(key); },
  },
};
const { addToWatchlist, getWatchlist, isWatched, removeFromWatchlist } = await import(
  '../../src/futu_algo/web/static/js/watchlist-store.js'
);

test('personal watchlist normalizes symbols, keeps names and avoids duplicates', () => {
  values.clear();
  assert.equal(addToWatchlist('700', 'Tencent'), true);
  assert.equal(addToWatchlist('HK.00700', 'Tencent Holdings'), false);
  assert.deepEqual(getWatchlist(), [{ symbol: 'HK.00700', name: 'Tencent Holdings' }]);
  assert.equal(isWatched('700'), true);
  assert.equal(addToWatchlist('not a symbol'), false);
  assert.equal(getWatchlist().length, 1);
});

test('personal watchlist removes one symbol and preserves other entries', () => {
  values.clear();
  addToWatchlist('00700', 'Tencent');
  addToWatchlist('09988', 'Alibaba');
  assert.equal(removeFromWatchlist('700'), true);
  assert.equal(removeFromWatchlist('700'), false);
  assert.deepEqual(getWatchlist(), [{ symbol: 'HK.09988', name: 'Alibaba' }]);
});

test('legacy string entries are normalized and duplicate entries collapse', () => {
  values.set('futu_algo.watchlist', JSON.stringify(['700', 'HK.00700', { symbol: '09988', name: 'Alibaba' }]));
  assert.deepEqual(getWatchlist(), [
    { symbol: 'HK.00700', name: '' }, { symbol: 'HK.09988', name: 'Alibaba' },
  ]);
});
