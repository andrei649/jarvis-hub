import type { PickingInfo } from "@deck.gl/core";

// Styled hover tooltip (spec §4): mono id line + kv lines on a surface card — the `.wv-tip`
// class in globals.css replaces deck.gl's default black box. Values are HTML-escaped (feed
// data is external input).

export function escapeHtml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function getTooltip(
  info: PickingInfo,
): { html: string; className: string } | null {
  const props = (info.object as { properties?: Record<string, unknown> } | null)?.properties;
  const layerId = info.layer?.id;
  if (!props || !layerId) return null;

  const lines = format(layerId, props).filter(Boolean);
  if (lines.length === 0) return null;
  const [id, ...kv] = lines;
  const kvHtml = kv.length
    ? `<div class="tt-kv">${kv.map((l) => escapeHtml(l)).join("<br/>")}</div>`
    : "";
  return {
    html: `<div class="tt-id">${escapeHtml(id!)}</div>${kvHtml}`,
    className: "wv-tip",
  };
}

function format(layerId: string, p: Record<string, unknown>): string[] {
  switch (layerId) {
    case "adsb":
    case "adsb-tiles":
      return [
        `${p.callsign || p.icao24}${p.is_military ? " ⚑ MIL" : ""}`,
        fmt("alt", p.alt_m, " m"),
        fmt("gs", p.gs_kt, " kt"),
        fmt("track", p.track_deg, "°"),
      ];
    case "ais":
    case "ais-tiles":
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
