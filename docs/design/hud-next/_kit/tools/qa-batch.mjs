// qa-batch.mjs — run several qa-render2.mjs jobs at once and report when all finish.
//   node qa-batch.mjs <out-root>
import { spawn } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';

const root = path.resolve(process.argv[2] || 'qa-run');
const tool = path.join(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), 'qa-render2.mjs');
const allRoutes = path.join(path.dirname(tool), '..', 'all-routes.txt');
const KEY = 'cockpit,chat,projects,agents,trust,memory,autonomy,build,observe,interop,comms,admin,finance,health,knowledge,family,jobs,console,console/appearance,console/settings,console/decision-inbox,console/integrations';
const OWNER = 'cockpit,chat,trust,console/appearance,console/decision-inbox,admin';

const jobs = [
  // the visual set: every look and scheme on the key routes, with axe
  { name: 'vis-ledger', args: ['vis', '--looks', 'ledger', '--routes', KEY, '--axe'] },
  { name: 'vis-presence-briefing', args: ['vis', '--looks', 'presence,briefing', '--routes', KEY, '--axe'] },
  { name: 'vis-workbench-threshold', args: ['vis', '--looks', 'workbench,threshold', '--routes', KEY, '--axe'] },
  { name: 'vis-console-atlas', args: ['vis', '--looks', 'console,atlas', '--routes', KEY, '--axe'] },
  { name: 'vis-classic', args: ['vis', '--looks', 'obsidian,graphite', '--schemes', 'dark', '--routes', KEY, '--axe'] },
  // the sweep: every route in Ledger dark, Ledger light and Obsidian, metrics only
  { name: 'sweep-ledger-dark', args: ['sweep', '--looks', 'ledger', '--schemes', 'dark', '--routes-file', allRoutes, '--axe', '--shots', 'none', '--wait', '1800'] },
  { name: 'sweep-ledger-light', args: ['sweep', '--looks', 'ledger', '--schemes', 'light', '--routes-file', allRoutes, '--axe', '--shots', 'none', '--wait', '1800'] },
  { name: 'sweep-obsidian', args: ['sweep', '--looks', 'obsidian', '--schemes', 'dark', '--routes-file', allRoutes, '--shots', 'none', '--wait', '1800'] },
  // the owner's display
  { name: 'owner-2560', args: ['owner', '--looks', 'ledger', '--routes', OWNER, '--w', '2560', '--h', '1353', '--dpr', '1.5'] },
];

fs.mkdirSync(root, { recursive: true });
const started = Date.now();
await Promise.all(jobs.map((job) => new Promise((resolve) => {
  const [sub, ...rest] = job.args;
  const out = path.join(root, job.name);
  const log = fs.createWriteStream(path.join(root, `${job.name}.log`));
  const child = spawn(process.execPath, [tool, out, ...rest], { stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.pipe(log);
  child.stderr.pipe(log);
  child.on('close', (code) => {
    console.log(`${job.name}: exit ${code} after ${Math.round((Date.now() - started) / 1000)}s`);
    resolve();
  });
})));
console.log(`all ${jobs.length} jobs done in ${Math.round((Date.now() - started) / 1000)}s; output under ${root}`);
