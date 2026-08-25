import { LAYER_IDS, type LayerId } from "@/lib/layers";
import { fetchHistoryResult, openLiveSocket, type LiveSocket } from "@/lib/api";
import { emptyLayerData, entityId, type LayerData } from "@/lib/layerData";
import { emptyCollection, type Feature, type FeatureCollection, type Lod } from "@/lib/types";
import { timelineStore } from "@/lib/store/timelineStore";

// The single source of layer data for the globe and the panels.
//
// Historical mode debounces an as-of-T REST fetch per visible layer on master-time change; live
// mode opens the WebSocket and merges snapshot + deltas into per-entity maps. Everything is
// keyed off the master clock (design doc §8), so every surface shows the same instant.

/** Below this zoom, request 1-minute rollups for the dense point layers (design doc §8.3). */
const ZOOM_LOD_THRESHOLD = 5;
const FETCH_DEBOUNCE_MS = 150;

function lodFor(layer: LayerId, lowZoom: boolean): Lod {
  return lowZoom && (layer === "adsb" || layer === "ais") ? "minute" : "raw";
}

export interface DataController {
  /** The current per-layer FeatureCollections. */
  get(): LayerData;
  /** Called after every data change; returns an unsubscribe. */
  subscribe(listener: (data: LayerData) => void): () => void;
  destroy(): void;
}

export function createDataController(): DataController {
  let data = emptyLayerData();
  const listeners = new Set<(data: LayerData) => void>();
  const liveMaps = new Map<LayerId, Map<string, Feature>>(
    LAYER_IDS.map((id) => [id, new Map<string, Feature>()]),
  );

  let socket: LiveSocket | null = null;
  let debounce: ReturnType<typeof setTimeout> | null = null;
  let historyToken = 0;

  function emit() {
    for (const listener of listeners) listener(data);
  }

  function set(next: LayerData) {
    data = next;
    emit();
  }

  // --- historical (REST, as-of-T) -----------------------------------------

  function scheduleHistoryFetch() {
    if (debounce != null) clearTimeout(debounce);
    debounce = setTimeout(runHistoryFetch, FETCH_DEBOUNCE_MS);
  }

  function runHistoryFetch() {
    debounce = null;
    const state = timelineStore.getState();
    if (state.mode !== "historical") return;
    const visible = LAYER_IDS.filter((id) => state.layerVisibility[id]);
    if (visible.length === 0) return;
    const token = ++historyToken;
    const lowZoom = state.zoom < ZOOM_LOD_THRESHOLD;
    for (const id of visible) state.setLayerStatus(id, "loading");
    void Promise.all(
      visible.map((id) =>
        fetchHistoryResult(id, state.masterTime, undefined, lodFor(id, lowZoom)),
      ),
    ).then((results) => {
      // A newer scrub has started: its fetch owns the screen, drop this one.
      if (token !== historyToken) return;
      const next = { ...data };
      visible.forEach((id, i) => {
        next[id] = results[i]?.data ?? emptyCollection();
      });
      set(next);
      visible.forEach((id, i) => {
        timelineStore.getState().setLayerStatus(id, results[i]?.outcome ?? "error");
      });
    });
  }

  // --- live (WebSocket snapshot + deltas) ----------------------------------

  function flush(layer: LayerId) {
    const features = Array.from(liveMaps.get(layer)?.values() ?? []);
    set({ ...data, [layer]: { type: "FeatureCollection", features } as FeatureCollection });
  }

  function openLive() {
    // Clear any per-entity maps left over from a previous live session so stale entities don't
    // render as ghosts before the first fresh snapshot arrives.
    for (const map of liveMaps.values()) map.clear();
    socket = openLiveSocket([...LAYER_IDS], {
      onConnectionChange: (state) => timelineStore.getState().setLiveConnection(state),
      onSnapshot: (layer, fc) => {
        const map = liveMaps.get(layer);
        if (!map) return;
        map.clear();
        for (const f of fc.features) map.set(entityId(f), f);
        flush(layer);
      },
      onDelta: (layer, envelope) => {
        const map = liveMaps.get(layer);
        if (!map) return;
        const id = String(envelope.entity_id ?? "");
        if (envelope.lon != null && envelope.lat != null) {
          map.set(id, {
            type: "Feature",
            geometry: {
              type: "Point",
              coordinates: [Number(envelope.lon), Number(envelope.lat)],
            },
            properties: {
              entity_id: id,
              ...((envelope.payload as Record<string, unknown>) ?? {}),
            },
          });
        }
        flush(layer);
      },
    });
  }

  function closeLive() {
    socket?.close();
    socket = null;
  }

  // --- store wiring --------------------------------------------------------

  let lastMode = timelineStore.getState().mode;
  let lastSecond = Math.floor(timelineStore.getState().masterTime);
  let lastVisibility = timelineStore.getState().layerVisibility;
  let lastLowZoom = timelineStore.getState().zoom < ZOOM_LOD_THRESHOLD;

  const unsubscribe = timelineStore.subscribe((state) => {
    const second = Math.floor(state.masterTime);
    const lowZoom = state.zoom < ZOOM_LOD_THRESHOLD;

    if (state.mode !== lastMode) {
      lastMode = state.mode;
      if (state.mode === "live") {
        openLive();
      } else {
        closeLive();
        scheduleHistoryFetch();
      }
    }

    if (state.mode === "historical") {
      // Bucket master time to whole seconds so sub-second clock ticks don't spam fetches.
      const changed =
        second !== lastSecond || state.layerVisibility !== lastVisibility || lowZoom !== lastLowZoom;
      if (changed) scheduleHistoryFetch();
    }

    lastSecond = second;
    lastVisibility = state.layerVisibility;
    lastLowZoom = lowZoom;
  });

  if (timelineStore.getState().mode === "live") openLive();
  else scheduleHistoryFetch();

  return {
    get: () => data,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    destroy() {
      unsubscribe();
      closeLive();
      if (debounce != null) clearTimeout(debounce);
      listeners.clear();
    },
  };
}
