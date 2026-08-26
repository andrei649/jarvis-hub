// Export / reproducible-replay client (tickets H19.4.6 / H19.2.7, frontend side).
//
// Two concerns live here:
//   1. A tiny browser download helper that turns an in-memory string/Blob into a saved file
//      (GeoJSON / JSON / Markdown), used by ExportPanel to dump the current view or a fetched
//      case/reconstruction brief.
//   2. Graceful fetchers for the backend export endpoints. The backend is being built in
//      parallel against the contract below; until it ships these degrade to `null` on any
//      non-2xx / thrown fetch (matching recon.ts / provenance.ts / api.ts conventions). They
//      never throw, so the UI can offer the affordance without crashing when offline.
//
// Backend contract (mirror when the endpoints land):
//   GET /cases/:id/export?format=brief|geojson|json
//   GET /reconstructions/:id/export?format=brief|geojson|json
// `brief` is Markdown (text/markdown), `geojson`/`json` are application/(geo+)json.

import type { FeatureCollection } from "./types";
import { apiUrl } from "./env";

/** Export formats supported by the backend export endpoints. */
export type ExportFormat = "brief" | "geojson" | "json";

/** A fetched export payload: the raw text body plus the MIME type the server returned. */
export interface ExportResult {
  body: string;
  /** The response Content-Type (e.g. "application/geo+json"), or a sensible default. */
  contentType: string;
}

/** MIME type for a download by format (used when serializing in-memory data locally). */
export function mimeForFormat(format: ExportFormat): string {
  switch (format) {
    case "geojson":
      return "application/geo+json";
    case "brief":
      return "text/markdown";
    case "json":
    default:
      return "application/json";
  }
}

/** File extension for a download by format. */
export function extForFormat(format: ExportFormat): string {
  switch (format) {
    case "geojson":
      return "geojson";
    case "brief":
      return "md";
    case "json":
    default:
      return "json";
  }
}

/**
 * Trigger a browser download of `content` as `filename` with the given MIME type. Builds an
 * object URL from a Blob, clicks a transient <a download>, then revokes the URL. Returns the
 * Blob it built so callers (and tests) can assert size/type without touching the DOM. A no-op
 * (returns the Blob) when there's no `document` (SSR / node test env).
 */
export function downloadBlob(content: string | Blob, filename: string, mime?: string): Blob {
  const blob =
    content instanceof Blob ? content : new Blob([content], { type: mime ?? "application/json" });
  // SSR / unit-test environments have no document — build the Blob but skip the click.
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") {
    return blob;
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return blob;
}

/** Serialize a FeatureCollection (the globe's in-memory view) to pretty GeoJSON text. */
export function featureCollectionToGeoJson(fc: FeatureCollection): string {
  return JSON.stringify(fc, null, 2);
}

/**
 * Merge several per-layer FeatureCollections into one for export, tagging each feature with the
 * layer it came from so a downloaded snapshot is self-describing. Pure; order-preserving.
 */
export function mergeFeatureCollections(
  layers: Record<string, FeatureCollection>,
): FeatureCollection {
  const features: FeatureCollection["features"] = [];
  for (const [layer, fc] of Object.entries(layers)) {
    for (const f of fc.features) {
      features.push({ ...f, properties: { layer, ...(f.properties ?? {}) } });
    }
  }
  return { type: "FeatureCollection", features };
}

/** Build the export URL for a case / reconstruction. Shared by both fetchers. */
function exportUrl(kind: "cases" | "reconstructions", id: string, format: ExportFormat): string {
  const url = new URL(`${apiUrl()}/${kind}/${encodeURIComponent(id)}/export`);
  url.searchParams.set("format", format);
  return url.toString();
}

/**
 * Fetch a case export in `format`. Returns the body text + content-type, or null on a non-ok
 * response or a thrown fetch (backend not up / endpoint not built yet). Never throws.
 */
export async function fetchCaseExport(
  caseId: string,
  format: ExportFormat = "brief",
): Promise<ExportResult | null> {
  try {
    const res = await fetch(exportUrl("cases", caseId, format));
    if (!res.ok) return null;
    const body = await res.text();
    return { body, contentType: res.headers?.get?.("content-type") ?? mimeForFormat(format) };
  } catch {
    return null;
  }
}

/**
 * Fetch a reconstruction export in `format`. Same graceful contract as fetchCaseExport.
 */
export async function fetchReconstructionExport(
  reconstructionId: string,
  format: ExportFormat = "geojson",
): Promise<ExportResult | null> {
  try {
    const res = await fetch(exportUrl("reconstructions", reconstructionId, format));
    if (!res.ok) return null;
    const body = await res.text();
    return { body, contentType: res.headers?.get?.("content-type") ?? mimeForFormat(format) };
  } catch {
    return null;
  }
}

// --- Reproducible replay link ------------------------------------------------
//
// A replay is a window [from, to] (UNIX seconds) plus an optional bbox the camera framed.
// Encoding it into the URL query makes a replay shareable + reproducible: reopening the link
// restores the exact window (and bbox) so a colleague sees the same playback.

/** A replay window: [from, to] in UNIX seconds, with an optional [w,s,e,n] bbox. */
export interface ReplayWindow {
  from: number;
  to: number;
  bbox?: [number, number, number, number];
}

/**
 * Encode a replay window into URLSearchParams query string (no leading "?"). Times are floored
 * to whole seconds (matching the API clients); bbox is a comma-joined w,s,e,n. Deterministic.
 */
export function encodeReplayWindow(win: ReplayWindow): string {
  const params = new URLSearchParams();
  params.set("from", String(Math.floor(win.from)));
  params.set("to", String(Math.floor(win.to)));
  if (win.bbox) params.set("bbox", win.bbox.map((n) => String(n)).join(","));
  return params.toString();
}

/**
 * Decode a replay window from a query string (with or without a leading "?"). Returns null when
 * `from`/`to` are missing or non-finite. A malformed/partial bbox is dropped (window still
 * returned). Round-trips with encodeReplayWindow.
 */
export function decodeReplayWindow(query: string): ReplayWindow | null {
  const params = new URLSearchParams(query.startsWith("?") ? query.slice(1) : query);
  const fromRaw = params.get("from");
  const toRaw = params.get("to");
  if (fromRaw == null || toRaw == null) return null;
  const from = Number(fromRaw);
  const to = Number(toRaw);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
  const win: ReplayWindow = { from, to };
  const rawBbox = params.get("bbox");
  if (rawBbox) {
    const parts = rawBbox.split(",").map(Number);
    if (parts.length === 4 && parts.every((n) => Number.isFinite(n))) {
      win.bbox = [parts[0]!, parts[1]!, parts[2]!, parts[3]!];
    }
  }
  return win;
}

/**
 * Build a full shareable replay URL from a base href (e.g. window.location) and a window.
 * Preserves the origin + path, replaces the query with the encoded window. Pure.
 */
export function buildReplayLink(baseHref: string, win: ReplayWindow): string {
  const query = encodeReplayWindow(win);
  // Strip any existing query/hash, then append ours.
  const base = baseHref.split("#")[0]!.split("?")[0]!;
  return `${base}?${query}`;
}
