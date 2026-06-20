// Runs the live WorldMonitor contract against the in-repo mock sidecar, so the
// LIVE code path (live config → McpClient fetch → provider → normalizers) is
// exercised in CI without a real WorldMonitor. This is a real gate: unlike a bare
// `test:live-contract` (which skips when nothing is on :3100), this asserts the
// contract actually passed against the mock.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { startMockWorldMonitor } from './_mock-worldmonitor.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const { server, url } = await startMockWorldMonitor();

const child = spawn(process.execPath, [join(here, 'live-contract.mjs')], {
  env: {
    ...process.env,
    JARVIS_SIGNAL_LAYER_MODE: 'live',
    WORLDMONITOR_BASE_URL: url,
    WORLDMONITOR_MCP_URL: `${url}/api/mcp`,
  },
});

let out = '';
child.stdout.on('data', (d) => { out += d; process.stdout.write(d); });
child.stderr.on('data', (d) => { out += d; process.stderr.write(d); });

child.on('close', (code) => {
  server.close();
  // The bare contract exits 0 even when it *skips*; require a real pass here.
  const passed = code === 0 && /"ok":\s*true/.test(out);
  if (!passed) {
    console.error('\nlive-contract-mock FAILED: contract did not pass against the mock sidecar.');
    process.exit(1);
  }
  console.log(JSON.stringify({ ok: true, suite: 'live-contract-mock', against: 'mock-worldmonitor' }, null, 2));
  process.exit(0);
});
