import { test, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchHistory,
  fetchHistoryResult,
  fetchTrack,
  openLiveSocket,
  type LiveHandlers,
} from "../api";

function okFetch() {
  return vi.fn(async () => ({
    ok: true,
    json: async () => ({ type: "FeatureCollection", features: [] }),
  }));
}

beforeEach(() => vi.stubGlobal("fetch", okFetch()));
afterEach(() => vi.unstubAllGlobals());

test("fetchHistory builds /history/:layer with floored t and a bbox", async () => {
  await fetchHistory("adsb", 1749200400.7, [55, 25, 58, 28]);
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/history/adsb");
  expect(url).toContain("t=1749200400"); // floored, no fractional seconds
  expect(url).toContain("bbox=55%2C25%2C58%2C28"); // comma-encoded w,s,e,n
});

test("fetchHistory omits bbox when not provided", async () => {
  await fetchHistory("ais", 1000);
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/history/ais");
  expect(url).not.toContain("bbox=");
});

test("fetchHistory requests minute LOD only when asked", async () => {
  await fetchHistory("adsb", 1000, undefined, "minute");
  let url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("lod=minute");

  vi.stubGlobal("fetch", okFetch());
  await fetchHistory("adsb", 1000, undefined, "raw");
  url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).not.toContain("lod=");
});

test("fetchHistory returns an empty FeatureCollection on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
  const fc = await fetchHistory("ew", 1);
  expect(fc).toEqual({ type: "FeatureCollection", features: [] });
});

test("fetchHistory returns an empty FeatureCollection when fetch throws", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => {
    throw new Error("network down");
  }));
  const fc = await fetchHistory("tle", 1);
  expect(fc.features).toEqual([]);
});

test("fetchTrack builds the /track URL with floored from/to and encoded id", async () => {
  await fetchTrack("ais", "636092297", 1000.9, 4600.2);
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/history/ais/636092297/track");
  expect(url).toContain("from=1000");
  expect(url).toContain("to=4600");
});

// --- fetchHistoryResult: distinguish empty vs error (finding #5) ----------------------------

test("fetchHistoryResult reports 'ok' when features are returned", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true,
    json: async () => ({ type: "FeatureCollection", features: [{ id: 1 }] }),
  })));
  const r = await fetchHistoryResult("adsb", 1);
  expect(r.outcome).toBe("ok");
  expect(r.data.features).toHaveLength(1);
});

test("fetchHistoryResult reports 'empty' for a valid response with no features", async () => {
  // okFetch() returns features: [] — a genuinely empty time slice, NOT a failure.
  const r = await fetchHistoryResult("adsb", 1);
  expect(r.outcome).toBe("empty");
  expect(r.data.features).toEqual([]);
});

test("fetchHistoryResult reports 'error' on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
  const r = await fetchHistoryResult("ew", 1);
  expect(r.outcome).toBe("error");
  expect(r.data.features).toEqual([]); // still no-throw, empty collection
});

test("fetchHistoryResult reports 'error' when fetch throws", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => {
    throw new Error("network down");
  }));
  const r = await fetchHistoryResult("tle", 1);
  expect(r.outcome).toBe("error");
});

test("fetchHistory still returns just the collection (back-compat)", async () => {
  const fc = await fetchHistory("ais", 1);
  expect(fc).toEqual({ type: "FeatureCollection", features: [] });
});

// --- openLiveSocket robustness (finding #2) -------------------------------------------------

class FakeWebSocket {
  static last: FakeWebSocket | null = null;
  static instances = 0;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWebSocket.last = this;
    FakeWebSocket.instances += 1;
  }
  close() {
    this.closed = true;
  }
}

function withFakeWs(fn: (Ws: typeof FakeWebSocket) => void) {
  FakeWebSocket.last = null;
  FakeWebSocket.instances = 0;
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  try {
    fn(FakeWebSocket);
  } finally {
    vi.unstubAllGlobals();
  }
}

function handlers(over: Partial<LiveHandlers> = {}): LiveHandlers {
  return { onSnapshot: vi.fn(), onDelta: vi.fn(), ...over };
}

test("a malformed frame is dropped instead of throwing out of the handler", () => {
  withFakeWs(() => {
    const h = handlers();
    openLiveSocket(["adsb"], h);
    const ws = FakeWebSocket.last!;
    expect(() => ws.onmessage!({ data: "}{ not json" })).not.toThrow();
    expect(h.onSnapshot).not.toHaveBeenCalled();
    expect(h.onDelta).not.toHaveBeenCalled();
    // a subsequent good frame still routes
    ws.onmessage!({ data: JSON.stringify({ type: "snapshot", layer: "adsb", data: {} }) });
    expect(h.onSnapshot).toHaveBeenCalledOnce();
  });
});

test("connection state transitions connecting → open, and open resets backoff", () => {
  withFakeWs(() => {
    const onConnectionChange = vi.fn();
    openLiveSocket(["adsb"], handlers({ onConnectionChange }));
    expect(onConnectionChange).toHaveBeenCalledWith("connecting");
    FakeWebSocket.last!.onopen!();
    expect(onConnectionChange).toHaveBeenCalledWith("open");
  });
});

test("onclose schedules a reconnect (new socket) with backoff", () => {
  vi.useFakeTimers();
  withFakeWs(() => {
    const onConnectionChange = vi.fn();
    openLiveSocket(["adsb"], handlers({ onConnectionChange }));
    expect(FakeWebSocket.instances).toBe(1);
    FakeWebSocket.last!.onclose!();
    expect(onConnectionChange).toHaveBeenCalledWith("reconnecting");
    vi.advanceTimersByTime(11_000); // past the capped backoff
    expect(FakeWebSocket.instances).toBe(2); // reconnected
  });
  vi.useRealTimers();
});

test("close() cancels the pending reconnect and reports 'closed'", () => {
  vi.useFakeTimers();
  withFakeWs(() => {
    const onConnectionChange = vi.fn();
    const socket = openLiveSocket(["adsb"], handlers({ onConnectionChange }));
    FakeWebSocket.last!.onclose!(); // schedule a reconnect
    socket.close();
    expect(onConnectionChange).toHaveBeenLastCalledWith("closed");
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toBe(1); // no reconnect after close
  });
  vi.useRealTimers();
});
