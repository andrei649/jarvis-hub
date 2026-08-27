import { LAYER_IDS, type LayerId } from "./layers";
import { emptyCollection, type FeatureCollection } from "./types";

/** The per-layer FeatureCollections currently on the globe, keyed by layer id. */
export type LayerData = Record<LayerId, FeatureCollection>;

/** An all-layers-empty snapshot — the state before the first fetch/snapshot lands. */
export function emptyLayerData(): LayerData {
  return LAYER_IDS.reduce((acc, id) => ({ ...acc, [id]: emptyCollection() }), {} as LayerData);
}

/**
 * The id a feature is tracked by, across every layer's differing identity column. Falls back
 * through the known identity properties so live deltas and historical rows key identically.
 */
export function entityId(feature: { properties: Record<string, unknown> | null }): string {
  const p = feature.properties ?? {};
  return String(p.entity_id ?? p.icao24 ?? p.mmsi ?? p.norad_id ?? p.h3_index ?? p.id ?? "");
}
