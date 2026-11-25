// shoot.mjs — render a local HTML file (or a localhost URL) headlessly and save a PNG.
//
//   node shoot.mjs <file-or-url> <out.png> [--w 1920] [--h 1080] [--scheme dark|light]
//                  [--full] [--wait 400] [--dpr 1] [--selector CSS] [--axe] [--hash '#x']
//
// Prints a JSON report on stdout: page size, horizontal overflow, console errors,
// blocked external requests (anything that is not file:, data:, blob: or loopback is
// ABORTED and listed — mockups must be fully self-contained), and, with --axe,
// the axe-core colour-contrast violations.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const require = createRequire('C:/dev/jarvis-hub/frontend/package.json');
const { chromium } = require('@playwright/test');

const argv = process.argv.slice(2);
if (argv.length < 2) {
  console.error('usage: node shoot.mjs <file-or-url> <out.png> [--w N] [--h N] [--scheme dark|light] [--full] [--wait ms] [--dpr N] [--selector CSS] [--axe] [--hash #x]');
  process.exit(2);
}
const [target, out] = argv;
const opt = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i > -1 && argv[i + 1] !== undefined ? argv[i + 1] : fallback;
};
const flag = (name) => argv.includes(`--${name}`);

const width = Number(opt('w', 1920));
const height = Number(opt('h', 1080));
const scheme = opt('scheme', 'dark');
const wait = Number(opt('wait', 400));
const dpr = Number(opt('dpr', 1));
const selector = opt('selector', null);
const hash = opt('hash', '');

const query = opt('query', '');
const isUrl = /^https?:\/\//i.test(target);
const url = (isUrl ? target : pathToFileURL(path.resolve(target)).href) + (query ? `?${query}` : '') + hash;
const allowed = (u) =>
  u.startsWith('file:') || u.startsWith('data:') || u.startsWith('blob:') || u.startsWith('about:') ||
  /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$)/i.test(u);

const report = { url, width, height, scheme, out: path.resolve(out), consoleErrors: [], pageErrors: [], blockedExternal: [] };

