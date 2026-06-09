import { GeoJsonLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import { feature } from "topojson-client";
import type { Topology, GeometryObject } from "topojson-specification";
import type { FeatureCollection } from "geojson";
import landTopo from "world-atlas/land-110m.json";

// Bundled Natural Earth land (110m) → GeoJSON, converted once at module load. Drawn as a subtle
// filled landmass beneath the data so the globe and the token-less 2.5D map read as Earth (real
// continents), with NO Mapbox account and NO network fetch. Low-res 110m keeps it light + fast.
const LAND = feature(
  landTopo as unknown as Topology,
  (landTopo as unknown as Topology).objects.land as GeometryObject,
) as unknown as FeatureCollection;

const LAND_FILL: [number, number, number, number] = [26, 38, 52, 255]; // dark slate land over the ocean
const LAND_LINE: [number, number, number, number] = [90, 120, 150, 150]; // faint coastline

/** A filled-land + coastline layer for the dark-earth backdrop (globe + token-less 2.5D). */
export function landLayer(): Layer {
  return new GeoJsonLayer({
    id: "land",
    data: LAND,
    filled: true,
    getFillColor: LAND_FILL,
    stroked: true,
    getLineColor: LAND_LINE,
    getLineWidth: 1,
    lineWidthUnits: "pixels",
    pickable: false,
  });
}
