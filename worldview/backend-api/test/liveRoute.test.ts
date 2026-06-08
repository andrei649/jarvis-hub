import test from "node:test";
import assert from "node:assert/strict";
import Fastify, { type FastifyInstance } from "fastify";
import websocket from "@fastify/websocket";
import { WebSocket } from "ws";
import type { AddressInfo } from "node:net";
import { liveRoutes } from "../src/routes/live.js";
import { setRedisForTesting } from "../src/plugins/redis.js";
import { channel } from "../src/repositories/live.js";
import { encodeGeohash, geoChannel, viewportCells } from "../src/live/geohash.js";

// Route-level test for the live WS endpoint (ticket H19.5.2). A mock Redis records what channels a
// connecting client subscribes to (the publish/coalesce paths are covered by the pure unit tests).
// We assert: a `?bbox=` client subscribes ONLY to the geohash cells covering its viewport, and a
// no-bbox client falls back to the global per-layer channels (back-compat).

interface MockSub {
  subscribed: string[];
  emit: (chan: string, payload: string) => void;
}

// A minimal mock of the ioredis surface the live route touches: duplicate() for the subscriber,
// subscribe()/on("message"), and the snapshot's scan/mget (return empty so snapshots are []).
function mockRedis() {
  const subscribers: MockSub[] = [];
  const makeSub = (): MockSub & {
    duplicate: () => unknown;
    subscribe: (...c: string[]) => Promise<void>;
    on: (ev: string, cb: (chan: string, payload: string) => void) => void;
    quit: () => Promise<void>;
    scan: () => Promise<[string, string[]]>;
    mget: () => Promise<string[]>;
  } => {
    let handler: ((chan: string, payload: string) => void) | null = null;
    const sub: MockSub & Record<string, unknown> = {
      subscribed: [],
      emit: (chan, payload) => handler?.(chan, payload),
    } as MockSub & Record<string, unknown>;
    Object.assign(sub, {
      duplicate: () => sub,
      subscribe: async (...c: string[]) => {
        sub.subscribed.push(...c);
      },
      on: (ev: string, cb: (chan: string, payload: string) => void) => {
        if (ev === "message") handler = cb;
      },
      quit: async () => {},
      scan: async () => ["0", []] as [string, string[]],
      mget: async () => [],
    });
    subscribers.push(sub);
    return sub as never;
  };
  return makeSub();
}

async function startApp(): Promise<{ app: FastifyInstance; url: string }> {
  const app = Fastify();
  await app.register(websocket);
  await app.register(liveRoutes);
  await app.listen({ port: 0, host: "127.0.0.1" });
  const { port } = app.server.address() as AddressInfo;
  return { app, url: `ws://127.0.0.1:${port}/live` };
}

function waitOpen(ws: WebSocket): Promise<void> {
  return new Promise((resolve, reject) => {
    ws.once("open", () => resolve());
    ws.once("error", reject);
  });
}

test("live route: a ?bbox= client subscribes only to the covering geohash cells", async () => {
  const redis = mockRedis();
  setRedisForTesting(redis as never);
  const { app, url } = await startApp();
  try {
    const bbox = { w: 13.0, s: 52.0, e: 13.001, n: 52.001 }; // tiny -> single cell
    const ws = new WebSocket(`${url}?layers=adsb&bbox=${bbox.w},${bbox.s},${bbox.e},${bbox.n}`);
    await waitOpen(ws);
    // Give the server a tick to run subscribe().
    await new Promise((r) => setTimeout(r, 30));

    const expectedCell = encodeGeohash(13.0005, 52.0005, 3);
    assert.deepEqual(redis.subscribed, [geoChannel(expectedCell)]);
    // No global channel leaked in.
    assert.ok(!redis.subscribed.includes(channel("adsb")));
    ws.close();
  } finally {
    await app.close();
    setRedisForTesting(null);
  }
});

