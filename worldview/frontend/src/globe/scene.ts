import type { Geometry, Position } from "geojson";
import type { LayerData } from "@/lib/layerData";
import type { LayerId } from "@/lib/layers";
import type { Feature, FeatureCollection } from "@/lib/types";
import { shouldUseTiles, buildTileLayerProps, type TileLayerProps } from "@/lib/tiles";
import { MARK_RGB } from "@/lib/markStyle";
import type { IconName } from "@/lib/markIcons";
import { buildNegativeSpace } from "@/lib/negativeSpace";

// The scene builder: per-layer FeatureCollections in, a plain DRAW SPEC out.
//
// Deliberately Cesium-free. Everything about WHAT the globe shows — which layers are drawn,
// the mark encodings (spec §1.2: shape + color, never color alone), altitudes, the vector-tile
// switch, the negative-space grammar — is decided here and unit-tested in a node environment.
// src/globe/render.ts is the only module that knows Cesium exists, and it just applies this
// spec. That split is what keeps the map's behavior testable without a GPU.

export type Rgba = [number, number, number, number];

/** A billboard mark at a geodetic position. */
export interface PointDraw {
  /** Stable, scene-unique id (`<layer>:<entity>`), used to diff frames. */
  id: string;
  layer: LayerId;
  lon: number;
  lat: number;
  /** Metres above the ellipsoid — ADS-B and satellite geometries carry Z (PointZ). */
  alt: number;
  icon: IconName;
  /** Fallback colour when no icon bitmap is available (headless canvas). */
  color: Rgba;
  sizePx: number;
  /** Heading in degrees clockwise from north; 0 for non-directional marks. */
  rotationDeg: number;
  props: Record<string, unknown>;
  /** Selection id for trackable entities, or null when this mark can't be traced. */
  trackId: string | null;
}

export interface PolygonDraw {
  id: string;
  /** Outer ring first, then holes. Positions are [lon, lat]. */
  rings: [number, number][][];
  fill: Rgba | null;
  outline: Rgba | null;
  outlineWidth: number;
}

export interface PolylineDraw {
  id: string;
  positions: [number, number, number][];
  color: Rgba;
  width: number;
  /** Dashed lines carry the "estimated, not observed" meaning (dead-reckoned paths). */
  dashed: boolean;
}

export interface LabelDraw {
  id: string;
  lon: number;
  lat: number;
  text: string;
  color: Rgba;
  sizePx: number;
}

export interface Scene {
  points: PointDraw[];
  polygons: PolygonDraw[];
  polylines: PolylineDraw[];
  labels: LabelDraw[];
  /** Imagery overlay props when the zoomed-out tile switch is active, else null. */
  tileOverlay: TileLayerProps | null;
  /** Logical layers drawn this frame — the assertion surface for the tile-switch tests. */
  layerIds: string[];
}

const TRAIL: Rgba = [238, 241, 245, 220];
const CALLOUT: Rgba = [167, 139, 250, 230];
const INK_FAINT: Rgba = [238, 241, 245, 36];

/** The property each layer's selection id is read from. */
export const TRACK_ID_PROP: Partial<Record<LayerId, string>> = {
  adsb: "icao24",
  ais: "mmsi",
  tle: "norad_id",
};

function rgba(rgb: [number, number, number], alpha: number): Rgba {
  return [rgb[0], rgb[1], rgb[2], alpha];
}

/** [lon, lat, alt] from a GeoJSON position, defaulting a missing Z to 0 (ground). */
function coords(position: Position | undefined): [number, number, number] | null {
  if (!position) return null;
  const lon = Number(position[0]);
  const lat = Number(position[1]);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  const alt = Number(position[2]);
  return [lon, lat, Number.isFinite(alt) ? alt : 0];
}

function pointOf(f: Feature): [number, number, number] | null {
  if (f.geometry?.type !== "Point") return null;
  return coords(f.geometry.coordinates);
}

function ringsOf(geometry: Geometry | null | undefined): [number, number][][] {
  if (!geometry) return [];
  if (geometry.type === "Polygon") {
    return geometry.coordinates.map((ring) =>
      ring.map((p) => [Number(p[0]), Number(p[1])] as [number, number]),
    );
  }
  if (geometry.type === "MultiPolygon") {
    // Flatten: each polygon's outer ring is drawn independently (holes are rare here and the
    // renderer treats every ring in `rings` after the first as a hole of the same polygon, so
    // only the outer rings of a MultiPolygon can be carried without changing the shape).
    return geometry.coordinates.map((poly) =>
      (poly[0] ?? []).map((p) => [Number(p[0]), Number(p[1])] as [number, number]),
    );
  }
  return [];
}

