import type { LayerId } from "./layers";
import { emptyCollection, type BBox, type FeatureCollection } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:4000";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:4000/live";

/** REST: as-of-T reconstruction for one layer (design doc §8.2). */
export async function fetchHistory(
  layer: LayerId,
  t: number,
  bbox?: BBox,
): Promise<FeatureCollection> {
  const url = new URL(`${API_URL}/history/${layer}`);
  url.searchParams.set("t", String(Math.floor(t)));
  if (bbox) url.searchParams.set("bbox", bbox.join(","));
  try {
    const res = await fetch(url.toString());
    if (!res.ok) return emptyCollection();
    return (await res.json()) as FeatureCollection;
  } catch {
    return emptyCollection(); // backend not up yet — render nothing, don't crash the globe
  }
}

/** REST: one entity's trail over [from, to] as a GeoJSON LineString FeatureCollection. */
export async function fetchTrack(
  layer: LayerId,
  id: string,
  from: number,
  to: number,
): Promise<FeatureCollection> {
  const url = new URL(`${API_URL}/history/${layer}/${encodeURIComponent(id)}/track`);
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

export interface LiveHandlers {
  onSnapshot: (layer: LayerId, data: FeatureCollection) => void;
  onDelta: (layer: LayerId, envelope: Record<string, unknown>) => void;
}

/** WebSocket: snapshot per layer on connect, then deltas on chan:<layer>. */
export function openLiveSocket(layers: LayerId[], handlers: LiveHandlers): WebSocket {
  const ws = new WebSocket(`${WS_URL}?layers=${layers.join(",")}`);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data as string) as {
      type: "snapshot" | "delta";
      layer: LayerId;
      data: FeatureCollection | Record<string, unknown>;
    };
    if (msg.type === "snapshot") {
      handlers.onSnapshot(msg.layer, msg.data as FeatureCollection);
    } else {
      handlers.onDelta(msg.layer, msg.data as Record<string, unknown>);
    }
  };
  return ws;
}
