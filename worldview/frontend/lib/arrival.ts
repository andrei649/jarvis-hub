// Arrival deep links (spec §5.1): landing in WorldView from a JARVIS/Argus digest alert (or a
// shared replay link). URL contract, extending the replay-link params (lib/export.ts):
//
//   ?from&to                       — replay window (UNIX seconds; required)
//   &layer=ais&id=244660000        — entity to pre-select (Inspector + trail)
//   &lon=56.4&lat=26.3&zoom=8      — camera pre-position (FlyTo on load)
//   &agent=argus                   — the referring agent; its presence makes this an ARRIVAL
//                                    (banner + REPLAY-from-first-frame), not just a window restore
//
// A plain ?from&to link restores the window silently (reproducible replay, H19.2.7); the
// banner appears only when the link declares an agent or an entity — we never invent an
// arrival story for an ordinary share.

import { decodeReplayWindow, type ReplayWindow } from "./export";
import { isLayer } from "./layers";
import type { SelectedEntity, FlyToTarget } from "./store/useTimelineStore";

export interface ParsedArrival {
  window: ReplayWindow;
  entity: SelectedEntity | null;
  view: FlyToTarget | null;
  agent: string | null;
  /** True when this link is an arrival (agent/entity present), not a bare window restore. */
  isArrival: boolean;
}

export function parseArrival(query: string): ParsedArrival | null {
  const win = decodeReplayWindow(query);
  if (!win) return null;
  const params = new URLSearchParams(query.startsWith("?") ? query.slice(1) : query);

  const layerRaw = params.get("layer");
  const idRaw = params.get("id");
  const entity: SelectedEntity | null =
    layerRaw && idRaw && isLayer(layerRaw) ? { layer: layerRaw, id: idRaw } : null;

  // Number(null) is 0 — an absent param must stay NaN, not become a (0,0) camera target.
  const numParam = (name: string): number => {
    const raw = params.get(name);
    return raw == null || raw === "" ? NaN : Number(raw);
  };
  const lon = numParam("lon");
  const lat = numParam("lat");
  const zoom = numParam("zoom");
  const view: FlyToTarget | null =
    Number.isFinite(lon) && Number.isFinite(lat)
      ? { longitude: lon, latitude: lat, zoom: Number.isFinite(zoom) ? zoom : 8 }
      : null;

  const agentRaw = params.get("agent");
  const agent = agentRaw ? agentRaw.toUpperCase().slice(0, 24) : null;

  return { window: win, entity, view, agent, isArrival: agent != null || entity != null };
}
