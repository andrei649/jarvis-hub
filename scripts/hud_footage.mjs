#!/usr/bin/env node
/* Marketing footage capture for the HUD v2 (T-0.52).
 *
 * Runs `frontend/e2e/footage.spec.ts` through Playwright's `footage` project and
 * leaves one .webm per shot in `frontend/e2e/artifacts/footage/`, plus a
 * `manifest.json` describing what was filmed, from which source, and when.
 *
 * Everything about WHAT is filmed lives in the spec — the shot list, the palette
 * navigation, and the honesty assertions that make `--source demo` show its banner
 * and `--source live` prove it isn't secretly demo. This file is the thin part: it
 * sets FOOTAGE=1 (without which the `footage` project does not exist at all),
 * forwards the two knobs, and turns the per-shot sidecars into one manifest a human
 * or a producer can read. See docs/marketing/FOOTAGE_RUNBOOK.md.
 *
 *   node scripts/hud_footage.mjs                     # real data, 6s per shot
 *   node scripts/hud_footage.mjs --source demo       # seeded corpus, banner in frame
 *   node scripts/hud_footage.mjs --seconds 12        # longer takes
 *   node scripts/hud_footage.mjs --shot trust-center # just one
 *
 * The backend is booted by Playwright's own webServer (serve.py on E2E_PORT), so
 * this needs no running hub — but it does need the v2 bundle built into
 * agents/web/v2/, because that is the thing being filmed.
 */
import { spawnSync } from 'node:child_process';
import { readdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const FRONTEND = join(REPO, 'frontend');
const OUT = join(FRONTEND, 'e2e', 'artifacts', 'footage');

const SOURCES = ['live', 'demo'];

function parseArgs(argv) {
  const out = { source: 'live', seconds: null, shot: null, help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--source') out.source = String(argv[++i] ?? '');
    else if (a === '--seconds') out.seconds = String(argv[++i] ?? '');
    else if (a === '--shot') out.shot = String(argv[++i] ?? '');
    else { console.error(`unknown argument: ${a}`); process.exit(2); }
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
  console.log(readFileSync(fileURLToPath(import.meta.url), 'utf8')
    .split('\n').filter((l) => l.startsWith(' *') || l.startsWith('/*'))
    .map((l) => l.replace(/^\/?\s?\*\/?/, '')).join('\n').trim());
  process.exit(0);
}

if (!SOURCES.includes(args.source)) {
  // Same closed set the spec enforces; caught here too so the failure arrives in one
  // second instead of after a backend boot.
  console.error(`--source must be one of ${SOURCES.join(' | ')} — got "${args.source}".`);
  console.error('TEASER_PACK.md §6: "never stage fake data for a shot. Demo mode is clearly');
  console.error('badged; use it, or use real data." There is no third source.');
  process.exit(2);
}
if (args.seconds !== null && !(Number(args.seconds) >= 1)) {
  console.error(`--seconds must be a number >= 1 — got "${args.seconds}".`);
  process.exit(2);
}

// The bundle is what gets filmed. Fail with the fix rather than recording six clips
// of the "HUD v2 not built" page, which would look plausible in a file listing.
const BUNDLE = join(REPO, 'agents', 'web', 'v2', 'index.html');
if (!existsSync(BUNDLE)) {
  console.error(`the v2 bundle is missing (${BUNDLE}) — there is nothing to film.`);
  console.error('build it first:  cd frontend && npm ci && npm run build');
  process.exit(1);
}

const env = { ...process.env, FOOTAGE: '1', FOOTAGE_SOURCE: args.source };
if (args.seconds !== null) env.FOOTAGE_SECONDS = args.seconds;

const cmd = ['playwright', 'test', '--project=footage'];
if (args.shot) cmd.push('-g', args.shot);

console.log(`▶ footage · source=${args.source}${args.seconds ? ` seconds=${args.seconds}` : ''}`
  + `${args.shot ? ` shot=${args.shot}` : ''}`);

const run = spawnSync('npx', cmd, { cwd: FRONTEND, env, stdio: 'inherit' });
if (run.error) {
  console.error(`could not launch Playwright: ${run.error.message}`);
  process.exit(1);
}

/* Collect whatever actually landed. This runs even on a non-zero exit: a run where
   four shots recorded and one failed should still leave a manifest describing the
   four, and the exit code below still reports the failure. A manifest that quietly
   claimed six would be worse than none. */
const shots = [];
if (existsSync(OUT)) {
  for (const f of readdirSync(OUT).sort()) {
    if (!f.endsWith('.json') || f === 'manifest.json') continue;
    try { shots.push(JSON.parse(readFileSync(join(OUT, f), 'utf8'))); }
    catch (e) { console.error(`skipping unreadable sidecar ${f}: ${e.message}`); }
  }
}

if (shots.length) {
  writeFileSync(join(OUT, 'manifest.json'), JSON.stringify({
    // Not a repo artifact: e2e/artifacts/ is gitignored, so this stamp records when a
    // particular producer's clips were made, for their own bookkeeping.
    captured_at: new Date().toISOString(),
    source: args.source,
    exit_code: run.status,
    shots,
  }, null, 2) + '\n');
  console.log(`\n${shots.length} clip(s) in ${OUT}`);
  for (const s of shots) {
    console.log(`  ${s.id.padEnd(20)} ${String(Math.round(s.bytes / 1024)).padStart(6)} KB  ${s.title}`);
  }
  console.log('\nReuse rule (TEASER_PACK.md §6): never stage fake data for a shot.');
  console.log(args.source === 'demo'
    ? 'These are DEMO clips — keep the amber "DEMO DATA" banner in frame when you cut.'
    : 'These are LIVE clips — they show this machine\'s real state, empty surfaces included.');
} else {
  console.error('\nno clips were produced.');
}

process.exit(run.status === null ? 1 : run.status);
