// Node >=22.6: node --experimental-strip-types frontend/scripts/generate-desktop-routes.mjs [--check]
import { readFileSync, writeFileSync } from 'node:fs';
import { HUD_MODES } from '../src/hud-modes.ts';
import { CONSOLE_PANELS } from '../src/console-routes.ts';

const canonical = [
  ...HUD_MODES.map(mode => '/v2/' + mode),
  '/v2/console',
  ...CONSOLE_PANELS.map(panel => '/v2/console/' + panel.id),
];
const routes = {
  main: ['/v2', '/v2/', ...canonical.flatMap(path => [path, path + '/'])],
  floating: ['/v2', '/v2/', '/v2/chat', '/v2/chat/'],
};
const file = new URL('../../desktop/src-tauri/hud-routes.json', import.meta.url);
const content = JSON.stringify(routes, null, 2) + '\n';
if (process.argv.includes('--check')) {
  if (readFileSync(file, 'utf8') !== content) {
    console.error('Native HUD routes are stale. Run frontend/scripts/generate-desktop-routes.mjs.');
    process.exitCode = 1;
  }
} else {
  writeFileSync(file, content);
}
