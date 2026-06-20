// Tests for /watchlist robustness: de-dupe, size cap, and request-body cap.
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { loadConfig } from '../src/config.mjs';
import { createProvider } from '../src/providers/index.mjs';
import { createServer } from '../src/server.mjs';

async function withServer(fn) {
  const config = loadConfig({ JARVIS_SIGNAL_LAYER_MODE: 'replay', SIGNAL_LAYER_PORT: '0' });
  const server = createServer({ config, provider: createProvider(config) });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  try { await fn(base); } finally { server.close(); }
}

const post = (base, body, raw) => fetch(`${base}/watchlist`, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: raw ?? JSON.stringify(body),
});
const count = async (base) => (await (await fetch(`${base}/watchlist`)).json()).watchlist.length;

await withServer(async (base) => {
  // De-dupe: posting the same target id twice does not grow the list.
  const before = await count(base);
  const r1 = await post(base, { type: 'country', value: 'FR', label: 'France' });
  assert.equal(r1.status, 201, 'first add → 201');
  const afterFirst = await count(base);
  assert.equal(afterFirst, before + 1, 'new target appended once');

  const r2 = await post(base, { type: 'country', value: 'FR', label: 'France (updated)' });
  assert.equal(r2.status, 200, 'duplicate id → 200 update, not 201');
  assert.equal(await count(base), afterFirst, 'duplicate does not grow the list');

  // Invalid target → 400.
  assert.equal((await post(base, { value: 'no-type' })).status, 400, 'missing type → 400');

  // Oversized body → 413.
  const huge = '{"type":"topic","value":"' + 'x'.repeat(70 * 1024) + '"}';
  assert.equal((await post(base, null, huge)).status, 413, 'oversized body → 413');
});

// Size cap: filling past MAX_WATCHLIST (200) returns 409.
await withServer(async (base) => {
  let lastStatus = 201;
  for (let i = 0; i < 400; i++) {
    const r = await post(base, { type: 'topic', value: `t${i}` });
    lastStatus = r.status;
    if (r.status === 409) break;
  }
  assert.equal(lastStatus, 409, 'watchlist eventually rejects with 409 when full');
  assert.ok((await count(base)) <= 200, 'watchlist stays bounded at the cap');
});

console.log(JSON.stringify({ ok: true, suite: 'watchlist', checks: ['dedupe', 'validate', 'body-cap', 'size-cap'] }, null, 2));
