import { fetchReconWindows, type ReconWindow } from "@/lib/recon";
import { timelineStore } from "@/lib/store/timelineStore";

// Upcoming recon windows over the next 24 h, refetched as the master clock advances (bucketed
// to ~10 s so a continuous clock doesn't storm the API). One fetch feeds both the recon panel
// and the timeline's event markers, so the two surfaces can't disagree.

const HORIZON_SECONDS = 24 * 3600;
const TIME_BUCKET_SECONDS = 10;

export interface ReconController {
  get(): ReconWindow[];
  subscribe(listener: (windows: ReconWindow[]) => void): () => void;
  destroy(): void;
}

export function createReconController(): ReconController {
  let windows: ReconWindow[] = [];
  const listeners = new Set<(windows: ReconWindow[]) => void>();
  let token = 0;
  let lastBucket = Number.NaN;

  function refresh() {
    const masterTime = timelineStore.getState().masterTime;
    const bucket = Math.floor(masterTime / TIME_BUCKET_SECONDS);
    if (bucket === lastBucket) return;
    lastBucket = bucket;
    const mine = ++token;
    void fetchReconWindows({ from: masterTime, to: masterTime + HORIZON_SECONDS }).then((rows) => {
      if (mine !== token) return;
      // Defensive sort by ingress; the API already orders, but keep it deterministic locally.
      windows = [...rows].sort((a, b) => a.t_ingress - b.t_ingress);
      for (const listener of listeners) listener(windows);
    });
  }

  const unsubscribe = timelineStore.subscribe(refresh);
  refresh();

  return {
    get: () => windows,
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
