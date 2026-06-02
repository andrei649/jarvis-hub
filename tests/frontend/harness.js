// HUD test harness.
//
// The Jarvis HUD has no bundler: it ships as a sequence of <script> tags
// (vendored React 18 UMD + the files in agents/web/static) that share browser
// globals. components.js declares helpers as `const` (lexical globals, NOT on
// window) and components as `function` declarations (which DO land on window).
//
// To test the *real* artifacts we boot a JSDOM with `runScripts: 'dangerously'`
// and inject the actual files as <script> elements — exactly like the browser.
// A trailing "expose" script then reads the lexical `const` bindings (esc,
// pad2, h, ...) from inside the page realm and surfaces them on `window.__hud`
// so specs can reach them.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = path.resolve(HERE, '../../agents/web/static');

// Vendored React always loads first; everything else mirrors index.html order.
const VENDOR = ['react.production.min.js', 'react-dom.production.min.js'];

function readStatic(name) {
  const file = name.endsWith('.js') ? name : `${name}.js`;
  return fs.readFileSync(path.join(STATIC_DIR, file), 'utf8');
}

function injectScript(doc, code) {
  const el = doc.createElement('script');
  el.textContent = code;
  doc.head.appendChild(el);
}

/**
 * Boot a fresh HUD realm.
 *
 * @param {object}   [opts]
 * @param {string[]} [opts.files]  static file base-names to load after React,
 *                                 in order (default: i18n, data, components).
 * @param {string[]} [opts.expose] identifier names to surface on window.__hud
 *                                 (use this for `const` helpers/components).
 * @param {string}   [opts.lang]   value pre-seeded into localStorage hud.lang.
 * @returns {{ window, document, React, ReactDOM, hud, render, cleanup }}
 */
export function loadHud(opts = {}) {
  const { files = ['i18n', 'data', 'components'], expose = [], lang } = opts;

  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url: 'http://127.0.0.1:8080/',
  });
  const { window } = dom;

  if (lang) window.localStorage.setItem('hud.lang', lang);

  for (const name of [...VENDOR, ...files]) {
    injectScript(window.document, readStatic(name));
  }

  if (expose.length) {
    const pairs = expose
      .map((n) => `${JSON.stringify(n)}: (typeof ${n} !== 'undefined' ? ${n} : undefined)`)
      .join(', ');
    injectScript(window.document, `window.__hud = Object.assign(window.__hud || {}, { ${pairs} });`);
  }

  const React = window.React;
  const ReactDOM = window.ReactDOM;

  // Render synchronously via flushSync so the DOM is populated by the time the
  // call returns (createRoot otherwise schedules work asynchronously).
  function render(element) {
    const container = window.document.createElement('div');
    window.document.body.appendChild(container);
    window.IS_REACT_ACT_ENVIRONMENT = true;
    const root = ReactDOM.createRoot(container);
    ReactDOM.flushSync(() => root.render(element));
    return { container, root, html: container.innerHTML };
  }

  return {
    window,
    document: window.document,
    React,
    ReactDOM,
    hud: window.__hud || {},
    render,
    cleanup: () => window.close(),
  };
}
