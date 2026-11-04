import { t as translate, LOCALES, getLocale, setLocale } from '../i18n.js';
// Settings: YAML config editor (validate / save), effective config, notifications, preferences, about.

import { h, mount, getPrefs, setPref } from '../core.js';
import { api, post, put } from '../api.js';
import { app, envLabel } from '../state.js';
import { card, btn, busy, callout, errorBox, segmented, kv, skeleton, toast, toastError, confirmDialog, badge, kbd } from '../ui.js';
import { MOD, showShortcuts } from '../palette.js';

function jsonTree(value, depth = 0) {
  if (value === null || value === undefined) return h('span', { class: 'j-null' }, 'null');
  if (Array.isArray(value)) {
    if (!value.length) return h('span', { class: 'j-punct' }, '[]');
    if (value.every((v) => v === null || typeof v !== 'object')) {
      return h('span', { class: 'j-inline' }, '[', value.map((v, i) => [i ? ', ' : '', jsonTree(v, depth + 1)]), ']');
    }
    return h('details', { class: 'j-node', open: depth < 1 }, h('summary', {}, h('span', { class: 'j-punct' }, `[${value.length}]`)),
      h('ul', {}, value.map((v, i) => h('li', {}, h('span', { class: 'j-key' }, `${i}: `), jsonTree(v, depth + 1)))));
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value);
    if (!entries.length) return h('span', { class: 'j-punct' }, '{}');
    return h('ul', { class: 'j-obj' }, entries.map(([k, v]) => {
      if (v && typeof v === 'object' && !(Array.isArray(v) && v.every((x) => x === null || typeof x !== 'object')) && Object.keys(v).length) {
        return h('li', {}, h('details', { class: 'j-node', open: depth < 0 }, h('summary', {}, h('span', { class: 'j-key' }, k), h('span', { class: 'j-punct' }, Array.isArray(v) ? ` [${v.length}]` : ` {${Object.keys(v).length}}`)), jsonTree(v, depth + 1)));
      }
      return h('li', {}, h('span', { class: 'j-key' }, `${k}: `), jsonTree(v, depth + 1));
    }));
  }
  if (typeof value === 'string') return h('span', { class: 'j-str' }, JSON.stringify(value));
  if (typeof value === 'number') return h('span', { class: 'j-num' }, String(value));
  if (typeof value === 'boolean') return h('span', { class: 'j-bool' }, String(value));
  return h('span', {}, String(value));
}

