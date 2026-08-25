import type { LayerId } from "./layers";
import { env } from "./env";

// H19.5.1 — pre-aggregated tile service (CLIENT side).
//
// When the globe is zoomed OUT, shipping every ADS-B/AIS point to the browser is wasteful:
// at world scale a million points collapse into a few pixels. Instead we let a tile server
// (Martin / pg_tileserv, run locally via docker-compose) serve pre-aggregated tiles, and the
// globe streams only the tiles in view as an imagery overlay. When the user zooms IN past the
// threshold we fall back to the per-point billboard layers (full fidelity, selection, tooltips,
// time scrubbing).
//
// RASTER ONLY. Cesium's imagery pipeline draws raster tiles (png/jpg/webp); it has no built-in
// Mapbox-Vector-Tile decoder, so a `.pbf` template can't be drawn and must NOT suppress the
// point layers — `shouldUseTiles` returns false for it and the globe keeps rendering points.
// Point Martin/pg_tileserv at a raster endpoint (or put a raster renderer in front) to use this.
//
// NOTE (acceptance criteria): the full AC — 1M+ points @60fps — is only realized once the
// local tile server is running and VITE_TILE_URL points at it. With no URL set this
// module is a pure no-op: shouldUseTiles() is always false and today's point rendering is
// unchanged. Nothing here ever throws on a missing tile server — it degrades to points.
//
// Config (all VITE_*, read at call time so the values are picklable in tests):
//   VITE_TILE_URL       Raster template, e.g. https://host/{z}/{x}/{y}.png
//                       Empty / unset = tiles disabled.
//   VITE_TILE_MAX_ZOOM  Zoom at/below which tiles are used (zoomed out). Default 6.
//   VITE_TILE_MIN_ZOOM  Min source zoom for the tile layer. Default 0.

/** Default upper zoom bound for tile rendering. At/below this zoom we use tiles. */
export const DEFAULT_TILE_MAX_ZOOM = 6;
/** Default lower zoom bound passed to the tile layer source. */
export const DEFAULT_TILE_MIN_ZOOM = 0;

/** Point layers that have a server-side tile equivalent (the high-cardinality ones). */
export const TILEABLE_LAYERS: readonly LayerId[] = ["adsb", "ais"] as const;

export function isTileableLayer(id: LayerId): boolean {
  return (TILEABLE_LAYERS as readonly string[]).includes(id);
}

/** Raster image extensions Cesium's UrlTemplateImageryProvider can actually draw. */
const RASTER_EXTENSIONS = ["png", "jpg", "jpeg", "webp"];

/**
 * True when `url` is a raster tile template. Vector-tile templates (`.pbf`, `.mvt`) are NOT
 * raster: Cesium can't decode them as imagery, so they never replace the point layers.
 * A template with no extension at all is treated as raster — many raster servers omit one.
 */
export function isRasterTemplate(url: string): boolean {
  const path = url.split("?")[0] ?? "";
  const match = /\.([a-z0-9]+)$/i.exec(path.trim());
  if (!match) return url.trim().length > 0;
  return RASTER_EXTENSIONS.includes(match[1]!.toLowerCase());
}

export interface TileConfig {
  /** Raster tile URL template, or "" when tiles are disabled. */
  url: string;
  /** Zoom at/below which tiles replace per-point layers. */
  maxZoom: number;
  /** Min source zoom handed to the tile layer. */
  minZoom: number;
  /** Convenience: whether a usable, drawable tile URL is configured. */
  enabled: boolean;
}

function parseZoom(raw: string | undefined, fallback: number): number {
  if (raw == null || raw.trim() === "") return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

/**
 * Read the tile config from VITE_* env. Pure w.r.t. its inputs; reads env at call
 * time so a test can stub the environment before calling. Never throws. A configured but
 * non-raster (vector) template reports `enabled: false` — see the RASTER ONLY note above.
 */
export function getTileConfig(): TileConfig {
  const url = env("VITE_TILE_URL").trim();
  const maxZoom = parseZoom(env("VITE_TILE_MAX_ZOOM", ""), DEFAULT_TILE_MAX_ZOOM);
  const minZoom = parseZoom(env("VITE_TILE_MIN_ZOOM", ""), DEFAULT_TILE_MIN_ZOOM);
  return { url, maxZoom, minZoom, enabled: url.length > 0 && isRasterTemplate(url) };
}

export interface ShouldUseTilesOpts {
  /** Override the configured max-zoom threshold (mainly for tests). */
  maxZoom?: number;
  /** Override the configured/derived config (mainly for tests). */
  config?: TileConfig;
}

/**
 * Decide whether to render the tile overlay instead of per-point layers at this zoom.
 *
 * True iff a drawable (raster) tile URL is configured AND zoom is at/below the threshold
 * (zoomed out), where per-point rendering is wasteful. Above the threshold (zoomed in) we keep
 * the point layers, so this returns false. Disabled (no URL, or a vector template Cesium can't
 * draw) → always false (today's behavior, a no-op).
 */
export function shouldUseTiles(zoom: number, opts: ShouldUseTilesOpts = {}): boolean {
  const config = opts.config ?? getTileConfig();
  if (!config.enabled) return false;
  if (!Number.isFinite(zoom)) return false;
  const threshold = opts.maxZoom ?? config.maxZoom;
  return zoom <= threshold;
}

export interface TileLayerProps {
  data: string;
  minZoom: number;
  maxZoom: number;
}

/**
 * Build the props for the imagery tile overlay from the current config. Returns null when
 * tiles are disabled so callers can simply skip the overlay. The globe renderer owns the actual
 * Cesium provider construction; this only supplies source + zoom bounds.
 */
export function buildTileLayerProps(config: TileConfig = getTileConfig()): TileLayerProps | null {
  if (!config.enabled) return null;
  return {
    data: config.url,
    minZoom: config.minZoom,
    // The tile source covers up to the switch threshold; beyond it we use points.
    maxZoom: config.maxZoom,
  };
}
