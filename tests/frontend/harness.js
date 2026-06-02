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
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';
import { createInstrumenter } from 'istanbul-lib-instrument';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC_DIR = path.resolve(HERE, '../../agents/web/static');
const ROOT = path.resolve(HERE, '../..');

// Vendored React always loads first; everything else mirrors index.html order.
const VENDOR = ['react.production.min.js', 'react-dom.production.min.js'];

// Coverage: when HUD_COVERAGE=1, instrument the app's own static files with
// istanbul before injecting them, then dump the per-window __coverage__ at
// cleanup. `nyc report` aggregates the .nyc_output dumps (see coverage.mjs).
// We never instrument the vendored React UMD.
const COVERAGE = process.env.HUD_COVERAGE === '1';
const instrumenter = COVERAGE
  ? createInstrumenter({ esModules: false, compact: true, coverageVariable: '__coverage__' })
  : null;
const NYC_OUTPUT = path.join(ROOT, '.nyc_output');

function readStatic(name, { instrument = false } = {}) {
  const file = name.endsWith('.js') ? name : `${name}.js`;
  const abs = path.join(STATIC_DIR, file);
  const code = fs.readFileSync(abs, 'utf8');
  if (instrument && instrumenter) {
    return instrumenter.instrumentSync(code, abs);
  }
  return code;
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
 * @param {Function} [opts.fetch]  a fetch stub installed before the app files
 *                                 run (needed for app.js, which mounts on load).
 * @returns {{ window, document, React, ReactDOM, hud, render, cleanup }}
 */
export function loadHud(opts = {}) {
  const { files = ['i18n', 'data', 'components'], expose = [], lang, fetch } = opts;

  // Capture uncaught script errors. JSDOM otherwise swallows a SyntaxError or
  // throw inside an injected file (reports to stderr and keeps going), which
  // would let a broken shipped artifact pass with a green suite. We surface
  // them and fail loadHud at load time.
  const jsdomErrors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', (err) => jsdomErrors.push(err));

  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url: 'http://127.0.0.1:8080/',
    virtualConsole,
  });
  const { window } = dom;

  if (lang) window.localStorage.setItem('hud.lang', lang);
  // Install before any app file runs — app.js mounts (and fetches) at load.
  if (fetch) window.fetch = fetch;

  for (const name of VENDOR) {
    injectScript(window.document, readStatic(name));
  }
  for (const name of files) {
    injectScript(window.document, readStatic(name, { instrument: true }));
  }

  // Scripts run synchronously under runScripts:'dangerously', so any load-time
  // error (syntax error, throw at module top-level) is already captured here.
  if (jsdomErrors.length) {
    const detail = jsdomErrors
      .map((e) => (e.detail && (e.detail.stack || e.detail.message)) || e.message || String(e))
      .join('\n');
    throw new Error(`HUD static script failed to load:\n${detail}`);
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
    const root = ReactDOM.createRoot(container);
    ReactDOM.flushSync(() => root.render(element));
    return { container, root, html: container.innerHTML };
  }

  // React 18 attaches its synthetic listeners at the root container, so a
  // bubbling native event drives onClick/onChange. flushSync forces the
  // resulting state update to land in the DOM before we assert.
  function fire(el, type, init = {}) {
    ReactDOM.flushSync(() => {
      el.dispatchEvent(new window.Event(type, { bubbles: true, ...init }));
    });
  }
  const click = (el) => fire(el, 'click');

  // React tracks input values, so we must set via the native setter before
  // dispatching, otherwise the change is swallowed as a no-op.
  function setNativeValue(el, value, proto) {
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value').set;
    setter.call(el, value);
  }
  function type(el, value) {
    setNativeValue(el, value, window.HTMLInputElement);
    fire(el, 'input');
  }
  function selectOption(el, value) {
    setNativeValue(el, value, window.HTMLSelectElement);
    fire(el, 'change');
  }
  function toggle(el) {
    // Checkboxes: React maps onChange to the click event. The native .click()
    // method runs the activation behaviour (flipping `checked`) that a bare
    // dispatchEvent does not, so React sees a real change.
    ReactDOM.flushSync(() => el.click());
  }
  function keyDown(el, key) {
    ReactDOM.flushSync(() => {
      el.dispatchEvent(new window.KeyboardEvent('keydown', { key, bubbles: true }));
    });
  }

  // Settle async work (awaited fetches → setState) then force a synchronous
  // flush. React's scheduler runs on a macrotask that can land after a single
  // setTimeout(0), so we pump a few turns before flushing.
  async function flush(turns = 3) {
    for (let i = 0; i < turns; i++) {
      await new Promise((r) => setTimeout(r, 0));
    }
    ReactDOM.flushSync(() => {});
  }

  return {
    window,
    document: window.document,
    React,
    ReactDOM,
    hud: window.__hud || {},
    render,
    fire,
    click,
    type,
    selectOption,
    toggle,
    keyDown,
    flush,
    cleanup: () => {
      if (COVERAGE && window.__coverage__) {
        fs.mkdirSync(NYC_OUTPUT, { recursive: true });
        fs.writeFileSync(
          path.join(NYC_OUTPUT, `${crypto.randomUUID()}.json`),
          JSON.stringify(window.__coverage__),
        );
      }
      window.close();
    },
  };
}
