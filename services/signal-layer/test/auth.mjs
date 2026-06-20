// Server hardening tests: local-only bind default, bearer-token gate, scoped CORS.
// Boots the real HTTP server in replay mode on an ephemeral port.
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { loadConfig } from '../src/config.mjs';
import { createProvider } from '../src/providers/index.mjs';
import { createServer } from '../src/server.mjs';

async function withServer(env, fn) {
  const config = loadConfig({ JARVIS_SIGNAL_LAYER_MODE: 'replay', SIGNAL_LAYER_PORT: '0', ...env });
  const server = createServer({ config, provider: createProvider(config) });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    await fn(base);
  } finally {
    server.close();
  }
}

// Default config binds local-only.
assert.equal(loadConfig({}).host, '127.0.0.1', 'default bind must be 127.0.0.1');

// --- No token configured: requests pass; CORS is scoped, never `*`. ---
await withServer({}, async (base) => {
  assert.equal((await fetch(`${base}/healthz`)).status, 200);
  assert.equal((await fetch(`${base}/briefs/world`)).status, 200);

  const local = await fetch(`${base}/signals`, { headers: { origin: 'http://127.0.0.1:8080' } });
  assert.equal(local.headers.get('access-control-allow-origin'), 'http://127.0.0.1:8080', 'local origin reflected');

  const evil = await fetch(`${base}/signals`, { headers: { origin: 'http://evil.example' } });
  assert.equal(evil.headers.get('access-control-allow-origin'), null, 'foreign origin must not be allowed');
  assert.notEqual(evil.headers.get('access-control-allow-origin'), '*', 'never wildcard CORS');
});

// --- Token configured: gate everything except GET /healthz. ---
await withServer({ SIGNAL_LAYER_API_TOKEN: 's3cret' }, async (base) => {
  assert.equal((await fetch(`${base}/healthz`)).status, 200, 'healthz stays open');
  assert.equal((await fetch(`${base}/briefs/world`)).status, 401, 'no token → 401');
  assert.equal((await fetch(`${base}/briefs/world`, { headers: { authorization: 'Bearer wrong' } })).status, 401, 'wrong token → 401');
  assert.equal((await fetch(`${base}/briefs/world`, { headers: { authorization: 'Bearer s3cret' } })).status, 200, 'right token → 200');
  const post = await fetch(`${base}/ask/world`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question: 'x' })
  });
  assert.equal(post.status, 401, 'POST without token → 401');
});

console.log(JSON.stringify({ ok: true, suite: 'auth', checks: ['bind-local', 'cors-scoped', 'token-gate'] }, null, 2));
