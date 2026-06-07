import { GeoJsonLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import type { Geometry } from "geojson";
import type { LayerData } from "./useWorldViewData";
import type { LayerId } from "./layers";
import type { Feature, FeatureCollection } from "./types";

// Build Deck.gl layers from the per-layer FeatureCollections. Each WorldView layer maps to a
// GeoJsonLayer styled for its domain. All layers are driven by the same as-of-T data, so they
// stay in lockstep with the master clock.

type Visibility = Record<LayerId, boolean>;

const FLIGHT_MIL: [number, number, number] = [255, 92, 92];
const FLIGHT_CIV: [number, number, number] = [80, 180, 255];
const VESSEL: [number, number, number] = [120, 230, 180];
const SAT: [number, number, number] = [240, 210, 120];
const DARK: [number, number, number] = [255, 70, 70];

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

export function buildLayers(data: LayerData, visibility: Visibility): Layer[] {
  const layers: Layer[] = [];

  if (visibility.adsb) {
    layers.push(
      new GeoJsonLayer({
        id: "adsb",
        data: data.adsb,
        pointType: "circle",
        pointRadiusUnits: "pixels",
        getPointRadius: 3,
        getFillColor: (f: Feature) => (f.properties.is_military ? FLIGHT_MIL : FLIGHT_CIV),
        pickable: true,
      }),
    );
  }

  if (visibility.ais) {
    layers.push(
      new GeoJsonLayer({
        id: "ais",
        data: data.ais,
        pointType: "circle",
        pointRadiusUnits: "pixels",
        getPointRadius: 3,
        getFillColor: VESSEL,
        pickable: true,
      }),
    );
  }

  if (visibility.tle) {
    layers.push(
      new GeoJsonLayer({
        id: "tle-footprint",
        data: footprintCollection(data.tle),
        filled: true,
        getFillColor: [...SAT, 40] as [number, number, number, number],
        getLineColor: [...SAT, 160] as [number, number, number, number],
        lineWidthMinPixels: 1,
      }),
      new GeoJsonLayer({
        id: "tle",
        data: data.tle,
        pointType: "circle",
        pointRadiusUnits: "pixels",
        getPointRadius: 4,
        getFillColor: SAT,
        pickable: true,
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
          return [255, Math.round(180 * (1 - i)), 40, 120];
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
        pointType: "circle",
        pointRadiusUnits: "pixels",
        getPointRadius: 5,
        getFillColor: (f: Feature) =>
          f.properties.kind === "dark_vessel" ? DARK : [200, 120, 255, 60],
        getLineColor: [200, 120, 255, 200],
        lineWidthMinPixels: 1,
        pickable: true,
      }),
    );
  }

  return layers;
}
