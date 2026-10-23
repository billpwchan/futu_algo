import zhCN from './locales/zh-CN.js';

export const LOCALES = { en: 'English', 'zh-CN': '简体中文' };
const catalogs = { en: {}, 'zh-CN': zhCN };
const KEY = 'futu_algo.locale';

export function normalizeLocale(value) {
  const tag = String(value || '').toLowerCase().replaceAll('_', '-');
  const exact = Object.keys(LOCALES).find(key => key.toLowerCase() === tag);
  if (exact) return exact;
  if (tag === 'zh' || tag === 'zh-cn' || tag === 'zh-sg' || tag.startsWith('zh-hans')) return 'zh-CN';
  return 'en';
}

function initialLocale() {
  const requested = new URLSearchParams(globalThis.location?.search || '').get('lang');
  if (Object.hasOwn(LOCALES, requested)) return requested;
  try {
    const saved = window.localStorage.getItem(KEY);
    if (Object.hasOwn(LOCALES, saved)) return saved;
  } catch { /* Private browsing can disable storage. */ }
  return normalizeLocale(globalThis.navigator?.language);
}

let locale = initialLocale();
export function getLocale() { return locale; }
export function intlLocale() { return locale === 'en' ? 'en-US' : locale; }

/** Explicit translation only: never translate API identifiers or arbitrary user data. */
export function t(message, params = {}) {
  const catalog = catalogs[locale] || catalogs.en;
  const translated = Object.hasOwn(catalog, message) ? catalog[message] : message;
  return String(translated).replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(params, key) ? String(params[key]) : match);
}

/** Reload rebuilds module-level labels and chart canvases consistently. */
export function setLocale(value) {
  if (!Object.hasOwn(LOCALES, value) || value === locale) return;
  locale = value;
  try {
    window.localStorage.setItem(KEY, value);
  } catch {
    const url = new URL(window.location.href);
    url.searchParams.set('lang', value);
    window.location.assign(url.href);
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.delete('lang');
  if (url.href !== window.location.href) window.location.assign(url.href);
  else window.location.reload();
}

export function localizeShell() {
  document.documentElement.lang = locale;
  for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const attr of ['aria-label', 'title']) {
    for (const el of document.querySelectorAll(`[data-i18n-${attr}]`)) el.setAttribute(attr, t(el.getAttribute(`data-i18n-${attr}`)));
  }
}