function linesOf(geometry: Geometry | null | undefined): [number, number, number][][] {
  if (!geometry) return [];
  if (geometry.type === "LineString") {
    return [geometry.coordinates.map(coords).filter((p): p is [number, number, number] => p != null)];
  }
  if (geometry.type === "MultiLineString") {
    return geometry.coordinates.map((line) =>
      line.map(coords).filter((p): p is [number, number, number] => p != null),
    );
  }
  return [];
}

function pushPolygons(
  out: PolygonDraw[],
  idPrefix: string,
  fc: FeatureCollection,
  style: { fill: Rgba | null; outline: Rgba | null; outlineWidth?: number },
  fillFor?: (f: Feature) => Rgba,
) {
  fc.features.forEach((f, i) => {
    const rings = ringsOf(f.geometry);
    if (rings.length === 0) return;
    out.push({
      id: `${idPrefix}:${i}`,
      rings,
      fill: fillFor ? fillFor(f) : style.fill,
      outline: style.outline,
      outlineWidth: style.outlineWidth ?? 1,
    });
  });
}

function pushLines(
  out: PolylineDraw[],
  idPrefix: string,
  fc: FeatureCollection,
  style: { color: Rgba; width: number; dashed: boolean },
) {
  let n = 0;
  for (const f of fc.features) {
    for (const positions of linesOf(f.geometry)) {
      if (positions.length < 2) continue;
      out.push({ id: `${idPrefix}:${n++}`, positions, ...style });
    }
  }
}

/** Satellites carry their ground footprint polygon in `properties.footprint`. */
function footprintCollection(tle: FeatureCollection): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: tle.features
      .filter((f) => f.properties.footprint)
      .map((f) => ({
        type: "Feature",
        geometry: f.properties.footprint as Geometry,
        properties: { norad_id: f.properties.norad_id },
      })),
  };
}

function pointDraws(
  layer: LayerId,
  fc: FeatureCollection,
  opts: {
    icon: (f: Feature) => IconName;
    color: (f: Feature) => Rgba;
    sizePx: number;
    rotation?: (f: Feature) => number;
    idProp?: string;
  },
): PointDraw[] {
  const out: PointDraw[] = [];
  fc.features.forEach((f, i) => {
    const position = pointOf(f);
    if (!position) return;
    const props = f.properties ?? {};
    const idProp = opts.idProp ?? TRACK_ID_PROP[layer];
    const raw = idProp ? props[idProp] : undefined;
    const trackId = raw == null ? null : String(raw);
    out.push({
      id: `${layer}:${trackId ?? i}`,
      layer,
      lon: position[0],
      lat: position[1],
      alt: position[2],
      icon: opts.icon(f),
      color: opts.color(f),
      sizePx: opts.sizePx,
      rotationDeg: opts.rotation ? opts.rotation(f) : 0,
      props,
      trackId,
    });
  });
  return out;
}

/**
 * Build the frame's draw spec from the per-layer data.
 *
 * `zoom` drives the tile switch (H19.5.1): zoomed out far enough AND a drawable raster tile URL
 * configured → the aggregated imagery overlay replaces the adsb/ais marks. With no tile URL this
 * is always false, so point rendering is unchanged (a no-op).
 */
