'use strict';
/* console.js — human-friendly HUD chrome (HUD redesign slice 2).
   - api()/adminFetch() shared helpers
   - SettingsMenu: one ⚙ dropdown that absorbs theme/density/scanline/language,
     the admin token, a link to /admin, the version, and the panel toggles
     (Cognition/Systems/Workflows/Observability) + the NetworkBrain toggle.
   This declutters the TopBar from ~11 controls down to status + ⚙. */

/* ── shared fetch helpers (global) ───────────────────────────────────────── */
window.api = async function (url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
};

/* admin token lives in localStorage; injected on every /api/admin call so the
   admin panel works when ADMIN_TOKEN is set (previously failed silently). */
window.adminToken = function () { return localStorage.getItem('hud.admin_token') || ''; };
window.adminFetch = async function (url, opts) {
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers, { 'X-Admin-Token': window.adminToken() });
  const r = await fetch(url, opts);
  if (r.status === 401) throw new Error('admin token required (set it in ⚙ Settings)');
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
};

(function () {
  /* h, useState are global lexical bindings from components.js (classic scripts
     share the global scope); they are NOT on window, so reference them bare. */

  function setPref(key, attr, value) {
    localStorage.setItem(key, value);
    document.documentElement.setAttribute(attr, value);
  }

  function Row(label, control) {
    return h('div', { className: 'set-row' },
      h('label', { className: 'set-label' }, label), control);
  }

  function Select(value, options, onChange) {
    return h('select', {
      className: 'set-select', value: value,
      onChange: function (e) { onChange(e.target.value); },
    }, options.map(function (o) {
      return h('option', { key: o[0], value: o[0] }, o[1]);
    }));
  }

  function Toggle(on, onClick, labelOn, labelOff) {
    return h('button', {
      className: 'set-toggle ' + (on ? 'is-on' : ''), onClick: onClick,
    }, on ? (labelOn || 'On') : (labelOff || 'Off'));
  }

  window.SettingsMenu = function SettingsMenu(props) {
    const _o = useState(false), open = _o[0], setOpen = _o[1];
    const _t = useState(localStorage.getItem('hud.theme') || 'default'), theme = _t[0], setTheme = _t[1];
    const _d = useState(localStorage.getItem('hud.density') || 'normal'), density = _d[0], setDensity = _d[1];
    const _s = useState((localStorage.getItem('hud.scanline') || 'on') === 'on'), scan = _s[0], setScan = _s[1];
    const _tok = useState(window.adminToken()), tok = _tok[0], setTok = _tok[1];
    const _lang = useState(window.currentLocale || 'ro'), lang = _lang[0], setLang = _lang[1];
    const t = props.toggles || {};

    function close(e) { if (e.target.classList.contains('set-backdrop')) setOpen(false); }

    return h('div', { className: 'set-wrap' },
      h('button', { className: 'topbar-btn set-gear', onClick: function () { setOpen(!open); }, title: 'Settings' }, '⚙'),
      open && h('div', { className: 'set-backdrop', onClick: close },
        h('div', { className: 'set-menu', role: 'dialog', 'aria-label': 'Settings' },
          h('div', { className: 'set-head' }, h('span', null, 'Settings'),
            h('button', { className: 'set-x', onClick: function () { setOpen(false); } }, '×')),

          h('div', { className: 'set-group-title' }, 'Appearance'),
          Row('Theme', Select(theme, [['default', 'Default'], ['obsidian', 'Obsidian'], ['aeroglass', 'Aero Glass'], ['cyberpunk', 'Cyberpunk']], function (v) {
            setTheme(v); setPref('hud.theme', 'data-theme', v);
            window.dispatchEvent(new CustomEvent('jarvis:theme_changed', { detail: v }));
          })),
          Row('Density', Select(density, [['compact', 'Compact'], ['normal', 'Normal'], ['comfy', 'Comfy']], function (v) {
            setDensity(v); setPref('hud.density', 'data-density', v);
          })),
          Row('Scanline', Toggle(scan, function () {
            const v = !scan; setScan(v); setPref('hud.scanline', 'data-scanline', v ? 'on' : 'off');
          })),
          Row('Language', Toggle(lang === 'en', function () {
            const v = lang === 'ro' ? 'en' : 'ro'; setLang(v); if (window.setLocale) window.setLocale(v);
          }, 'EN', 'RO')),

          h('div', { className: 'set-group-title' }, 'Panels'),
          t.network !== undefined && Row('Network graph', Toggle(t.network, t.onNetwork)),
          Row('Cognition', Toggle(t.cognition, t.onCognition)),
          Row('Systems', Toggle(t.systems, t.onSystems)),
          Row('Workflows', Toggle(t.workflows, t.onWorkflows)),
          Row('Observability', Toggle(t.observability, t.onObservability)),

          h('div', { className: 'set-group-title' }, 'Admin'),
          Row('Admin token', h('input', {
            className: 'set-input', type: 'password', value: tok, placeholder: 'X-Admin-Token',
            onChange: function (e) { setTok(e.target.value); localStorage.setItem('hud.admin_token', e.target.value); },
          })),
          h('a', { className: 'set-link', href: '/admin', target: '_blank', rel: 'noopener' }, 'Open Admin Panel →'),

          h('div', { className: 'set-foot' }, 'JARVIS HUB · v' + (props.version || '—') + ' · BONOBO-WS'),
        )
      )
    );
  };
})();
