import type { PickingInfo } from "@deck.gl/core";

// Per-layer hover tooltip: a compact, human-readable summary of the picked feature.
export function getTooltip(info: PickingInfo): { text: string } | null {
  const props = (info.object as { properties?: Record<string, unknown> } | null)?.properties;
  const layerId = info.layer?.id;
  if (!props || !layerId) return null;

  const lines = format(layerId, props).filter(Boolean);
  return lines.length ? { text: lines.join("\n") } : null;
}

function format(layerId: string, p: Record<string, unknown>): string[] {
  switch (layerId) {
    case "adsb":
      return [
        `${p.callsign || p.icao24}${p.is_military ? " ⚑ MIL" : ""}`,
        fmt("alt", p.alt_m, "m"),
        fmt("gs", p.gs_kt, "kt"),
        fmt("track", p.track_deg, "°"),
      ];
    case "ais":
      return [`MMSI ${p.mmsi}`, fmt("sog", p.sog_kt, "kt"), fmt("cog", p.cog_deg, "°")];
    case "tle":
      return [`NORAD ${p.norad_id}`, `sensor ${p.sensor_type ?? "?"}`, fmt("v", p.velocity_kms, "km/s")];
    case "ew":
      return [`H3 ${p.h3_index}`, fmt("intensity", p.intensity), fmt("samples", p.sample_count)];
    case "context":
      return [`${p.kind ?? "intel"}`, p.category ? String(p.category) : "", p.mmsi ? `MMSI ${p.mmsi}` : ""];
    default:
      return [];
  }
}

function fmt(label: string, value: unknown, unit = ""): string {
  if (value == null) return "";
  const n = typeof value === "number" ? Math.round(value * 100) / 100 : value;
  return `${label}: ${n}${unit}`;
}
