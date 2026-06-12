import { GeoJsonLayer, TextLayer } from "@deck.gl/layers";
import { MVTLayer } from "./mvtLayer";
import type { Layer } from "@deck.gl/core";
import type { Geometry } from "geojson";
import type { LayerData } from "./useWorldViewData";
import type { LayerId } from "./layers";
import type { Feature, FeatureCollection } from "./types";
import { shouldUseTiles, buildTileLayerProps, type TileLayerProps } from "./tiles";
import { MARK_RGB } from "./markStyle";
import { getMarkAtlas, ICON_MAPPING, type IconName } from "./markAtlas";
import { buildNegativeSpace, type NsCaption } from "./negativeSpace";

// Build Deck.gl layers from the per-layer FeatureCollections. Each WorldView layer maps to a
// GeoJsonLayer styled per the redesign's encodings (spec §1.2): shape + color, never color
// alone — aircraft are chevrons (civil filled steel-blue, military hollow amber), vessels
// seafoam diamonds, dark vessels red hollow rings, satellites gold ringed dots, intel violet
// squares. Shapes come from the runtime icon atlas; without a canvas (tests/SSR) every point
// falls back to the previous circle rendering so the map never depends on the atlas.

type Visibility = Record<LayerId, boolean>;

const TRAIL: [number, number, number] = [238, 241, 245];
const CALLOUT: [number, number, number] = [167, 139, 250];
const INK: [number, number, number] = [238, 241, 245];

// Event callouts: only context features that are events AND have a Point geometry get a label
// on the map (polygons/zones are skipped). The label is the event category.
function eventCallouts(data: LayerData["context"]): Feature[] {
  return data.features.filter(
    (f) => f.properties.kind === "event" && f.geometry?.type === "Point",
  );
}

function calloutPosition(f: Feature): [number, number] {
  // Safe because eventCallouts only keeps Point geometries.
  const coords = (f.geometry as { coordinates: number[] }).coordinates;
  return [Number(coords[0]), Number(coords[1])];
}

function footprintCollection(data: LayerData["tle"]): FeatureCollection {
  // Satellites carry their footprint polygon in properties.footprint (a GeoJSON geometry).
  return {
    type: "FeatureCollection",
    features: data.features
      .filter((f) => f.properties.footprint)
      .map((f) => ({
        type: "Feature",
        geometry: f.properties.footprint as Geometry,
        properties: { norad_id: f.properties.norad_id },
      })),
  };
}

// Shape-or-circle point props: when the atlas exists, render the icon (with optional heading
// rotation); otherwise keep the circle fallback with the same de-collided colors. A single
// (non-union) type so it spreads cleanly into the GeoJsonLayer constructor.
type PointStyleProps = {
  pointType: "icon" | "circle";
  iconAtlas?: string;
  iconMapping?: typeof ICON_MAPPING;
  getIcon?: (f: Feature) => IconName;
  getIconSize?: number;
  iconSizeUnits?: "pixels";
  getIconAngle?: (f: Feature) => number;
  pointRadiusUnits?: "pixels";
  getPointRadius?: number;
  getFillColor?: (f: Feature) => [number, number, number] | [number, number, number, number];
};

function pointProps(opts: {
  getIcon: (f: Feature) => IconName;
  getFillColor: (f: Feature) => [number, number, number] | [number, number, number, number];
  sizePx: number;
  getAngle?: (f: Feature) => number;
}): PointStyleProps {
  const atlas = getMarkAtlas();
  if (atlas) {
    return {
      pointType: "icon",
      iconAtlas: atlas,
      iconMapping: ICON_MAPPING,
      getIcon: opts.getIcon,
      getIconSize: opts.sizePx,
      iconSizeUnits: "pixels",
      ...(opts.getAngle ? { getIconAngle: opts.getAngle } : {}),
    };
  }
  return {
    pointType: "circle",
    pointRadiusUnits: "pixels",
    getPointRadius: opts.sizePx / 4,
    getFillColor: opts.getFillColor,
  };
}

// MVTLayer is parametrized by its feature *properties* type; its accessors receive a GeoJSON
// Feature carrying those properties.
type TileProps = Record<string, unknown>;
type TileFeature = { properties: TileProps };

