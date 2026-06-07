"use client";

import { useEffect, useState } from "react";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { fetchReconWindows, formatEta, type ReconWindow } from "@/lib/recon";

const HORIZON_SECONDS = 24 * 3600; // list passes ingressing within the next 24h

// Recon panel: upcoming predicted satellite overflights of the AOIs, with a live countdown to
// ingress tied to the master clock. Sits top-left below the LayerPanel; refetches as the master
// clock advances (bucketed to ~10s, like useEntityTrack) so the list and countdown stay in step.
export function ReconPanel() {
  const masterTime = useTimelineStore((s) => s.masterTime);
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

  return (
    <div className="pointer-events-auto absolute left-4 top-[19rem] z-10 flex w-64 flex-col gap-1 rounded-lg bg-cockpit/85 p-3 text-xs backdrop-blur">
      <div className="mb-1 font-semibold text-signal">Recon · upcoming passes</div>
      {windows.length === 0 ? (
        <div className="text-white/50">No upcoming passes</div>
      ) : (
        <ul className="flex max-h-56 flex-col gap-0.5 overflow-y-auto">
          {windows.map((w) => (
            <li
              key={`${w.norad_id}:${w.aoi_id}:${w.t_ingress}`}
              className="flex items-center gap-2 rounded px-2 py-1 text-white/85"
            >
              <span className="truncate">
                {w.sensor_type.toUpperCase()} · NORAD {w.norad_id} · {w.aoi_id} ·{" "}
                {formatEta(w.t_ingress, masterTime)} · q{w.quality.toFixed(2)}{" "}
                {w.sunlit_at_peak ? "☀" : "🌙"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
