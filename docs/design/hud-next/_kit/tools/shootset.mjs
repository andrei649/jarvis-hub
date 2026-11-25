// shootset.mjs — render the standard screenshot matrix for one design-direction folder.
//
//   node shootset.mjs <direction-folder> [--only cockpit|secondary|chat] [--quick]
//
// Expects <folder>/cockpit.html (required) and optionally secondary.html / chat.html.
// Pages must honour ?theme=dark|light (default dark). A page declares light support with
//   <meta name="nerva-themes" content="dark light">
// Output: <folder>/shots/<page>-<width>-<theme>.png and <folder>/shots/report.json
// --quick renders only the 1920 dark shot of each page (fast inner loop while iterating).
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const here = path.dirname(fileURLToPath(import.meta.url));
const shoot = path.join(here, 'shoot.mjs');
const argv = process.argv.slice(2);
if (!argv[0]) {
  console.error('usage: node shootset.mjs <direction-folder> [--only page] [--quick]');
  process.exit(2);
}
const dir = path.resolve(argv[0]);
const only = argv.includes('--only') ? argv[argv.indexOf('--only') + 1] : null;
const quick = argv.includes('--quick');

const pages = ['cockpit', 'secondary', 'chat'].filter((p) => fs.existsSync(path.join(dir, `${p}.html`)) && (!only || only === p));
if (!pages.length) {
  console.error(`no cockpit.html / secondary.html / chat.html found in ${dir}`);
  process.exit(2);
}

const results = [];
function run(page, w, h, theme, axe, dpr = 1) {
  const out = path.join(dir, 'shots', `${page}-${w}-${theme}.png`);
  const args = [shoot, path.join(dir, `${page}.html`), out, '--w', String(w), '--h', String(h), '--dpr', String(dpr), '--query', `theme=${theme}`, '--scheme', theme, '--wait', '500'];
  if (axe) args.push('--axe');
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  let rep;
  try { rep = JSON.parse(r.stdout); } catch { rep = { ok: false, error: (r.stderr || r.stdout || '').slice(0, 400) }; }
  const m = rep.metrics || {};
  results.push({
    page, width: w, height: h, theme, file: out, ok: !!rep.ok, error: rep.error || null,
    horizontalOverflow: !!m.horizontalOverflow,
    verticalOverflowPx: m.scrollHeight && m.innerHeight ? Math.max(0, m.scrollHeight - m.innerHeight) : null,
    textElements: m.textElements ?? null,
    smallestFontPx: m.smallestFontPx ?? null,
    textElementsUnder11px: m.textElementsUnder11px ?? null,
    fontsRequested: m.firstChoiceFontsRequested || [],
    fontsMissing: m.fontsMissing || [],
    fontsLoaded: m.fontsActuallyLoaded || [],
    blockedExternal: rep.blockedExternal || [],
    consoleErrors: (rep.consoleErrors || []).concat(rep.pageErrors || []),
    axeContrastCount: axe ? rep.axeContrastCount ?? null : undefined,
    axeContrastSamples: axe ? (rep.axeContrast || []).slice(0, 12) : undefined,
    axeError: rep.axeError || undefined,
  });
}

const noLight = [];
for (const page of pages) {
  const html = fs.readFileSync(path.join(dir, `${page}.html`), 'utf8');
  const hasLight = /<meta[^>]+name=["']nerva-themes["'][^>]+content=["'][^"']*light/i.test(html);
  run(page, 1920, 1080, 'dark', true);
  if (quick) continue;
  if (page === 'cockpit') {
    run(page, 1440, 900, 'dark', false);
    run(page, 1280, 800, 'dark', false);
    // The owner's real screen: a maximized browser on a 4K 31-inch monitor at 150% scale.
    run(page, 2560, 1353, 'dark', false, 1.5);
    if (hasLight) run(page, 2560, 1353, 'light', false, 1.5);
  }
  if (hasLight) run(page, 1920, 1080, 'light', true);
  else noLight.push(page);
}

fs.mkdirSync(path.join(dir, 'shots'), { recursive: true });
fs.writeFileSync(path.join(dir, 'shots', 'report.json'), JSON.stringify(results, null, 2));

const line = (r) =>
  `${r.ok ? 'OK ' : 'ERR'} ${r.page}@${r.width}${r.width === 2560 ? ' (owner screen 2560x1353 @1.5x)' : ''} ${r.theme.padEnd(5)} | text ${r.textElements} | smallest ${r.smallestFontPx}px | <11px ${r.textElementsUnder11px}` +
  ` | hOverflow ${r.horizontalOverflow ? 'YES' : 'no'} | vOverflow ${r.verticalOverflowPx}px` +
  (r.axeContrastCount !== undefined ? ` | contrast fails ${r.axeContrastCount}` : '') +
  (r.fontsMissing.length ? ` | FONTS NOT INSTALLED: ${r.fontsMissing.join(', ')}` : '') +
  (r.blockedExternal.length ? ` | EXTERNAL REQUESTS BLOCKED ${r.blockedExternal.length}` : '') +
  (r.consoleErrors.length ? ` | JS errors ${r.consoleErrors.length}` : '') +
  (r.error ? ` | ${r.error}` : '');
console.log(results.map(line).join('\n'));
console.log(`\nfonts requested: ${[...new Set(results.flatMap((r) => r.fontsRequested))].join(', ')}`);
if (noLight.length) console.log(`NO LIGHT THEME DECLARED on: ${noLight.join(', ')} (add <meta name="nerva-themes" content="dark light"> once light is designed)`);
const worst = results.filter((r) => r.axeContrastSamples && r.axeContrastSamples.length);
for (const r of worst) {
  console.log(`\ncontrast failures on ${r.page}@${r.width} ${r.theme} (first ${r.axeContrastSamples.length}):`);
  for (const s of r.axeContrastSamples) console.log(`  - ${s.target} :: ${s.summary}`);
}
console.log(`\nreport: ${path.join(dir, 'shots', 'report.json')}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
