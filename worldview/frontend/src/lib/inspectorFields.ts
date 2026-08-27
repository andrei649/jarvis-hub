// Humanized inspector fields (spec §4): raw telemetry keys become labeled, unit-bearing rows
// ("Last speed / course · 11.2 kt · 312°", never `sog_kt`), and a dark-vessel selection leads
// with its ALERT CONTEXT (last fix, silence duration, dead-reckoned position) instead of a
// generic property dump. Pure and unit-testable.

import type { LayerId } from "./layers";
import type { MarkKind } from "./markStyle";

export interface FieldRow {
  label: string;
  value: string;
  /** "warn" renders amber, "bad" renders red. */
  tone?: "warn" | "bad";
}

export interface InspectorView {
  /** Primary identity line (callsign / MMSI / NORAD id…). */
  name: string;
  /** Mono kind tag under the name (e.g. "DARK VESSEL · ALERT CONTEXT"). */
  kind: string;
  /** The glyph that identifies this entity in the legend/map. */
  glyph: MarkKind | "hex";
  /** True when this selection is an alert context (tints the panel red). */
  alert: boolean;
  rows: FieldRow[];
  /** Leftover props not covered by the humanized rows (transparency, collapsed by default). */
  raw: [string, string][];
}

/** "1h 04m" / "45m" / "30s" from seconds. */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60) % 60;
  const h = Math.floor(s / 3600);
  if (h === 0) return `${m}m`;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

function utc(ts: unknown): string | null {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return null;
  return `${new Date(n * 1000).toISOString().slice(11, 19)} UTC`;
}

function num(v: unknown, digits = 1): string | null {
  const n = Number(v);
  if (!Number.isFinite(n)) return null;
  return n.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function str(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return String(Math.round(v * 1000) / 1000);
  return String(v);
}

// Keys we either render as humanized rows or deliberately hide from the raw dump.
const HIDDEN = new Set(["coordTimes", "footprint", "source", "ingested_at", "layer", "entity_id"]);

function leftovers(props: Record<string, unknown>, used: string[]): [string, string][] {
  const usedSet = new Set([...used, ...HIDDEN]);
  return Object.entries(props)
    .filter(([k]) => !usedSet.has(k))
    .map(([k, v]) => [k, str(v)]);
}

export function buildInspectorView(
  layer: LayerId,
  props: Record<string, unknown>,
  masterTime: number,
): InspectorView {
  switch (layer) {
    case "adsb": {
      const mil = Boolean(props.is_military);
      const rows: FieldRow[] = [];
      const alt = num(props.alt_m, 0);
      const gs = num(props.gs_kt, 0);
      const track = num(props.track_deg, 0);
      if (alt) rows.push({ label: "Altitude", value: `${alt} m` });
      if (gs || track)
        rows.push({ label: "Ground speed / track", value: `${gs ?? "—"} kt · ${track ?? "—"}°` });
      rows.push({ label: "Military", value: mil ? "yes ⚑" : "no" });
      return {
        name: String(props.callsign ?? props.icao24 ?? "?"),
        kind: mil ? "AIRCRAFT · MILITARY" : "AIRCRAFT",
        glyph: mil ? "mil" : "civil",
        alert: false,
        rows,
        raw: leftovers(props, ["callsign", "icao24", "alt_m", "gs_kt", "track_deg", "is_military"]),
      };
    }
    case "ais": {
      const rows: FieldRow[] = [];
      const sog = num(props.sog_kt);
      const cog = num(props.cog_deg, 0);
      if (sog || cog)
        rows.push({ label: "Speed / course", value: `${sog ?? "—"} kt · ${cog ?? "—"}°` });
      return {
        name: `MMSI ${String(props.mmsi ?? "?")}`,
        kind: "VESSEL",
        glyph: "vessel",
        alert: false,
        rows,
        raw: leftovers(props, ["mmsi", "sog_kt", "cog_deg"]),
      };
    }
    case "tle": {
      const rows: FieldRow[] = [];
      const sensor = props.sensor_type ? String(props.sensor_type).toUpperCase() : null;
      const v = num(props.velocity_kms, 2);
      if (v) rows.push({ label: "Velocity", value: `${v} km/s` });
      if (props.is_sunlit != null)
        rows.push({
          label: "Target lighting",
          value: props.is_sunlit ? "☀ daylight" : "☾ night",
          tone: props.is_sunlit ? undefined : sensor === "OPTICAL" ? "warn" : undefined,
        });
      return {
        name: `NORAD ${String(props.norad_id ?? "?")}`,
        kind: sensor ? `SATELLITE · ${sensor}` : "SATELLITE",
        glyph: "sat",
        alert: false,
        rows,
        raw: leftovers(props, ["norad_id", "sensor_type", "velocity_kms", "is_sunlit"]),
      };
    }
    case "ew": {
      const rows: FieldRow[] = [];
      const i = Number(props.intensity);
      if (Number.isFinite(i))
        rows.push({
          label: "Jamming intensity",
          value: i.toFixed(2),
          tone: i >= 0.66 ? "bad" : i >= 0.33 ? "warn" : undefined,
        });
      const samples = num(props.sample_count, 0);
      if (samples) rows.push({ label: "Samples", value: samples });
      return {
        name: `H3 ${String(props.h3_index ?? "?").slice(0, 12)}`,
        kind: "GPS JAMMING CELL",
        glyph: "hex",
        alert: false,
        rows,
        raw: leftovers(props, ["h3_index", "intensity", "sample_count"]),
      };
    }
    case "context": {
      if (props.kind === "dark_vessel") {
        // The alert context leads (spec §4): what happened, for how long, and that the shown
        // position is an estimate — not a raw property dump.
        const rows: FieldRow[] = [];
        const lastFix = utc(props.ts);
        if (lastFix) rows.push({ label: "Last AIS fix", value: lastFix });
        const gap = Number(props.gap_seconds);
        if (Number.isFinite(gap))
          rows.push({ label: "Silent for", value: formatDuration(gap), tone: "bad" });
        rows.push({ label: "Position now", value: "dead-reckoned", tone: "warn" });
        const fence = props.geofence ?? props.aoi_id ?? props.aoi;
        if (fence != null) rows.push({ label: "Geofence", value: String(fence) });
        return {
          name: `MMSI ${String(props.mmsi ?? "?")}`,
          kind: "DARK VESSEL · ALERT CONTEXT",
          glyph: "dark",
          alert: true,
          rows,
          raw: leftovers(props, ["kind", "mmsi", "ts", "gap_seconds", "geofence", "aoi_id", "aoi"]),
        };
      }
      const rows: FieldRow[] = [];
      const sev = Number(props.severity);
      if (Number.isFinite(sev))
        rows.push({
          label: "Severity",
          value: sev.toFixed(2),
          tone: sev >= 0.66 ? "bad" : sev >= 0.33 ? "warn" : undefined,
        });
      const at = utc(props.ts);
      if (at) rows.push({ label: "Reported", value: at });
      return {
        name: String(props.category ?? props.kind ?? "intel"),
        kind: String(props.kind ?? "event").toUpperCase(),
        glyph: "intel",
        alert: false,
        rows,
        raw: leftovers(props, ["kind", "category", "severity", "ts"]),
      };
    }
  }
  // Exhaustive over LayerId; keeps tsc honest if a layer is added.
  void masterTime;
  return { name: "?", kind: "?", glyph: "intel", alert: false, rows: [], raw: [] };
}
