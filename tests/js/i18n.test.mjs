import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import zhCN from '../../src/futu_algo/web/static/js/locales/zh-CN.js';

const moduleURL = new URL('../../src/futu_algo/web/static/js/i18n.js', import.meta.url);
let serial = 0;
async function load({ language = 'en-US', saved = null, blocked = false, search = '' } = {}) {
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { language } });
  globalThis.location = { search };
  globalThis.window = {
    localStorage: {
      getItem() { if (blocked) throw new Error('blocked'); return saved; },
      setItem(key, value) { if (blocked) throw new Error('blocked'); saved = value; },
    },
    location: { href: `http://localhost/${search}#/settings`, reload() {}, assign(url) { this.href = url; } },
  };
  return import(`${moduleURL.href}?test=${serial++}`);
}

test('locale detection, saved preferences and unsupported-language fallback', async () => {
  assert.equal((await load({ language: 'zh-CN' })).getLocale(), 'zh-CN');
  assert.equal((await load({ language: 'zh-Hans-SG' })).getLocale(), 'zh-CN');
  assert.equal((await load({ language: 'fr-FR' })).getLocale(), 'en');
  assert.equal((await load({ language: 'zh-CN', saved: 'en' })).getLocale(), 'en');
  assert.equal((await load({ language: 'zh-CN', saved: 'invalid' })).getLocale(), 'zh-CN');
  assert.equal((await load({ search: '?lang=zh-CN' })).getLocale(), 'zh-CN');
});

test('translations interpolate once, fall back to source and preserve data', async () => {
  const { t } = await load({ language: 'zh-CN' });
  assert.equal(t('Settings'), '设置');
  assert.equal(t('Open the {0} chart', { 0: 'HK.00700' }), '打开 HK.00700 图表');
  assert.equal(t('Unknown message {name}', { name: '<script>{name}</script>' }), 'Unknown message <script>{name}</script>');
  assert.equal(t('Missing {value}'), 'Missing {value}');
  assert.equal(t('toString'), 'toString');
  assert.equal((await load()).t('Settings'), 'Settings');
});

test('screener labels translate known values and leave unknown identifiers intact', async () => {
  const { t } = await load({ language: 'zh-CN' });
  assert.equal(t('CUR_PRICE'), '现价');
  assert.equal(t('MA_ALIGNMENT_LONG'), '均线多头排列');
  assert.equal(t('cur_price'), '现价');
  assert.equal(t('turnover_today'), '今日成交额');
  assert.equal(t('Liquid HK stocks with MA5 > MA10 > MA20 > MA30 > MA60 on daily bars'),
    '日线 MA5 > MA10 > MA20 > MA30 > MA60 的高流动性港股');
  assert.equal(t('UNKNOWN_FUTU_FIELD'), 'UNKNOWN_FUTU_FIELD');
});

test('blocked storage still allows language switching via URL', async () => {
  const i18n = await load({ blocked: true });
  assert.equal(i18n.getLocale(), 'en');
  i18n.setLocale('invalid');
  assert.equal(i18n.getLocale(), 'en');
  i18n.setLocale('zh-CN');
  assert.equal(new URL(window.location.href).searchParams.get('lang'), 'zh-CN');
  assert.equal(new URL(window.location.href).hash, '#/settings');
});

test('catalog has no duplicate keys and preserves every placeholder', () => {
  const source = readFileSync(new URL('../../src/futu_algo/web/static/js/locales/zh-CN.js', import.meta.url), 'utf8');
  const keys = [...source.matchAll(/(?:'([^'\n]+)'|"([^"\n]+)")\s*:/g)].map(m => m[1] ?? m[2]);
  assert.equal(new Set(keys).size, keys.length, 'duplicate translation keys');
  const placeholders = text => [...text.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort();
  for (const [key, value] of Object.entries(zhCN)) {
    assert.ok(value.trim(), key);
    assert.deepEqual(placeholders(value), placeholders(key), key);
  }
});

test('every explicit UI translation has a Chinese catalog entry', () => {
  const root = fileURLToPath(new URL('../../src/futu_algo/web/static/', import.meta.url));
  for (const entry of readdirSync(root, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.js') || /vendor|locales/.test(entry.parentPath)) continue;
    const source = readFileSync(`${entry.parentPath}/${entry.name}`, 'utf8');
    for (const match of source.matchAll(/translate\(\s*(?:'([^'\n]+)'|"([^"\n]+)")/g)) {
      const key = match[1] ?? match[2];
      assert.ok(Object.hasOwn(zhCN, key), `${entry.name}: ${key}`);
    }
  }
});
