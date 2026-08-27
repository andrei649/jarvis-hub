import { fetchTrack } from "@/lib/api";
import { emptyCollection, type FeatureCollection } from "@/lib/types";
import { timelineStore } from "@/lib/store/timelineStore";

// The selected entity's trail over [masterTime - 1h, masterTime]. Refetched as the master clock
// advances (bucketed to ~10 s) so the trail grows in step with playback, and cleared the moment
// the selection is dropped.

const TRAIL_WINDOW_SECONDS = 3600;
const TIME_BUCKET_SECONDS = 10;

export interface TrackController {
  get(): FeatureCollection;
  subscribe(listener: (track: FeatureCollection) => void): () => void;
  destroy(): void;
}

export function createTrackController(): TrackController {
  let track: FeatureCollection = emptyCollection();
  const listeners = new Set<(track: FeatureCollection) => void>();
  let token = 0;
  let lastKey = "";

  function emit() {
    for (const listener of listeners) listener(track);
  }

  function refresh() {
    const s = timelineStore.getState();
    const selected = s.selectedEntity;
    const bucket = Math.floor(s.masterTime / TIME_BUCKET_SECONDS);
    const key = selected ? `${selected.layer}:${selected.id}:${bucket}` : "";
    if (key === lastKey) return;
    lastKey = key;

    if (!selected) {
      track = emptyCollection();
      emit();
      return;
    }
    const mine = ++token;
    void fetchTrack(
      selected.layer,
      selected.id,
      s.masterTime - TRAIL_WINDOW_SECONDS,
      s.masterTime,
    ).then((fc) => {
      if (mine !== token) return;
      track = fc;
      emit();
    });
  }

  const unsubscribe = timelineStore.subscribe(refresh);
  refresh();

  return {
    get: () => track,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    destroy() {
      unsubscribe();
      listeners.clear();
    },
  };
}
