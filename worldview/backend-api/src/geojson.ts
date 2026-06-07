import type { FeatureCollection, GeoJSONFeature } from "./types.js";

/**
 * Turn DB rows into a GeoJSON FeatureCollection. The column named `geomKey` holds a
 * GeoJSON string (from ST_AsGeoJSON) and becomes the feature geometry; everything else
 * becomes a property. Optional `extraGeomKeys` are parsed into properties (e.g. footprint).
 */
export function rowsToFeatureCollection(
  rows: Record<string, unknown>[],
  geomKey = "geojson",
  extraGeomKeys: string[] = [],
): FeatureCollection {
  const features: GeoJSONFeature[] = rows.map((row) => {
    const { [geomKey]: geom, ...rest } = row;
    const properties: Record<string, unknown> = { ...rest };
    for (const key of extraGeomKeys) {
      const value = properties[key];
      properties[key] = typeof value === "string" ? JSON.parse(value) : value;
    }
    return {
      type: "Feature",
      geometry: typeof geom === "string" ? JSON.parse(geom) : geom,
      properties,
    };
  });
  return { type: "FeatureCollection", features };
}

export function emptyCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}
