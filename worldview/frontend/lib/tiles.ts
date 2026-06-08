import type { LayerId } from "./layers";

// H19.5.1 — Vector-tile service (CLIENT side).
//
// When the globe is zoomed OUT, shipping every ADS-B/AIS point to the browser is wasteful:
// at world scale a million points collapse into a few pixels. Instead we let a tile server
// (Martin / pg_tileserv, run locally via docker-compose) serve pre-aggregated MVT/raster
// tiles, and Deck.gl's MVTLayer streams only the tiles in view. When the user zooms IN past
// the threshold we fall back to the existing per-point scatter layers (full fidelity,
// selection, tooltips, time scrubbing).
//
// NOTE (acceptance criteria): the full AC — 1M+ points @60fps — is only realized once the
// local tile server is running and NEXT_PUBLIC_TILE_URL points at it. With no URL set this
// module is a pure no-op: shouldUseTiles() is always false and today's point rendering is
// unchanged. Nothing here ever throws on a missing tile server — it degrades to points.
//
// Config (all NEXT_PUBLIC_*, read at call time so the values are picklable in tests):
//   NEXT_PUBLIC_TILE_URL       MVT/raster template, e.g. https://host/{z}/{x}/{y}.pbf
//                              Empty / unset = tiles disabled.
//   NEXT_PUBLIC_TILE_MAX_ZOOM  Zoom at/below which tiles are used (zoomed out). Default 6.
//   NEXT_PUBLIC_TILE_MIN_ZOOM  Min source zoom for the tile layer. Default 0.

/** Default upper zoom bound for tile rendering. At/below this zoom we use tiles. */
export const DEFAULT_TILE_MAX_ZOOM = 6;
/** Default lower zoom bound passed to the tile layer source. */
export const DEFAULT_TILE_MIN_ZOOM = 0;

/** Point layers that have a server-side tile equivalent (the high-cardinality ones). */
export const TILEABLE_LAYERS: readonly LayerId[] = ["adsb", "ais"] as const;

export function isTileableLayer(id: LayerId): boolean {
  return (TILEABLE_LAYERS as readonly string[]).includes(id);
}

export interface TileConfig {
  /** MVT/raster URL template, or "" when tiles are disabled. */
  url: string;
  /** Zoom at/below which tiles replace per-point layers. */
  maxZoom: number;
  /** Min source zoom handed to the tile layer. */
  minZoom: number;
  /** Convenience: whether a usable tile URL is configured. */
  enabled: boolean;
}

function parseZoom(raw: string | undefined, fallback: number): number {
  if (raw == null || raw.trim() === "") return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

/**
 * Read the tile config from NEXT_PUBLIC_* env. Pure w.r.t. its inputs; reads env at call
 * time so a test can stub process.env before calling. Never throws.
 */
export function getTileConfig(): TileConfig {
  const url = (process.env.NEXT_PUBLIC_TILE_URL ?? "").trim();
  const maxZoom = parseZoom(process.env.NEXT_PUBLIC_TILE_MAX_ZOOM, DEFAULT_TILE_MAX_ZOOM);
  const minZoom = parseZoom(process.env.NEXT_PUBLIC_TILE_MIN_ZOOM, DEFAULT_TILE_MIN_ZOOM);
  return { url, maxZoom, minZoom, enabled: url.length > 0 };
}

export interface ShouldUseTilesOpts {
  /** Override the configured max-zoom threshold (mainly for tests). */
  maxZoom?: number;
  /** Override the configured/derived config (mainly for tests). */
  config?: TileConfig;
}

/**
 * Decide whether to render the tile layer instead of per-point layers at this zoom.
 *
 * True iff a tile URL is configured AND zoom is at/below the threshold (zoomed out), where
 * per-point rendering is wasteful. Above the threshold (zoomed in) we keep the point layers,
 * so this returns false. Disabled (no URL) → always false (today's behavior, a no-op).
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
 * Build the props for a Deck.gl MVT/Tile layer from the current config. Returns null when
 * tiles are disabled so callers can simply skip the tile layer. The layers module owns the
 * actual MVTLayer construction (styling, picking); this only supplies source + zoom bounds.
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
