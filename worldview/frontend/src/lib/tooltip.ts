import type { LayerId } from "./layers";

// Styled hover tooltip (spec §4): mono id line + kv lines on a surface card — the `.wv-tip`
// class in styles.css. Values are HTML-escaped (feed data is external input).
//
// Pure: the globe hands in the picked feature's layer + properties and positions the returned
// HTML itself, so the formatting stays unit-testable without a renderer.

export function escapeHtml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** The tooltip card's inner HTML for a picked feature, or null when there's nothing to say. */
export function tooltipHtml(
  layerId: LayerId | string,
  props: Record<string, unknown> | null | undefined,
): string | null {
  if (!props) return null;
  const lines = format(layerId, props).filter(Boolean);
  if (lines.length === 0) return null;
  const [id, ...kv] = lines;
  const kvHtml = kv.length
    ? `<div class="tt-kv">${kv.map((l) => escapeHtml(l)).join("<br/>")}</div>`
    : "";
  return `<div class="tt-id">${escapeHtml(id!)}</div>${kvHtml}`;
}

function format(layerId: string, p: Record<string, unknown>): string[] {
  switch (layerId) {
    case "adsb":
      return [
        `${p.callsign || p.icao24}${p.is_military ? " ⚑ MIL" : ""}`,
        fmt("alt", p.alt_m, " m"),
        fmt("gs", p.gs_kt, " kt"),
        fmt("track", p.track_deg, "°"),
      ];
    case "ais":
      return [`MMSI ${p.mmsi}`, fmt("speed", p.sog_kt, " kt"), fmt("course", p.cog_deg, "°")];
    case "tle":
      return [
        `NORAD ${p.norad_id}`,
        `sensor ${p.sensor_type ?? "?"}`,
        fmt("v", p.velocity_kms, " km/s"),
        p.is_sunlit == null ? "" : p.is_sunlit ? "target: ☀ daylight" : "target: ☾ night",
      ];
    case "ew":
      return [`H3 ${p.h3_index}`, fmt("intensity", p.intensity), fmt("samples", p.sample_count)];
    case "context":
      return [
        `${p.kind === "dark_vessel" ? "DARK VESSEL" : p.kind ?? "intel"}`,
        p.category ? String(p.category) : "",
        p.mmsi ? `MMSI ${p.mmsi}` : "",
        p.kind === "dark_vessel" ? "position: dead-reckoned" : "",
      ];
    default:
      return [];
  }
}

function fmt(label: string, value: unknown, unit = ""): string {
  if (value == null) return "";
  const n = typeof value === "number" ? Math.round(value * 100) / 100 : value;
  return `${label}: ${n}${unit}`;
}
