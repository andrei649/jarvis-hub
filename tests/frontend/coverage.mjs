// Frontend coverage runner.
//
// The HUD scripts run inside JSDOM, so they can't be instrumented by vitest's
// own v8/istanbul providers. Instead the harness instruments each static file
// with istanbul before injecting it (HUD_COVERAGE=1) and dumps per-window
// __coverage__ into .nyc_output. This script drives that run and turns the
// dumps into an nyc report + an SVG badge.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const rm = (p) => fs.rmSync(path.join(ROOT, p), { recursive: true, force: true });

function run(cmd, args, env = {}) {
  const res = spawnSync(cmd, args, {
    cwd: ROOT,
    stdio: 'inherit',
    env: { ...process.env, ...env },
    shell: process.platform === 'win32',
  });
  return res.status ?? 1;
}

// Fresh slate.
rm('.nyc_output');
rm('coverage');

// 1) Run the suite with instrumentation on.
const testStatus = run('npx', ['vitest', 'run', 'tests/frontend'], { HUD_COVERAGE: '1' });
if (testStatus !== 0) process.exit(testStatus);

// 2) Aggregate the .nyc_output dumps into reports.
run('npx', [
  'nyc', 'report',
  '--reporter=text-summary',
  '--reporter=text',
  '--reporter=html',
  '--reporter=json-summary',
  '--report-dir=coverage',
  '--temp-dir=.nyc_output',
]);

// 3) Emit a coverage badge SVG from the summary.
const summaryPath = path.join(ROOT, 'coverage', 'coverage-summary.json');
if (fs.existsSync(summaryPath)) {
  const pct = JSON.parse(fs.readFileSync(summaryPath, 'utf8')).total.lines.pct;
  const color = pct >= 80 ? '#4c1' : pct >= 60 ? '#97ca00' : pct >= 40 ? '#dfb317' : '#e05d44';
  const label = 'HUD coverage';
  const value = `${pct}%`;
  // Rough text widths for a shields-style badge.
  const lw = 6.5 * label.length + 10;
  const vw = 7 * value.length + 10;
  const w = lw + vw;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="20" role="img" aria-label="${label}: ${value}">
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
  <rect rx="3" width="${w}" height="20" fill="#555"/>
  <rect rx="3" x="${lw}" width="${vw}" height="20" fill="${color}"/>
  <rect rx="3" width="${w}" height="20" fill="url(#s)"/>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="${lw / 2}" y="14">${label}</text>
    <text x="${lw + vw / 2}" y="14">${value}</text>
  </g>
</svg>`;
  fs.writeFileSync(path.join(HERE, 'coverage-badge.svg'), svg);
  console.log(`\nHUD coverage badge updated: ${value} (lines)`);
}

// 4) Gate: fail the run (and CI) if line/statement coverage regresses below
//    the BUG-2 target. Functions/branches kept lower as they trail line cov.
const gate = run('npx', [
  'nyc', 'check-coverage',
  '--temp-dir=.nyc_output',
  '--lines=60',
  '--statements=60',
  '--functions=50',
  '--branches=50',
]);
process.exit(gate);