// The bundled Playwright expects a browser build that is not downloaded on this machine;
// nothing is fetched here — use a browser that is already installed.
async function launchInstalled() {
  const local = process.env.LOCALAPPDATA || '';
  const attempts = [
    { name: 'cached-headless-shell', opts: { executablePath: path.join(local, 'ms-playwright', 'chromium_headless_shell-1228', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe') } },
    { name: 'cached-chromium', opts: { executablePath: path.join(local, 'ms-playwright', 'chromium-1228', 'chrome-win64', 'chrome.exe') } },
    { name: 'msedge', opts: { channel: 'msedge' } },
    { name: 'chrome', opts: { channel: 'chrome' } },
  ];
  const errors = [];
  for (const a of attempts) {
    if (a.opts.executablePath && !fs.existsSync(a.opts.executablePath)) continue;
    try {
      const b = await chromium.launch({ headless: true, ...a.opts });
      report.browser = a.name;
      return b;
    } catch (e) {
      errors.push(`${a.name}: ${String(e).split('\n')[0].slice(0, 160)}`);
    }
  }
  throw new Error('no installed browser could be launched: ' + errors.join(' | '));
}

const browser = await launchInstalled();
try {
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: dpr,
    colorScheme: scheme === 'light' ? 'light' : 'dark',
    reducedMotion: 'reduce',
  });
  // --ls key=value (repeatable): seed localStorage before the page's own scripts run.
  const seeds = [];
  argv.forEach((a, i) => {
    if (a === '--ls' && argv[i + 1]) {
      const eq = argv[i + 1].indexOf('=');
      if (eq > 0) seeds.push([argv[i + 1].slice(0, eq), argv[i + 1].slice(eq + 1)]);
    }
  });
  if (seeds.length) {
    await context.addInitScript((pairs) => {
      try { for (const [k, v] of pairs) window.localStorage.setItem(k, v); } catch (_) { /* file: origins may refuse */ }
    }, seeds);
  }
  const page = await context.newPage();
  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (allowed(u)) return route.continue();
    report.blockedExternal.push(u);
    return route.abort();
  });
  page.on('console', (m) => { if (m.type() === 'error') report.consoleErrors.push(m.text().slice(0, 300)); });
  page.on('pageerror', (e) => report.pageErrors.push(String(e).slice(0, 300)));

  await page.goto(url, { waitUntil: 'load', timeout: 45000 });
  await page.evaluate(() => (document.fonts && document.fonts.ready) || null).catch(() => {});
  await page.waitForTimeout(wait);

  // --eval "js": run a snippet in the page after load (inspection aid, e.g. flip a data-attribute).
  const snippet = opt('eval', null);
  if (snippet) {
    await page.evaluate((code) => { new Function(code)(); }, snippet).catch((e) => report.pageErrors.push('eval: ' + String(e).slice(0, 200)));
    await page.waitForTimeout(600);
  }

  report.metrics = await page.evaluate(() => {
    const de = document.documentElement;
    const fonts = new Set();
    for (const el of Array.from(document.querySelectorAll('body *')).slice(0, 4000)) {
      if (el.childNodes.length && Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim())) {
        fonts.add(getComputedStyle(el).fontFamily.split(',')[0].trim().replace(/["']/g, ''));
      }
    }
    let smallest = 99;
    let tiny = 0;
    let textNodes = 0;
    for (const el of Array.from(document.querySelectorAll('body *')).slice(0, 6000)) {
      const hasText = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!hasText) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none') continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const px = parseFloat(cs.fontSize);
      textNodes++;
      if (px < smallest) smallest = px;
      if (px < 11) tiny++;
    }
    // Is each first-choice family really rendering? (A missing system font falls back silently.)
    const generic = new Set(['serif', 'sans-serif', 'monospace', 'system-ui', 'ui-sans-serif', 'ui-serif', 'ui-monospace', 'ui-rounded', 'cursive', 'fantasy', 'math', 'emoji', 'inherit', 'initial']);
    const probe = document.createElement('canvas').getContext('2d');
    const sample = 'mmmmmmmmmmlliWW@#1234567890abcdefghijQg';
    const bases = ['monospace', 'serif', 'sans-serif'];
    const baseWidths = bases.map((b) => { probe.font = `72px ${b}`; return probe.measureText(sample).width; });
    const available = (family) => bases.some((b, i) => { probe.font = `72px "${family}", ${b}`; return probe.measureText(sample).width !== baseWidths[i]; });
    const fontsMissing = Array.from(fonts).filter((f) => f && !generic.has(f.toLowerCase()) && !available(f));
    return {
      fontsMissing,
      scrollWidth: de.scrollWidth,
      scrollHeight: de.scrollHeight,
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      horizontalOverflow: de.scrollWidth > window.innerWidth + 1,
      firstChoiceFontsRequested: Array.from(fonts),
      fontsActuallyLoaded: document.fonts ? Array.from(document.fonts).filter((f) => f.status === 'loaded').map((f) => `${f.family} ${f.weight}`) : [],
      textElements: textNodes,
      smallestFontPx: smallest === 99 ? null : smallest,
      textElementsUnder11px: tiny,
      title: document.title,
    };
  });

  if (flag('axe')) {
    try {
      const AxeBuilder = require('@axe-core/playwright').default;
      const res = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze();
      report.axeContrast = res.violations.flatMap((v) =>
        v.nodes.slice(0, 60).map((n) => ({
          target: String(n.target).slice(0, 120),
          summary: (n.any[0] && n.any[0].message ? n.any[0].message : n.failureSummary || '').slice(0, 220),
        })),
      );
      report.axeContrastCount = res.violations.reduce((a, v) => a + v.nodes.length, 0);
    } catch (e) {
      report.axeError = String(e).slice(0, 300);
    }
  }

  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  if (selector) {
    await page.locator(selector).first().screenshot({ path: out });
  } else {
    await page.screenshot({ path: out, fullPage: flag('full') });
  }
  report.ok = true;
} catch (e) {
  report.ok = false;
  report.error = String(e).slice(0, 600);
} finally {
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
process.exit(report.ok ? 0 : 1);
