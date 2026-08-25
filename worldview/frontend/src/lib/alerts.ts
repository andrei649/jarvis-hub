import type { LayerData } from "./layerData";
import type { Feature } from "./types";

// Surface the platform's "so what": derive a flat, sortable list of actionable intel alerts
// (dark vessels + geopolitical events) from the contextual-intel layer. Pure + unit-testable.

export type AlertSeverity = "high" | "medium" | "low";
export type AlertKind = "dark_vessel" | "event";

export interface Alert {
  /** Stable id for React keys + selection wiring. */
  id: string;
  kind: AlertKind;
  label: string;
  severity: AlertSeverity;
  /** UNIX seconds of the underlying observation, if known (0 when absent). */
  ts: number;
  lon?: number;
  lat?: number;
  /** Entity id to feed back into selectEntity (dark vessels link to the inspector). */
  entityId?: string;
}

// Numeric weight so we can sort high → low regardless of label ordering.
const SEVERITY_RANK: Record<AlertSeverity, number> = { high: 3, medium: 2, low: 1 };

// Map a raw event severity (0..1 float, or a small integer scale) to a coarse band.
function eventSeverity(raw: unknown): AlertSeverity {
  const n = Number(raw);
  if (!Number.isFinite(n)) return "low";
  // Events typically carry a 0..1 severity; treat ≥0.66 as high, ≥0.33 as medium.
  if (n >= 0.66 || n >= 4) return "high";
  if (n >= 0.33 || n >= 2) return "medium";
  return "low";
}

// Extract a [lon, lat] from a feature only when it's a Point (callers skip polygons).
function pointOf(feature: Feature): { lon?: number; lat?: number } {
  const geom = feature.geometry;
  if (geom?.type === "Point" && Array.isArray(geom.coordinates)) {
    const [lon, lat] = geom.coordinates as number[];
    if (Number.isFinite(lon) && Number.isFinite(lat)) return { lon, lat };
  }
  return {};
}

function entityIdOf(props: Record<string, unknown>): string {
  return String(props.entity_id ?? props.mmsi ?? props.id ?? "");
}

/**
 * Build alerts from `data.context.features`. Dark vessels are always high severity; events map
 * their raw severity to a band. Results are sorted by severity (high first) then recency (newest
 * first). `now` is accepted for future time-window filtering and to keep the signature stable.
 */
export function deriveAlerts(data: LayerData, now: number): Alert[] {
  void now; // reserved for trailing-window filtering; kept for a stable, future-proof signature
  const features = data.context?.features ?? [];
  const alerts: Alert[] = [];

  for (const feature of features) {
    const props = feature.properties ?? {};
    const kind = props.kind;
    const { lon, lat } = pointOf(feature);

    if (kind === "dark_vessel") {
      const mmsi = String(props.mmsi ?? "?");
      const gap = props.gap_seconds ?? "?";
      const entityId = entityIdOf(props);
      alerts.push({
        id: `dark_vessel:${entityId || mmsi}`,
        kind: "dark_vessel",
        label: `Dark vessel MMSI ${mmsi} (gap ${gap}s)`,
        severity: "high",
        ts: Number(props.ts ?? 0),
        lon,
        lat,
        entityId: entityId || mmsi,
      });
    } else if (kind === "event") {
      const category = String(props.category ?? "event");
      const severity = eventSeverity(props.severity);
      const entityId = entityIdOf(props);
      alerts.push({
        id: `event:${entityId || `${category}:${props.ts ?? ""}`}`,
        kind: "event",
        label: `${category} (sev ${props.severity ?? "?"})`,
        severity,
        ts: Number(props.ts ?? 0),
        lon,
        lat,
        entityId: entityId || undefined,
      });
    }
  }

  alerts.sort((a, b) => {
    const bySeverity = SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity];
    if (bySeverity !== 0) return bySeverity;
    return b.ts - a.ts; // newer first
  });

  return alerts;
}