function yamlEditor(text) {
  const gutter = h('pre', { class: 'code-gutter', 'aria-hidden': 'true' });
  const area = h('textarea', { class: 'code-area', spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off', wrap: 'off', 'aria-label': translate('Configuration YAML') });
  area.value = text;
  let errLine = null;
  const renderGutter = () => {
    const n = area.value.split('\n').length;
    const frag = document.createDocumentFragment();
    for (let i = 1; i <= n; i++) frag.appendChild(h('span', { class: i === errLine ? 'err' : null }, `${i}\n`));
    gutter.replaceChildren(frag);
    gutter.scrollTop = area.scrollTop;
  };
  area.addEventListener('input', renderGutter);
  area.addEventListener('scroll', () => { gutter.scrollTop = area.scrollTop; });
  renderGutter();
  const el = h('div', { class: 'code-editor' }, gutter, area);
  return {
    el, area,
    setErrorLine(line) { errLine = line; renderGutter(); },
    goto(line) {
      const lines = area.value.split('\n');
      const pos = lines.slice(0, line - 1).reduce((s, l) => s + l.length + 1, 0);
      area.focus();
      area.setSelectionRange(pos, pos + (lines[line - 1] || '').length);
      area.scrollTop = Math.max(0, (line - 5) * parseFloat(getComputedStyle(area).lineHeight || '18'));
    },
  };
}

export default {
  title: () => translate('Settings'),
  async mount(root, { ctx }) {
    let hasUnsavedEdits = () => false;
    async function changeLanguage(event) {
      const select = event.target;
      const next = select.value;
      if (hasUnsavedEdits() && !await confirmDialog(translate('Discard unsaved changes?'),
        translate('Switching language reloads the page and discards unsaved configuration edits.'))) {
        select.value = getLocale();
        return;
      }
      setLocale(next);
    }
    const editorHolder = h('div', {}, card({ title: translate('Configuration'), body: skeleton(10) }));
    const effectiveHolder = h('div', {}, card({ title: translate('Effective config'), body: skeleton(6) }));
    const side = h('div', { class: 'stack' });
    mount(root, h('div', { class: 'settings-layout' }, h('div', { class: 'stack' }, editorHolder, effectiveHolder), side));

    // ---------------------------------------------------------------- preferences
    const prefs = getPrefs();
    const themeCard = (value, label, swatch) => h('button', {
      type: 'button', role: 'radio', class: 'theme-card', 'aria-checked': String(prefs.theme === value), onclick: () => setPref('theme', value),
    }, swatch, h('span', {}, label));
    const preview = h('div', { class: 'updown-preview', 'aria-hidden': 'true' },
      h('span', { class: 'candle-demo candle-up' }), h('span', { class: 'candle-demo candle-down' }),
      h('span', { class: 'up' }, '▲ +1.25%'), h('span', { class: 'down' }, '▼ −0.80%'));
    const prefCard = card({
      title: translate('Appearance'), subtitle: translate('Stored in this browser'),
      body: h('div', { class: 'stack' },
        h('div', { class: 'field' },
          h('label', { class: 'field-label', for: 'language-select' }, translate('Language')),
          h('select', { id: 'language-select', class: 'input', onchange: changeLanguage },
            Object.entries(LOCALES).map(([value, label]) => h('option', { value, selected: value === getLocale() }, label))),
          h('span', { class: 'field-hint' }, translate('Language changes reload the page. Save any edits first.'))),
        h('div', { class: 'field' }, h('span', { class: 'field-label' }, translate('Theme')),
          h('div', { class: 'theme-cards', role: 'radiogroup', 'aria-label': translate('Theme') },
            themeCard('dark', translate('Dark'), h('span', { class: 'theme-swatch dark' }, h('i', { class: 'sw-l' }), h('i'))),
            themeCard('light', translate('Light'), h('span', { class: 'theme-swatch' }, h('i', { class: 'sw-l' }), h('i'))),
            themeCard('system', translate('System'), h('span', { class: 'theme-swatch system' })))),
        h('div', { class: 'field' }, h('span', { class: 'field-label' }, translate('Price colours')),
          segmented([{ value: 'green-up', label: translate('Green up') }, { value: 'red-up', label: translate('Red up') }], prefs.updown, (v) => setPref('updown', v), { label: translate('Price colours') }),
          preview,
          h('span', { class: 'field-hint' }, translate('Applies to P/L, candles and fill markers. Red up is the mainland China convention.')))),
    });
    const keysCard = card({
      title: translate('Keyboard'),
      actions: btn(translate('All shortcuts'), { size: 'sm', tone: 'ghost', onclick: showShortcuts }),
      body: h('div', { class: 'shortcut-list' },
        h('span', {}, translate('Command palette')), kbd(MOD, 'K'),
        h('span', {}, translate('Go to a page')), kbd('G', 'D'),
        h('span', {}, translate('Toggle theme')), kbd('T')),
    });

    // ---------------------------------------------------------------- notifications
    const channels = app.status?.notifications || [];
    const notifyResult = h('div');
    const notifyCard = card({
      title: translate('Notifications'),
      body: h('div', { class: 'stack-sm' },
        h('div', { class: 'meta-line' }, channels.length ? channels.map((c) => badge(c, 'good', { class: 'badge badge-good badge-dot' })) : badge(translate("no channel enabled"), 'muted')),
        h('p', { class: 'muted small' }, translate('Channels are configured under notify.email / notify.telegram; secrets come from environment variables.')),
        h('div', {}, btn(translate('Send test notification'), {
          tone: 'secondary', iconName: 'bell', disabled: !channels.length,
          onclick: (e) => busy(e.currentTarget, async () => {
            try {
              const r = await post('/api/notify/test', {});
              mount(notifyResult, r.ok ? callout('success', translate('Test sent'), translate("Delivered via {0}.", { 0: channels.join(', ') })) : callout('error', translate('Some channels failed'), (r.errors || []).join('; ')));
            } catch (err) { toastError(err, translate('Notification test failed')); }
          }),
        })),
        notifyResult),
    });

    // ---------------------------------------------------------------- about
    const s = app.status || {};
    const aboutCard = card({
      title: translate('About'),
      body: h('div', { class: 'stack-sm' }, kv([
        [translate('Version'), h('span', { class: 'mono' }, s.version || '—')],
        [translate('Config file'), h('span', { class: 'mono break' }, s.config_path || translate("none (defaults)"))],
        [translate('Market'), `${s.market || '—'} (${s.market_tz || '—'})`],
        [translate('Trading'), translate('{env} · {mode} · {tf} bars', { env: envLabel(s), mode: s.trading?.mode || '—', tf: s.trading?.timeframe || '—' })],
        [translate('Data'), s.offline ? translate("offline (cache only)") : translate("online (OpenD)")],
        [translate('Auth'), s.token_required ? translate("console token required") : translate("local only, no token")],
        ['API', h('a', { href: '/api/docs', target: '_blank', rel: 'noopener' }, translate('OpenAPI docs'))],
        [translate('Fonts'), 'Geist, Geist Mono (OFL)'],
      ]), h('p', { class: 'muted small' }, translate('Charts by '), h('a', { href: 'https://www.tradingview.com/', target: '_blank', rel: 'noopener noreferrer' }, 'TradingView'), ' Lightweight Charts™ (Apache 2.0).')),
    });
    mount(side, prefCard, notifyCard, keysCard, aboutCard);

    // ---------------------------------------------------------------- editor
    let cfg;
    try {
      cfg = await api('/api/config');
    } catch (err) {
      if (!ctx.alive) return;
      mount(editorHolder, card({ title: translate('Configuration'), body: errorBox(err) }));
      mount(effectiveHolder);
      return;
    }
    if (!ctx.alive) return;
    const editor = yamlEditor(cfg.text || '');
    let saved = cfg.text || '';
    hasUnsavedEdits = () => editor.area.value !== saved;
    const out = h('div', { class: 'editor-out', 'aria-live': 'polite' });
    const dirty = h('span', { class: 'toolbar-meta' });
    const updateDirty = () => { mount(dirty, editor.area.value !== saved ? [h('span', { class: 'dot dot-warn' }), translate('Unsaved changes')] : null); };
    editor.area.addEventListener('input', updateDirty);

    function showError(text) {
      const m = /line (\d+)/i.exec(text || '');
      const line = m ? Number(m[1]) : null;
      editor.setErrorLine(line);
      mount(out, callout('error', translate('Invalid configuration'), h('div', {},
        h('pre', { class: 'pre-wrap mono small' }, text),
        line ? btn(translate("Go to line {0}", { 0: line }), { size: 'sm', tone: 'ghost', onclick: () => editor.goto(line) }) : null)));
    }
    async function validate() {
      const r = await post('/api/config/validate', { text: editor.area.value });
      if (r.ok) {
        editor.setErrorLine(null);
        mount(out, callout('success', translate('Configuration is valid'), translate('It passes schema validation. Save it to use it after a restart.')));
      } else showError(r.error);
      return r.ok;
    }
    const validateBtn = btn(translate('Validate'), { iconName: 'check', onclick: (e) => busy(e.currentTarget, () => validate().catch((err) => toastError(err, translate('Validate failed')))) });
    const saveBtn = btn(translate('Save'), {
      tone: 'primary', disabled: !cfg.editable, title: cfg.editable ? null : translate('The server was started without --config'),
      onclick: (e) => busy(e.currentTarget, async () => {
        try {
          if (!(await validate())) return;
          const ok = await confirmDialog(translate('Save configuration?'), translate("Overwrite {0}? A timestamped backup is written first. Changes take effect after a restart.", { 0: cfg.path }), { confirmLabel: translate('Save') });
          if (!ok) return;
          const r = await put('/api/config', { text: editor.area.value });
          saved = editor.area.value;
          updateDirty();
          mount(out, callout('success', translate('Saved — restart required'), h('div', {}, h('div', {}, translate('Saved to '), h('span', { class: 'mono break' }, r.saved)), h('div', {}, translate('Backup: '), h('span', { class: 'mono break' }, r.backup)), h('div', {}, translate('Restart futu_algo for the new settings to take effect.')))));
          toast(translate('Configuration saved; restart required'), 'success');
        } catch (err) {
          if (err.status === 422) showError(err.detail);
          else toastError(err, translate('Save failed'));
        }
      }),
    });
    const revertBtn = btn(translate('Revert'), { tone: 'ghost', onclick: () => { editor.area.value = saved; editor.area.dispatchEvent(new Event('input')); editor.setErrorLine(null); mount(out); } });

    mount(editorHolder, card({
      title: translate('Configuration'),
      subtitle: cfg.path ? h('span', { class: 'mono break' }, cfg.path) : translate('Read-only: started without a config file (showing the defaults as YAML)'),
      body: h('div', { class: 'stack-sm' },
        cfg.editable ? null : callout('info', translate('Read-only'), translate('The server was started without --config, so there is no file to save to. You can still validate edits.')),
        editor.el,
        h('div', { class: 'form-actions' }, saveBtn, validateBtn, revertBtn, h('span', { class: 'spacer' }), dirty),
        out),
    }));
    mount(effectiveHolder, card({ title: translate('Effective configuration'), subtitle: translate('What the running process uses; secrets appear as environment variable names'), body: h('div', { class: 'json-tree mono' }, jsonTree(cfg.effective)) }));
  },
};
