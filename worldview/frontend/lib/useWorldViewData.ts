import { useEffect, useRef, useState } from "react";
import { LAYER_IDS, type LayerId } from "./layers";
import { fetchHistory, openLiveSocket } from "./api";
import { emptyCollection, type Feature, type FeatureCollection, type Lod } from "./types";
import { useTimelineStore } from "./store/useTimelineStore";

export type LayerData = Record<LayerId, FeatureCollection>;

// Below this zoom, request 1-minute rollups for the dense point layers (design doc §8.3).
const ZOOM_LOD_THRESHOLD = 5;

function lodFor(layer: LayerId, lowZoom: boolean): Lod {
  return lowZoom && (layer === "adsb" || layer === "ais") ? "minute" : "raw";
}

function emptyLayerData(): LayerData {
  return LAYER_IDS.reduce(
    (acc, id) => ({ ...acc, [id]: emptyCollection() }),
    {} as LayerData,
  );
}

function entityId(feature: { properties: Record<string, unknown> }): string {
  const p = feature.properties;
  return String(p.entity_id ?? p.icao24 ?? p.mmsi ?? p.norad_id ?? p.h3_index ?? p.id ?? "");
}

/**
 * The single source of layer data for the globe. In historical mode it debounces a REST
 * fetch per visible layer on master-time change; in live mode it opens the WebSocket and
 * merges snapshot + deltas. Everything is keyed off the Zustand master clock (design doc §8).
 */
export function useWorldViewData(): LayerData {
  const [data, setData] = useState<LayerData>(emptyLayerData);
  const mode = useTimelineStore((s) => s.mode);
  const masterTime = useTimelineStore((s) => s.masterTime);
  const visibility = useTimelineStore((s) => s.layerVisibility);
  // Only re-render/refetch when crossing the zoom threshold, not on every zoom delta.
  const lowZoom = useTimelineStore((s) => s.zoom < ZOOM_LOD_THRESHOLD);

  // Historical mode: debounced as-of-T fetch for each visible layer.
  useEffect(() => {
    if (mode !== "historical") return;
    const handle = setTimeout(() => {
      const visible = LAYER_IDS.filter((id) => visibility[id]);
      void Promise.all(
        visible.map((id) => fetchHistory(id, masterTime, undefined, lodFor(id, lowZoom))),
      ).then((results) => {
        setData((prev) => {
          const next = { ...prev };
          visible.forEach((id, i) => {
            next[id] = results[i] ?? emptyCollection();
          });
          return next;
        });
      });
    }, 150);
    return () => clearTimeout(handle);
    // Bucket master time to whole seconds so sub-second clock ticks don't spam fetches.
  }, [mode, Math.floor(masterTime), visibility, lowZoom]);

  // Live mode: WebSocket snapshot + deltas merged into per-entity maps.
  const liveMaps = useRef<Record<LayerId, Map<string, unknown>>>(
    LAYER_IDS.reduce((acc, id) => ({ ...acc, [id]: new Map() }), {} as Record<LayerId, Map<string, unknown>>),
  );

  useEffect(() => {
    if (mode !== "live") return;
    const ws = openLiveSocket([...LAYER_IDS], {
      onSnapshot: (layer, fc) => {
        const map = liveMaps.current[layer];
        map.clear();
        for (const f of fc.features) map.set(entityId(f), f);
        flush(layer);
      },
      onDelta: (layer, env) => {
        const map = liveMaps.current[layer];
        const id = String((env.entity_id as string) ?? "");
        if (env.lon != null && env.lat != null) {
          const feature: Feature = {
            type: "Feature",
            geometry: { type: "Point", coordinates: [Number(env.lon), Number(env.lat)] },
            properties: { entity_id: id, ...((env.payload as Record<string, unknown>) ?? {}) },
          };
          map.set(id, feature);
        }
        flush(layer);
      },
    });

    function flush(layer: LayerId) {
      const features = Array.from(liveMaps.current[layer].values()) as FeatureCollection["features"];
      setData((prev) => ({ ...prev, [layer]: { type: "FeatureCollection", features } }));
    }

    return () => ws.close();
  }, [mode]);

  return data;
}
