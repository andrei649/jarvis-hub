import Redis from "ioredis";
import { config } from "../config.js";

// Live-state cache connection (design doc §7). STEP 4 uses this for the live snapshot
// (`geo:*` sets, `live:*` hashes) and subscribes to `chan:*` for the WebSocket stream.
let client: Redis | null = null;

export function getRedis(): Redis {
  if (!client) {
    client = new Redis(config.redisUrl, { lazyConnect: true });
  }
  return client;
}

/**
 * Test seam: inject a (mock) Redis client, bypassing the real connection. Pass `null` to reset back
 * to the lazily-constructed real client. Only intended for unit tests of the WS/live path so they
 * can observe pub/sub subscriptions without a live Redis.
 */
export function setRedisForTesting(mock: Redis | null): void {
  client = mock;
}
