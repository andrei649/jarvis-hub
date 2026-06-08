// WS subscription planning (ticket H19.5.2). Pure helper that maps a connecting client's requested
// layers + optional viewport bbox to the concrete set of Redis pub/sub channels it should subscribe
// to. Keeping this pure makes the viewport→channel mapping unit-testable without a live socket.

import type { BBox, Layer } from "../types.js";
import { channel } from "../repositories/live.js";
import { geoChannel, viewportCells } from "./geohash.js";

export interface SubscriptionPlan {
  channels: string[];
  // "geo": viewport-scoped per-cell channels (client filters by layer + bbox locally).
  // "global": per-layer global channels (no bbox, or the cover was too large → back-compat path).
  mode: "geo" | "global";
}

/**
 * Decide which channels a client subscribes to.
 *
 * - No bbox, or precision<=0, or the viewport cover would exceed the cell cap → GLOBAL mode:
 *   subscribe to `chan:<layer>` for each requested layer (the pre-H19.5.2 behavior, back-compat).
 * - Otherwise → GEO mode: subscribe only to the `live:geo:<cell>` channels covering the bbox, so the
 *   client never receives deltas for entities outside its viewport.
 */
export function planSubscription(
  layers: Layer[],
  bbox: BBox | null,
  precision: number,
): SubscriptionPlan {
  if (!bbox || precision <= 0) {
    return { channels: layers.map(channel), mode: "global" };
  }
  const cover = viewportCells(bbox, precision);
  if (!cover.bounded || cover.cells.length === 0) {
    // Viewport too large to enumerate (or degenerate) → fall back to global channels.
    return { channels: layers.map(channel), mode: "global" };
  }
  return { channels: cover.cells.map(geoChannel), mode: "geo" };
}
