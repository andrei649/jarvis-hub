// qa-render2.mjs — render HUD routes in chosen looks and schemes through the read-only preview
// server, measure each frame, and keep evidence a fixer can act on.
//
//   node qa-render2.mjs <out-dir> [--base http://127.0.0.1:4180] [--looks a,b] [--schemes dark,light]
//        [--routes r1,r2 | --routes-file file] [--axe] [--shots all|none|first]
//        [--w 1920 --h 1080 --dpr 1] [--wait 2200]
//
// Per frame (report.json): smallest visible font, visible text under 12px (count + samples),
// horizontal overflow, page errors, Classic colour leaks in a Nerva look (computed colours equal
// to HUD v2 literals: count + samples), white platform controls on a dark scheme, optional axe
// colour-contrast failures (count + samples). The look is chosen through the appearance cache
// in localStorage, the way an owner's choice is restored (the server document is untouched).
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs';

const require = createRequire('C:/dev/jarvis-hub/frontend/package.json');
const { chromium } = require('@playwright/test');

const args = process.argv.slice(2);
const out = path.resolve(args[0] || 'qa');
const opt = (n, d) => { const i = args.indexOf(`--${n}`); return i > -1 ? args[i + 1] : d; };
const flag = (n) => args.includes(`--${n}`);
const base = opt('base', 'http://127.0.0.1:4180');
const ALL_LOOKS = ['ledger', 'presence', 'briefing', 'workbench', 'threshold', 'console', 'atlas', 'obsidian', 'graphite'];
const CLASSIC = new Set(['obsidian', 'graphite']);
const looks = opt('looks', ALL_LOOKS.join(',')).split(',');
const schemes = opt('schemes', 'dark,light').split(',');
let routes = (opt('routes', '') || '').split(',').filter(Boolean);
const rf = opt('routes-file', '');
if (rf) routes = fs.readFileSync(rf, 'utf8').split(/[\s,]+/).filter((r) => r && !r.startsWith('{'));
if (!routes.length) routes = ['cockpit'];
const axe = flag('axe');
const shots = opt('shots', 'all');
const W = Number(opt('w', 1920)), H = Number(opt('h', 1080)), DPR = Number(opt('dpr', 1));
const WAIT = Number(opt('wait', 2200));
const FRAME = opt('frame', '');            // 'ledger' | 'classic' -> localStorage['hud.frame'] (Phase B switch)
const DEMO = flag('demo');                 // append ?demo=1 (seeded, labelled demo data)

