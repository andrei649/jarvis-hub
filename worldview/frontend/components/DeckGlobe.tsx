"use client";

import { useEffect, useState } from "react";
import DeckGL from "@deck.gl/react";
import { _GlobeView as GlobeView, FlyToInterpolator } from "@deck.gl/core";
import type { Layer, PickingInfo, Position } from "@deck.gl/core";
import { SolidPolygonLayer, PathLayer } from "@deck.gl/layers";
import Map from "react-map-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import type { LayerData } from "@/lib/useWorldViewData";
import { useEntityTrack } from "@/lib/useEntityTrack";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { buildLayers } from "@/lib/deckLayers";
import { landLayer } from "@/lib/landLayer";
import { getTooltip } from "@/lib/tooltip";
import { isLayer, type LayerId } from "@/lib/layers";
import { CameraTour } from "./CameraTour";
import type { TourStep } from "@/lib/cameraTour";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN ?? "";
// The 2.5D flat basemap is Mapbox, which needs a token. Without one we draw our own dark-earth
// backdrop (below) instead of a blank void, so the map is always visible.
const HAS_MAPBOX = MAPBOX_TOKEN.length > 0;

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

// Background layers (dark ocean sphere + landmasses + graticule) drawn beneath the data layers in
// globe mode and in the token-less 2.5D fallback, so the map always reads as Earth.
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
    landLayer(),
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

// Controlled viewState we hand to deck while a camera driver (tour / arrival fly-to) runs.
type DrivenViewState = {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch?: number;
  bearing?: number;
  transitionDuration?: number;
  transitionInterpolator?: FlyToInterpolator;
};

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
  // The tour's start/stop control lives in the AppBar (spec §2); the globe follows the store.
  const tourActive = useTimelineStore((s) => s.tour);
  const setTour = useTimelineStore((s) => s.setTour);
  const flyTo = useTimelineStore((s) => s.flyTo);
  const setFlyTo = useTimelineStore((s) => s.setFlyTo);
  // zoom drives the H19.5.1 vector-tile switch: zoomed out (+ a tile URL) → MVT tiles.
  const dataLayers = buildLayers(data, visibility, track, zoom);

  // While a tour or a one-shot arrival fly-to runs we control the deck viewState (FlyTo-animated).
  // When idle, viewState is undefined so deck stays uncontrolled (initialViewState + user control).
  const [viewState, setViewState] = useState<DrivenViewState | undefined>(undefined);
  const baseViewState = viewMode === "globe" ? GLOBE_VIEW_STATE : INITIAL_VIEW_STATE;

  function onTourViewState(vs: TourStep["viewState"]) {
    setViewState({
      ...baseViewState,
      ...vs,
      transitionInterpolator: new FlyToInterpolator({ speed: 1.2 }),
    });
  }

  // Arrival deep link (spec §5.1): consume the one-shot fly-to so the camera lands on the entity.
  useEffect(() => {
    if (!flyTo) return;
    setViewState({
      ...baseViewState,
      longitude: flyTo.longitude,
      latitude: flyTo.latitude,
      zoom: flyTo.zoom,
      transitionDuration: 1200,
      transitionInterpolator: new FlyToInterpolator({ speed: 1.2 }),
    });
    setFlyTo(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flyTo]);

  // Tour stopped (app bar / user interaction) → hand camera control back to the user.
  useEffect(() => {
    if (!tourActive) setViewState(undefined);
  }, [tourActive]);

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

  function onViewStateChange(e: { viewState: unknown; interactionState?: { isZooming?: boolean; isPanning?: boolean; isRotating?: boolean } }) {
    const vs = e.viewState as { zoom?: number };
    if (typeof vs.zoom === "number" && vs.zoom !== useTimelineStore.getState().zoom) {
      // Deck can emit onViewStateChange during its own render while viewState is
      // controlled (camera tour / fly-to). Defer the store write so we never update
      // a zoom subscriber (LOD selector / bar) while DeckGL is rendering.
      queueMicrotask(() => setZoom(vs.zoom as number));
    }
    // A user drag/zoom/rotate cancels any camera driver and hands control back.
    const i = e.interactionState;
    const userMoved = i && (i.isZooming || i.isPanning || i.isRotating);
    if (userMoved) {
      if (tourActive) setTour(false);
      setViewState(undefined);
    } else if (tourActive) {
      // Keep our controlled viewState in sync with deck's in-flight interpolation.
      setViewState(e.viewState as DrivenViewState);
    }
  }

  const tourControl = <CameraTour onViewState={onTourViewState} />;

  // While a camera driver is active we pass controlled viewState; otherwise leave deck uncontrolled.
  const controlledProps = viewState ? { viewState } : { initialViewState: baseViewState };

  if (viewMode === "globe") {
    // GlobeView: no Mapbox basemap (it can't render under a globe). Draw the data
    // on a dark earth sphere; the controller keeps onViewStateChange→setZoom live.
    return (
      <>
        {tourControl}
        <DeckGL
          views={new GlobeView({ resolution: 1 })}
          {...controlledProps}
          controller={true}
          layers={[...backgroundLayers(), ...dataLayers]}
          onClick={onClick}
          onViewStateChange={onViewStateChange}
          getTooltip={getTooltip}
        />
        {/* Basemap status (spec §4, designed): the dark earth is ours by principle. */}
        <div className="pointer-events-none absolute bottom-1.5 left-3.5 z-[5] font-mono text-[8.5px] tracking-[.1em] text-ink/30">
          BASEMAP · WORLDVIEW DARK EARTH — MAPBOX UNUSED IN GLOBE PROJECTION
        </div>
      </>
    );
  }

  // Flat (2.5D) map. With a Mapbox token, use the Mapbox basemap. Without one, draw the data on the
  // same dark-earth + graticule backdrop the globe uses (so it's never a blank void) and say so.
  return (
    <>
      {tourControl}
      <DeckGL
        {...controlledProps}
        controller={true}
        layers={HAS_MAPBOX ? dataLayers : [...backgroundLayers(), ...dataLayers]}
        onClick={onClick}
        onViewStateChange={onViewStateChange}
        getTooltip={getTooltip}
      >
        {HAS_MAPBOX && (
          <Map
            reuseMaps
            mapboxAccessToken={MAPBOX_TOKEN}
            mapStyle="mapbox://styles/mapbox/dark-v11"
          />
        )}
      </DeckGL>
      {!HAS_MAPBOX && (
        // Basemap status, actionable (UX review P2#8): exact env var, where it goes, and the
        // no-token alternative. Bottom edge of the stage, clear of both rails.
        <div className="pointer-events-none absolute bottom-1.5 left-3.5 z-[5] max-w-lg font-mono text-[8.5px] leading-relaxed tracking-[.06em] text-amber/70">
          BASEMAP · COASTLINES (NO MAPBOX TOKEN) — add{" "}
          <span className="text-amber">NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN=pk…</span> to{" "}
          <span className="text-amber">frontend/.env.local</span> + restart for street tiles, or
          switch to 3D GLOBE (no token needed)
        </div>
      )}
    </>
  );
}