test("live route: a no-bbox client subscribes to the global per-layer channels (back-compat)", async () => {
  const redis = mockRedis();
  setRedisForTesting(redis as never);
  const { app, url } = await startApp();
  try {
    const ws = new WebSocket(`${url}?layers=adsb,ais`);
    await waitOpen(ws);
    await new Promise((r) => setTimeout(r, 30));
    assert.deepEqual(redis.subscribed.sort(), [channel("adsb"), channel("ais")].sort());
    ws.close();
  } finally {
    await app.close();
    setRedisForTesting(null);
  }
});

test("live route: a delta on a subscribed cell is forwarded to the bbox client", async () => {
  const redis = mockRedis();
  setRedisForTesting(redis as never);
  const { app, url } = await startApp();
  try {
    const bbox = { w: 13.0, s: 52.0, e: 13.5, n: 52.5 };
    const ws = new WebSocket(`${url}?layers=adsb&bbox=${bbox.w},${bbox.s},${bbox.e},${bbox.n}`);
    await waitOpen(ws);
    await new Promise((r) => setTimeout(r, 30));

    const deltas: unknown[] = [];
    ws.on("message", (raw) => {
      const msg = JSON.parse(raw.toString());
      if (msg.type === "delta") deltas.push(msg);
    });

    const lon = 13.2;
    const lat = 52.2;
    const cell = encodeGeohash(lon, lat, 3);
    // Sanity: the cell is one we actually subscribed to.
    assert.ok(viewportCells(bbox, 3).cells.includes(cell));
    const env = { domain: "adsb", entity_id: "abc", ts: 1, lon, lat };
    redis.emit(geoChannel(cell), JSON.stringify(env));

    // Coalescer flushes on WS_COALESCE_MS (100ms default); wait past it.
    await new Promise((r) => setTimeout(r, 180));
    assert.equal(deltas.length, 1);
    assert.deepEqual(deltas[0], { type: "delta", layer: "adsb", data: env });
    ws.close();
  } finally {
    await app.close();
    setRedisForTesting(null);
  }
});

test("live route: a malformed pub/sub payload is ignored (poison-pill safe)", async () => {
  const redis = mockRedis();
  setRedisForTesting(redis as never);
  const { app, url } = await startApp();
  try {
    const ws = new WebSocket(`${url}?layers=adsb`);
    await waitOpen(ws);
    await new Promise((r) => setTimeout(r, 30));
    const deltas: unknown[] = [];
    ws.on("message", (raw) => {
      const msg = JSON.parse(raw.toString());
      if (msg.type === "delta") deltas.push(msg);
    });
    // Garbage on the channel must not crash the handler nor produce a delta.
    redis.emit(channel("adsb"), "{not json");
    await new Promise((r) => setTimeout(r, 180));
    assert.equal(deltas.length, 0);
    ws.close();
  } finally {
    await app.close();
    setRedisForTesting(null);
  }
});

test("live route: deltas for the same entity coalesce to one message per flush window", async () => {
  const redis = mockRedis();
  setRedisForTesting(redis as never);
  const { app, url } = await startApp();
  try {
    const ws = new WebSocket(`${url}?layers=adsb`);
    await waitOpen(ws);
    await new Promise((r) => setTimeout(r, 30));
    const deltas: { data: { ts: number } }[] = [];
    ws.on("message", (raw) => {
      const msg = JSON.parse(raw.toString());
      if (msg.type === "delta") deltas.push(msg);
    });
    // Three rapid updates for the same entity within one flush window -> one delivered (latest).
    for (let i = 1; i <= 3; i++) {
      redis.emit(channel("adsb"), JSON.stringify({ domain: "adsb", entity_id: "e1", ts: i, lon: 1, lat: 2 }));
    }
    await new Promise((r) => setTimeout(r, 180));
    assert.equal(deltas.length, 1);
    assert.equal(deltas[0]?.data.ts, 3); // latest value won
    ws.close();
  } finally {
    await app.close();
    setRedisForTesting(null);
  }
});