const local = process.env.LOCALAPPDATA || '';
const exe = path.join(local, 'ms-playwright', 'chromium_headless_shell-1228', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe');
const browser = await chromium.launch(fs.existsSync(exe) ? { headless: true, executablePath: exe } : { headless: true, channel: 'msedge' });
const AxeBuilder = axe ? require('@axe-core/playwright').default : null;

const report = [];
fs.mkdirSync(out, { recursive: true });
for (const look of looks) {
  for (const scheme of schemes) {
    if (CLASSIC.has(look) && scheme === 'light') continue;
    const dir = path.join(out, `${look}-${scheme}`);
    fs.mkdirSync(dir, { recursive: true });
    const context = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: DPR, colorScheme: scheme, reducedMotion: 'reduce' });
    await context.addInitScript(([lk, sc, fr]) => {
      try {
        localStorage.setItem('hud.firstrun.dismissed', '1');
        localStorage.setItem('hud.seen', '1');
        localStorage.setItem('hud.appearance.v1:/', JSON.stringify({ version: 2, preferences: { look: lk, scheme: sc, accent: 'cyan', density: 'normal', motion: 'calm', font: 'theme', scanline: 'off', dotgrid: 'off', lang: 'en' } }));
        if (fr) localStorage.setItem('hud.frame', fr);
      } catch (_) { /* ignore */ }
    }, [look, scheme, FRAME]);
    let first = true;
    for (const route of routes) {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));
      page.on('console', (m) => { if (m.type() === 'error' && !/405|404|Method Not Allowed|sw-v2|Failed to load resource/.test(m.text())) errors.push(m.text().slice(0, 200)); });
      const url = `${base}/v2/${route}${DEMO ? (route.includes('?') ? '&' : '?') + 'demo=1' : ''}`;
      const entry = { look, scheme, route, url, ok: false };
      try {
        await page.goto(url, { waitUntil: 'load', timeout: 45000 });
        await page.evaluate(() => (document.fonts && document.fonts.ready) || null).catch(() => {});
        await page.waitForTimeout(WAIT);
        Object.assign(entry, await page.evaluate(({ nerva, dark }) => {
          const de = document.documentElement;
          const LEAKS = new Map([
            ['43,184,240', 'cyan #2bb8f0'], ['143,224,255', 'cyan-light #8fe0ff'], ['4,7,14', 'navy #04070e'], ['6,11,21', 'navy-2 #060b15'],
            ['65,245,155', 'green #41f59b'], ['255,194,77', 'amber #ffc24d'], ['255,90,82', 'red #ff5a52'], ['167,139,250', 'violet #a78bfa'],
            ['233,244,253', 'ink #e9f4fd'], ['10,22,38', 'surface rgba(10,22,38)'], ['13,27,46', 'surface-2 rgba(13,27,46)'],
          ]);
          const key = (c) => { const m = /rgba?\(([^)]+)\)/.exec(c || ''); if (!m) return null; const p = m[1].split(',').map((s) => s.trim()); if (p.length === 4 && Number(p[3]) === 0) return null; return p.slice(0, 3).map((v) => Math.round(Number(v))).join(','); };
          const label = (el) => {
            const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.');
            const tid = el.getAttribute('data-testid');
            return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}${tid ? `[data-testid=${tid}]` : ''}`;
          };
          const visible = (el, cs) => {
            if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.bottom >= 0 && r.top <= innerHeight * 3;
          };
          let smallest = 99, under12 = 0, texts = 0, leaks = 0, white = 0;
          const under12Samples = [], leakSamples = [], whiteSamples = [];
          for (const el of Array.from(document.querySelectorAll('body *')).slice(0, 12000)) {
            const cs = getComputedStyle(el);
            if (!visible(el, cs)) continue;
            const hasText = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
            if (hasText) {
              const px = parseFloat(cs.fontSize);
              texts++;
              if (px < smallest) smallest = px;
              if (px < 11.95) { under12++; if (under12Samples.length < 6) under12Samples.push(`${label(el)} ${px}px "${el.textContent.trim().slice(0, 40)}"`); }
            }
            if (nerva) {
              for (const prop of ['color', 'backgroundColor', 'borderTopColor', 'borderLeftColor']) {
                if (prop === 'color' && !hasText) continue;
                if (prop.startsWith('border') && !(parseFloat(cs[prop === 'borderTopColor' ? 'borderTopWidth' : 'borderLeftWidth']) > 0)) continue;
                const k = key(cs[prop]);
                if (k && LEAKS.has(k)) { leaks++; if (leakSamples.length < 8) leakSamples.push(`${label(el)} ${prop}=${LEAKS.get(k)}${hasText ? ` "${el.textContent.trim().slice(0, 30)}"` : ''}`); }
              }
            }
            if (dark && /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(el.tagName)) {
              const k = key(cs.backgroundColor);
              if (k === '255,255,255' || k === '239,239,239' || k === '240,240,240') { white++; if (whiteSamples.length < 6) whiteSamples.push(label(el)); }
            }
          }
          return {
            htmlLook: de.getAttribute('data-look'), htmlScheme: de.getAttribute('data-scheme'),
            bg: getComputedStyle(document.body).backgroundColor,
            texts, smallest: smallest === 99 ? null : Math.round(smallest * 10) / 10, under12, under12Samples,
            classicLeaks: leaks, leakSamples, whiteControls: white, whiteSamples,
            hOverflow: de.scrollWidth > innerWidth + 1, title: document.title,
          };
        }, { nerva: !CLASSIC.has(look), dark: scheme === 'dark' }));
        if (AxeBuilder) {
          try {
            const res = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze();
            entry.contrastFails = res.violations.reduce((a, v) => a + v.nodes.length, 0);
            entry.contrastSamples = res.violations.flatMap((v) => v.nodes.slice(0, 8).map((n) => `${String(n.target).slice(0, 90)} :: ${(n.any[0] && n.any[0].message || '').slice(0, 150)}`)).slice(0, 8);
          } catch (e) { entry.axeError = String(e).slice(0, 160); }
        }
        if (shots === 'all' || (shots === 'first' && first)) {
          const file = path.join(dir, `${route.replace(/\//g, '__')}.jpg`);
          await page.screenshot({ path: file, type: 'jpeg', quality: 80, scale: 'css' });
          entry.file = file;
        }
        entry.ok = true;
        first = false;
      } catch (e) {
        entry.error = String(e).slice(0, 300);
      }
      entry.errors = errors;
      report.push(entry);
      console.log(`${entry.ok ? 'OK ' : 'ERR'} ${look}-${scheme} ${route.padEnd(30)} html=${entry.htmlLook}/${entry.htmlScheme} smallest=${entry.smallest} <12=${entry.under12} leaks=${entry.classicLeaks ?? '-'} white=${entry.whiteControls ?? '-'} hOverflow=${entry.hOverflow ? 'YES' : 'no'}${entry.contrastFails !== undefined ? ` contrast=${entry.contrastFails}` : ''}${errors.length ? ` errors=${errors.length}` : ''}`);
      await page.close();
    }
    await context.close();
  }
}
await browser.close();
fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
console.log(`report: ${path.join(out, 'report.json')} (${report.length} frames)`);
