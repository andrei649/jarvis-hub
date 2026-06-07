"use client";

import DeckGL from "@deck.gl/react";
import type { PickingInfo } from "@deck.gl/core";
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
  const layers = buildLayers(data, visibility, track);

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

  return (
    <DeckGL
      initialViewState={INITIAL_VIEW_STATE}
      controller={true}
      layers={layers}
      onClick={onClick}
      onViewStateChange={(e) => {
        const vs = e.viewState as { zoom?: number };
        if (typeof vs.zoom === "number") setZoom(vs.zoom);
      }}
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
