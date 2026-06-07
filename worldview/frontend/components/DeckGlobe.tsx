"use client";

import DeckGL from "@deck.gl/react";
import Map from "react-map-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useWorldViewData } from "@/lib/useWorldViewData";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { buildLayers } from "@/lib/deckLayers";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN ?? "";

// Centered on the Strait of Hormuz — the platform's reference choke point.
const INITIAL_VIEW_STATE = {
  longitude: 56.4,
  latitude: 26.6,
  zoom: 6,
  pitch: 30,
  bearing: 0,
};

export function DeckGlobe() {
  const data = useWorldViewData();
  const visibility = useTimelineStore((s) => s.layerVisibility);
  const layers = buildLayers(data, visibility);

  return (
    <DeckGL initialViewState={INITIAL_VIEW_STATE} controller={true} layers={layers}>
      <Map
        reuseMaps
        mapboxAccessToken={MAPBOX_TOKEN}
        mapStyle="mapbox://styles/mapbox/dark-v11"
      />
    </DeckGL>
  );
}
