"use client";

import { useEffect, useState } from "react";
import { fetchReconWindows, type ReconWindow } from "./recon";

const HORIZON_SECONDS = 24 * 3600;

/**
 * Upcoming recon windows over the next 24 h, refetched as the master clock advances (bucketed
 * to ~10s so a continuous clock doesn't storm the API). Shared by the recon panel and the
 * timeline's event markers so the two surfaces can't disagree.
 */
export function useReconWindows(masterTime: number): ReconWindow[] {
  const [windows, setWindows] = useState<ReconWindow[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchReconWindows({ from: masterTime, to: masterTime + HORIZON_SECONDS }).then((rows) => {
      if (!cancelled) {
        // Defensive sort by ingress; the API already orders, but keep it deterministic locally.
        setWindows([...rows].sort((a, b) => a.t_ingress - b.t_ingress));
      }
    });
    return () => {
      cancelled = true;
    };
    // Bucket the master clock to ~10s so we don't refetch on every tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Math.floor(masterTime / 10)]);

  return windows;
}