export function buildScene(
  data: LayerData,
  visibility: Record<LayerId, boolean>,
  track?: FeatureCollection,
  zoom?: number,
): Scene {
  const points: PointDraw[] = [];
  const polygons: PolygonDraw[] = [];
  const polylines: PolylineDraw[] = [];
  const labels: LabelDraw[] = [];
  const layerIds: string[] = [];

  const tileProps = buildTileLayerProps();
  const tilesActive = tileProps != null && zoom != null && shouldUseTiles(zoom);
  const useTiles = (id: LayerId): boolean => tilesActive && (id === "adsb" || id === "ais");

  // Selected-entity trail (a LineString path), drawn under the live marks.
  if (track && track.features.length > 0) {
    pushLines(polylines, "track", track, { color: TRAIL, width: 2, dashed: false });
    if (polylines.length > 0) layerIds.push("track");
  }

  if (visibility.adsb) {
    if (useTiles("adsb")) {
      layerIds.push("adsb-tiles");
    } else {
      layerIds.push("adsb");
      points.push(
        ...pointDraws("adsb", data.adsb, {
          icon: (f) => (f.properties.is_military ? "mil" : "civil"),
          color: (f) => rgba(f.properties.is_military ? MARK_RGB.mil : MARK_RGB.civil, 255),
          sizePx: 14,
          // Chevrons point along the aircraft's track (degrees clockwise from north).
          rotation: (f) => Number(f.properties.track_deg ?? 0),
        }),
      );
    }
  }

  if (visibility.ais) {
    if (useTiles("ais")) {
      layerIds.push("ais-tiles");
    } else {
      layerIds.push("ais");
      points.push(
        ...pointDraws("ais", data.ais, {
          icon: () => "vessel",
          color: () => rgba(MARK_RGB.vessel, 255),
          sizePx: 12,
        }),
      );
    }
  }

  if (visibility.tle) {
    layerIds.push("tle");
    pushPolygons(polygons, "tle-footprint", footprintCollection(data.tle), {
      fill: rgba(MARK_RGB.sat, 40),
      outline: rgba(MARK_RGB.sat, 160),
    });
    points.push(
      ...pointDraws("tle", data.tle, {
        icon: () => "sat",
        color: () => rgba(MARK_RGB.sat, 255),
        sizePx: 18,
      }),
    );
  }

  if (visibility.ew) {
    layerIds.push("ew");
    pushPolygons(
      polygons,
      "ew",
      data.ew,
      { fill: null, outline: [255, 140, 40, 200], outlineWidth: 1 },
      (f) => {
        const i = Number(f.properties.intensity ?? 0);
        return [255, Math.round(180 * (1 - i)) + 40, 40, 120];
      },
    );
  }

  if (visibility.context) {
    layerIds.push("context");
    // Zones/areas carry polygon geometry; events and dark vessels are points.
    pushPolygons(polygons, "context-zone", data.context, {
      fill: rgba(MARK_RGB.intel, 60),
      outline: rgba(MARK_RGB.intel, 200),
    });
    points.push(
      ...pointDraws("context", data.context, {
        icon: (f) => (f.properties.kind === "dark_vessel" ? "dark" : "intel"),
        color: (f) =>
          f.properties.kind === "dark_vessel" ? rgba(MARK_RGB.dark, 255) : rgba(MARK_RGB.intel, 200),
        sizePx: 16,
        idProp: "entity_id",
      }),
    );

    // Annotation/callout layer: label notable events with their category on the map.
    data.context.features.forEach((f, i) => {
      if (f.properties.kind !== "event") return;
      const position = pointOf(f);
      if (!position) return;
      labels.push({
        id: `context-callout:${i}`,
        lon: position[0],
        lat: position[1],
        text: String(f.properties.category ?? "event"),
        color: CALLOUT,
        sizePx: 12,
      });
    });

    // The negative-space grammar (spec §5.0): the dark-vessel story rendered as evidence —
    // ghost ring at the last fix, dashed dead-reckoned path, faint uncertainty cone, mono
    // captions — plus dashed outlines for backend-flagged voided zones. None of it animates.
    const ns = buildNegativeSpace(data.context);
    pushPolygons(polygons, "ns-cone", ns.cones, {
      fill: rgba(MARK_RGB.dark, 12),
      outline: rgba(MARK_RGB.dark, 45),
    });
    pushLines(polylines, "ns-dr-path", ns.drPaths, {
      color: rgba(MARK_RGB.dark, 140),
      width: 1.5,
      dashed: true,
    });
    pushPolygons(polygons, "ns-void-zone", ns.voidZones, {
      fill: null,
      outline: INK_FAINT,
    });
    points.push(
      ...pointDraws("context", ns.ghosts, {
        icon: () => "ghost",
        color: () => rgba(MARK_RGB.dark, 140),
        sizePx: 16,
        idProp: "__none__",
      }).map((p, i) => ({ ...p, id: `ns-ghost:${i}`, trackId: null })),
    );
    ns.captions.forEach((caption, i) => {
      labels.push({
        id: `ns-caption:${i}`,
        lon: caption.position[0],
        lat: caption.position[1],
        text: caption.text,
        color: rgba(MARK_RGB.dark, 190),
        sizePx: 10,
      });
    });
  }

  return {
    points,
    polygons,
    polylines,
    labels,
    tileOverlay: tilesActive ? tileProps : null,
    layerIds,
  };
}
