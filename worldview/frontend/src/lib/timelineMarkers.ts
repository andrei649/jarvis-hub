// Timeline event markers (spec §4): alerts, recon passes and intel events pinned onto the 24h
// scrubber so history is navigable — hover names them, click scrubs to them. Pure + testable.

import type { LayerData } from "./layerData";
import { deriveAlerts } from "./alerts";
import type { ReconWindow } from "./recon";

export type MarkerKind = "alert" | "recon" | "intel";

export interface TimelineMarker {
  /** UNIX seconds. */
  t: number;
  kind: MarkerKind;
  label: string;
}

/**
 * Derive the marker set from the on-screen data: dark vessels and high-severity events are
 * red `alert` ticks, other context events are violet `intel`, recon-window ingresses are gold
 * `recon`. Markers without a usable timestamp are dropped.
 */
export function deriveTimelineMarkers(
  data: LayerData,
  recon: ReconWindow[],
  now: number,
): TimelineMarker[] {
  const markers: TimelineMarker[] = [];

  for (const alert of deriveAlerts(data, now)) {
    if (!(alert.ts > 0)) continue;
    markers.push({
      t: alert.ts,
      kind: alert.kind === "dark_vessel" || alert.severity === "high" ? "alert" : "intel",
      label: alert.label,
    });
  }

  for (const w of recon) {
    markers.push({
      t: w.t_ingress,
      kind: "recon",
      label: `${w.sensor_type.toUpperCase()} pass · NORAD ${w.norad_id} · ${w.aoi_id}`,
    });
  }

  return markers.sort((a, b) => a.t - b.t);
}

/**
 * Position of a timestamp within [windowStart, windowEnd] as a 0–100 percentage, or null when
 * it falls outside the window (the caller skips those ticks).
 */
export function markerPct(t: number, windowStart: number, windowEnd: number): number | null {
  if (windowEnd <= windowStart) return null;
  if (t < windowStart || t > windowEnd) return null;
  return ((t - windowStart) / (windowEnd - windowStart)) * 100;
}