// Per-tileable-layer styling for the MVT fill. Mirrors the mark colors so the zoomed-out tile
// view reads the same as the per-point view.
function tileFillColor(id: LayerId): (f: TileFeature) => [number, number, number] {
  if (id === "adsb") return (f) => (f.properties.is_military ? MARK_RGB.mil : MARK_RGB.civil);
  return () => MARK_RGB.vessel; // ais
}

// Build a vector-tile layer for a high-cardinality point layer (adsb/ais). The tile server
// (Martin/pg_tileserv) serves pre-aggregated MVT tiles so we stream only what's in view
// instead of shipping every point. Picking stays on so selection/tooltips keep working.
function tileLayer(id: LayerId, props: TileLayerProps): Layer {
  return new MVTLayer<TileProps>({
    id: `${id}-tiles`,
    data: props.data,
    minZoom: props.minZoom,
    maxZoom: props.maxZoom,
    pointType: "circle",
    pointRadiusUnits: "pixels",
    getPointRadius: 3,
    getFillColor: tileFillColor(id),
    pickable: true,
  });
}

function captionLayer(id: string, captions: NsCaption[], color: [number, number, number]): Layer {
  return new TextLayer<NsCaption>({
    id,
    data: captions,
    getPosition: (d: NsCaption) => d.position,
    getText: (d: NsCaption) => d.text,
    getColor: [...color, 190] as [number, number, number, number],
    getSize: 10,
    sizeUnits: "pixels",
    getPixelOffset: [10, -10],
    getTextAnchor: "start",
    getAlignmentBaseline: "bottom",
    fontFamily: "JetBrains Mono, ui-monospace, monospace",
    outlineColor: [4, 7, 14, 220],
    outlineWidth: 2,
    fontSettings: { sdf: true },
  });
}

