"use client";

import DeckGL from "@deck.gl/react";
import { _GlobeView as GlobeView } from "@deck.gl/core";
import type { Layer, PickingInfo, Position } from "@deck.gl/core";
import { SolidPolygonLayer, PathLayer } from "@deck.gl/layers";
import Map from "react-map-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import type { LayerData } from "@/lib/useWorldViewData";
import { useEntityTrack } from "@/lib/useEntityTrack";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { buildLayers } from "@/lib/deckLayers";
import { getTooltip } from "@/lib/tooltip";
import { isLayer, type LayerId } from "@/lib/layers";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN ?? "";

// Centered on the Strait of Hormuz — the platform's reference choke point.
const INITIAL_VIEW_STATE = {
  longitude: 56.4,
  latitude: 26.6,
  zoom: 6,
  pitch: 30,
  bearing: 0,
};

// In globe mode we zoom all the way out so the whole sphere is framed.
const GLOBE_VIEW_STATE = {
  longitude: 56.4,
  latitude: 26.6,
  zoom: 0,
};

const OCEAN: [number, number, number, number] = [10, 18, 28, 255];
const GRATICULE: [number, number, number, number] = [90, 110, 130, 60];

// A single polygon covering the whole sphere, drawn under the data so the globe
// reads as a dark earth (Mapbox can't render beneath GlobeView).
type SpherePoly = { polygon: Position[] };
const EARTH_SPHERE: SpherePoly[] = [
  {
    polygon: [
      [-180, -90],
      [180, -90],
      [180, 90],
      [-180, 90],
      [-180, -90],
    ],
  },
];

// A subtle graticule: meridians every 30°, parallels every 30°.
type GratPath = { path: Position[] };
function buildGraticule(): GratPath[] {
  const paths: GratPath[] = [];
  for (let lng = -180; lng <= 180; lng += 30) {
    const path: Position[] = [];
    for (let lat = -90; lat <= 90; lat += 5) path.push([lng, lat]);
    paths.push({ path });
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const path: Position[] = [];
    for (let lng = -180; lng <= 180; lng += 5) path.push([lng, lat]);
    paths.push({ path });
  }
  return paths;
}
const GRATICULE_PATHS = buildGraticule();

// Background layers (dark sphere + graticule) drawn beneath the data layers in globe mode.
function backgroundLayers(): Layer[] {
  return [
    new SolidPolygonLayer<SpherePoly>({
      id: "earth-sphere",
      data: EARTH_SPHERE,
      getPolygon: (d) => d.polygon,
      getFillColor: OCEAN,
      filled: true,
      pickable: false,
    }),
    new PathLayer<GratPath>({
      id: "graticule",
      data: GRATICULE_PATHS,
      getPath: (d) => d.path,
      getColor: GRATICULE,
      getWidth: 1,
      widthUnits: "pixels",
      pickable: false,
    }),
  ];
}

// Layers whose features identify a trackable entity, and the property holding its id.
const TRACK_ID_PROP: Partial<Record<LayerId, string>> = {
  adsb: "icao24",
  ais: "mmsi",
  tle: "norad_id",
};

export function DeckGlobe({ data }: { data: LayerData }) {
  const track = useEntityTrack();
  const visibility = useTimelineStore((s) => s.layerVisibility);
  const selectEntity = useTimelineStore((s) => s.selectEntity);
  const setZoom = useTimelineStore((s) => s.setZoom);
  const viewMode = useTimelineStore((s) => s.viewMode);
  const zoom = useTimelineStore((s) => s.zoom);
  // zoom drives the H19.5.1 vector-tile switch: zoomed out (+ a tile URL) → MVT tiles.
  const dataLayers = buildLayers(data, visibility, track, zoom);

  function onClick(info: PickingInfo) {
    const props = (info.object as { properties?: Record<string, unknown> } | null)?.properties;
    if (!info.object || !props) {
      selectEntity(null); // clicking empty space clears the trail
      return;
    }
    const layerId = info.layer?.id;
    if (!layerId || !isLayer(layerId)) return;
    const idProp = TRACK_ID_PROP[layerId];
    const id = idProp ? props[idProp] : undefined;
    if (id != null) selectEntity({ layer: layerId, id: String(id) });
  }

  function onViewStateChange(e: { viewState: unknown }) {
    const vs = e.viewState as { zoom?: number };
    if (typeof vs.zoom === "number") setZoom(vs.zoom);
  }

  if (viewMode === "globe") {
    // GlobeView: no Mapbox basemap (it can't render under a globe). Draw the data
    // on a dark earth sphere; the controller keeps onViewStateChange→setZoom live.
    return (
      <DeckGL
        views={new GlobeView({ resolution: 1 })}
        initialViewState={GLOBE_VIEW_STATE}
        controller={true}
        layers={[...backgroundLayers(), ...dataLayers]}
        onClick={onClick}
        onViewStateChange={onViewStateChange}
        getTooltip={getTooltip}
      />
    );
  }

  return (
    <DeckGL
      initialViewState={INITIAL_VIEW_STATE}
      controller={true}
      layers={dataLayers}
      onClick={onClick}
      onViewStateChange={onViewStateChange}
      getTooltip={getTooltip}
    >
      <Map
        reuseMaps
        mapboxAccessToken={MAPBOX_TOKEN}
        mapStyle="mapbox://styles/mapbox/dark-v11"
      />
    </DeckGL>
  );
}
