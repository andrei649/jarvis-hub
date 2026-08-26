import type { LayerId } from "./layers";
import { apiUrl, wsUrl } from "./env";
import { emptyCollection, type BBox, type Lod, type FeatureCollection } from "./types";


/**
 * Outcome of a no-throw fetch, so callers can tell a genuinely empty time slice apart from a
 * backend 500 / network drop (both still resolve to an empty FeatureCollection): "ok" = features
 * returned, "empty" = a valid 2xx response with no features, "error" = non-2xx or thrown fetch.
 */
export type FetchOutcome = "ok" | "empty" | "error";

/** A fetched FeatureCollection paired with the outcome that produced it. */
export interface FetchResult {
  data: FeatureCollection;
  outcome: FetchOutcome;
}

function classify(fc: FeatureCollection): FetchOutcome {
  return fc.features.length > 0 ? "ok" : "empty";
}

/** REST: as-of-T reconstruction for one layer (design doc §8.2). Never throws. */
export async function fetchHistory(
  layer: LayerId,
  t: number,
  bbox?: BBox,
  lod: Lod = "raw",
): Promise<FeatureCollection> {
  return (await fetchHistoryResult(layer, t, bbox, lod)).data;
}

/**
 * Same as fetchHistory but also reports the {@link FetchOutcome}, so the store can surface a
 * per-layer status (empty vs error) without losing the no-throw, never-crash-the-globe contract.
 */
export async function fetchHistoryResult(
  layer: LayerId,
  t: number,
  bbox?: BBox,
  lod: Lod = "raw",
): Promise<FetchResult> {
  const url = new URL(`${apiUrl()}/history/${layer}`);
  url.searchParams.set("t", String(Math.floor(t)));
  if (bbox) url.searchParams.set("bbox", bbox.join(","));
  if (lod === "minute") url.searchParams.set("lod", "minute");
  try {
    const res = await fetch(url.toString());
    if (!res.ok) return { data: emptyCollection(), outcome: "error" };
    const data = (await res.json()) as FeatureCollection;
    return { data, outcome: classify(data) };
  } catch {
    // backend not up yet — render nothing, don't crash the globe, but flag the failure.
    return { data: emptyCollection(), outcome: "error" };
  }
}

/** REST: one entity's trail over [from, to] as a GeoJSON LineString FeatureCollection. */
export async function fetchTrack(
  layer: LayerId,
  id: string,
  from: number,
  to: number,
): Promise<FeatureCollection> {
  const url = new URL(`${apiUrl()}/history/${layer}/${encodeURIComponent(id)}/track`);
  url.searchParams.set("from", String(Math.floor(from)));
  url.searchParams.set("to", String(Math.floor(to)));
  try {
    const res = await fetch(url.toString());
    if (!res.ok) return emptyCollection();
    return (await res.json()) as FeatureCollection;
  } catch {
    return emptyCollection();
  }
}

/** Live WebSocket connection state, mirrored from the store's LiveConnectionState. */
export type LiveConnectionState = "connecting" | "open" | "reconnecting" | "closed";

export interface LiveHandlers {
  onSnapshot: (layer: LayerId, data: FeatureCollection) => void;
  onDelta: (layer: LayerId, envelope: Record<string, unknown>) => void;
  /** Connection-state changes, so the UI can show whether the live feed is healthy. */
  onConnectionChange?: (state: LiveConnectionState) => void;
}

/** A live socket handle: call close() to tear down the socket AND cancel any pending reconnect. */
export interface LiveSocket {
  close: () => void;
}

// Capped exponential backoff: 500ms, 1s, 2s, 4s, 8s, then hold at 10s. Jittered to avoid a
// thundering-herd reconnect when the backend bounces.
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10_000;

/**
 * WebSocket: snapshot per layer on connect, then deltas on chan:<layer>. Resilient to the backend
 * dropping: onerror/onclose trigger a capped exponential-backoff reconnect, and a bad frame is
 * dropped (its JSON.parse is guarded) rather than throwing out of the message handler. Connection
 * state is surfaced via onConnectionChange so the UI can show a "reconnecting"/"closed" indicator.
 */
export function openLiveSocket(layers: LayerId[], handlers: LiveHandlers): LiveSocket {
  let ws: WebSocket | null = null;
  let attempts = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false; // caller-requested teardown; suppresses reconnect

  const setState = (state: LiveConnectionState) => handlers.onConnectionChange?.(state);

  const scheduleReconnect = () => {
    if (closed || reconnectTimer != null) return;
    setState("reconnecting");
    const backoff = Math.min(RECONNECT_BASE_MS * 2 ** attempts, RECONNECT_MAX_MS);
    const delay = backoff / 2 + Math.random() * (backoff / 2); // jitter in [backoff/2, backoff]
    attempts += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  const connect = () => {
    if (closed) return;
    setState(attempts === 0 ? "connecting" : "reconnecting");
    ws = new WebSocket(`${wsUrl()}?layers=${layers.join(",")}`);

    ws.onopen = () => {
      attempts = 0; // reset backoff on a healthy connection
      setState("open");
    };

    ws.onmessage = (event) => {
      let msg: {
        type: "snapshot" | "delta";
        layer: LayerId;
        data: FeatureCollection | Record<string, unknown>;
      };
      try {
        msg = JSON.parse(event.data as string);
      } catch {
        return; // drop a malformed frame instead of throwing out of the handler
      }
      if (msg.type === "snapshot") {
        handlers.onSnapshot(msg.layer, msg.data as FeatureCollection);
      } else {
        handlers.onDelta(msg.layer, msg.data as Record<string, unknown>);
      }
    };

    // onerror generally fires just before onclose; let onclose own the reconnect so we don't
    // schedule twice.
    ws.onerror = () => {
      if (!closed) setState("reconnecting");
    };

    ws.onclose = () => {
      if (!closed) scheduleReconnect();
    };
  };

  connect();

  return {
    close: () => {
      closed = true;
      if (reconnectTimer != null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      setState("closed");
      ws?.close();
    },
  };
}