export function buildLayers(
  data: LayerData,
  visibility: Visibility,
  track?: FeatureCollection,
  zoom?: number,
): Layer[] {
  const layers: Layer[] = [];

  // Vector-tile switch (H19.5.1): when zoomed out far enough AND a tile URL is configured,
  // render server-aggregated MVT tiles for adsb/ais instead of per-point scatter. With no
  // tile URL set this is always false, so the point rendering is unchanged (a no-op).
  const tileProps = buildTileLayerProps();
  const useTiles = (id: LayerId): boolean =>
    tileProps != null && zoom != null && shouldUseTiles(zoom) && (id === "adsb" || id === "ais");

  // Selected-entity trail (a LineString path), drawn under the live points.
  if (track && track.features.length > 0) {
    layers.push(
      new GeoJsonLayer({
        id: "track",
        data: track,
        stroked: true,
        filled: false,
        getLineColor: [...TRAIL, 220] as [number, number, number, number],
        lineWidthMinPixels: 2,
      }),
    );
  }

  if (visibility.adsb) {
    if (useTiles("adsb") && tileProps) {
      layers.push(tileLayer("adsb", tileProps));
    } else {
      layers.push(
        new GeoJsonLayer({
          id: "adsb",
          data: data.adsb,
          pickable: true,
          ...pointProps({
            getIcon: (f) => (f.properties.is_military ? "mil" : "civil"),
            getFillColor: (f) => (f.properties.is_military ? MARK_RGB.mil : MARK_RGB.civil),
            sizePx: 14,
            // Chevrons point along the aircraft's track (deck rotates CCW; headings are CW).
            getAngle: (f) => -Number(f.properties.track_deg ?? 0),
          }),
        }),
      );
    }
  }

  if (visibility.ais) {
    if (useTiles("ais") && tileProps) {
      layers.push(tileLayer("ais", tileProps));
    } else {
      layers.push(
        new GeoJsonLayer({
          id: "ais",
          data: data.ais,
          pickable: true,
          ...pointProps({
            getIcon: () => "vessel",
            getFillColor: () => MARK_RGB.vessel,
            sizePx: 12,
          }),
        }),
      );
    }
  }

  if (visibility.tle) {
    layers.push(
      new GeoJsonLayer({
        id: "tle-footprint",
        data: footprintCollection(data.tle),
        filled: true,
        getFillColor: [...MARK_RGB.sat, 40] as [number, number, number, number],
        getLineColor: [...MARK_RGB.sat, 160] as [number, number, number, number],
        lineWidthMinPixels: 1,
      }),
      new GeoJsonLayer({
        id: "tle",
        data: data.tle,
        pickable: true,
        ...pointProps({
          getIcon: () => "sat",
          getFillColor: () => MARK_RGB.sat,
          sizePx: 18,
        }),
      }),
    );
  }

  if (visibility.ew) {
    layers.push(
      new GeoJsonLayer({
        id: "ew",
        data: data.ew,
        filled: true,
        getFillColor: (f: Feature) => {
          const i = Number(f.properties.intensity ?? 0);
          return [255, Math.round(180 * (1 - i)) + 40, 40, 120];
        },
        getLineColor: [255, 140, 40, 200],
        lineWidthMinPixels: 1,
        pickable: true,
      }),
    );
  }

  if (visibility.context) {
    layers.push(
      new GeoJsonLayer({
        id: "context",
        data: data.context,
        filled: true,
        pickable: true,
        getLineColor: [...MARK_RGB.intel, 200] as [number, number, number, number],
        lineWidthMinPixels: 1,
        ...pointProps({
          getIcon: (f) => (f.properties.kind === "dark_vessel" ? "dark" : "intel"),
          getFillColor: (f) =>
            f.properties.kind === "dark_vessel"
              ? MARK_RGB.dark
              : ([...MARK_RGB.intel, 60] as [number, number, number, number]),
          sizePx: 16,
        }),
      }),
    );

    // Annotation/callout layer: label notable events with their category on the map.
    layers.push(
      new TextLayer<Feature>({
        id: "context-callouts",
        data: eventCallouts(data.context),
        getPosition: calloutPosition,
        getText: (f: Feature) => String(f.properties.category ?? "event"),
        getColor: [...CALLOUT, 230] as [number, number, number, number],
        getSize: 12,
        sizeUnits: "pixels",
        getPixelOffset: [8, -8],
        getTextAnchor: "start",
        getAlignmentBaseline: "bottom",
        fontWeight: 600,
        outlineColor: [4, 7, 14, 200],
        outlineWidth: 2,
        fontSettings: { sdf: true },
      }),
    );

    // The negative-space grammar (spec §5.0): the dark-vessel story rendered as evidence —
    // ghost ring at the last fix, dashed dead-reckoned path, faint uncertainty cone, mono
    // captions — plus dashed outlines for backend-flagged voided zones. None of it animates.
    const ns = buildNegativeSpace(data.context);
    if (ns.cones.features.length > 0) {
      layers.push(
        new GeoJsonLayer({
          id: "ns-cones",
          data: ns.cones,
          filled: true,
          stroked: true,
          getFillColor: [...MARK_RGB.dark, 12] as [number, number, number, number],
          getLineColor: [...MARK_RGB.dark, 45] as [number, number, number, number],
          lineWidthMinPixels: 1,
        }),
      );
    }
    if (ns.drPaths.features.length > 0) {
      layers.push(
        new GeoJsonLayer({
          id: "ns-dr-paths",
          data: ns.drPaths,
          stroked: true,
          filled: false,
          getLineColor: [...MARK_RGB.dark, 140] as [number, number, number, number],
          lineWidthMinPixels: 1.5,
        }),
      );
    }
    if (ns.ghosts.features.length > 0) {
      layers.push(
        new GeoJsonLayer({
          id: "ns-ghosts",
          data: ns.ghosts,
          ...pointProps({
            getIcon: () => "ghost",
            getFillColor: () => [...MARK_RGB.dark, 140] as [number, number, number, number],
            sizePx: 16,
          }),
        }),
      );
    }
    if (ns.voidZones.features.length > 0) {
      layers.push(
        new GeoJsonLayer({
          id: "ns-void-zones",
          data: ns.voidZones,
          filled: false,
          stroked: true,
          getLineColor: [...INK, 36] as [number, number, number, number],
          lineWidthMinPixels: 1,
        }),
      );
    }
    if (ns.captions.length > 0) {
      layers.push(captionLayer("ns-captions", ns.captions, MARK_RGB.dark));
    }
  }

  return layers;
}
