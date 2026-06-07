import type {
  Feature as GeoFeature,
  FeatureCollection as GeoFeatureCollection,
  Geometry,
} from "geojson";

// Layer features carry arbitrary properties from the API; geometry is always present.
export type Feature = GeoFeature<Geometry, Record<string, unknown>>;
export type FeatureCollection = GeoFeatureCollection<Geometry, Record<string, unknown>>;

export function emptyCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

export type BBox = [number, number, number, number]; // w, s, e, n
