"use client";

import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { formatEta, type ReconWindow } from "@/lib/recon";
import { Panel } from "./Panel";

// Recon panel (spec §4): upcoming predicted overflights with typographic hierarchy — what
// matters reads first (sensor + in how long), the identifiers second. Quality is judged
// (green ≥ .7, amber below); windows under q .5 dim to 55%. Countdown follows the master
// clock; the windows come from the page-level useReconWindows fetch (shared with the timeline).

export function ReconPanel({ windows }: { windows: ReconWindow[] }) {
  const masterTime = useTimelineStore((s) => s.masterTime);

  return (
    <Panel title="Recon · next passes" meta="24h horizon" maxBodyClass="max-h-[230px]">
      {windows.length === 0 ? (
        <div className="py-1 text-[10.5px] text-ink/40">
          No predicted passes in the next 24 h — or the recon API is offline.
        </div>
      ) : (
        windows.map((w) => {
          const sensor = w.sensor_type.toLowerCase();
          return (
            <div
              key={`${w.norad_id}:${w.aoi_id}:${w.t_ingress}`}
              className={`border-b border-line-2 py-2 last:border-b-0 ${w.quality < 0.5 ? "opacity-55" : ""}`}
            >
              <div className="flex items-baseline gap-2">
                <span
                  className={`rounded-[9px] px-1.5 py-0.5 font-mono text-[9px] tracking-[.1em] ${
                    sensor === "sar"
                      ? "bg-[#E8D27A]/15 text-[#E8D27A]"
                      : "bg-signal-faint text-signal-light"
                  }`}
                >
                  {w.sensor_type.toUpperCase()}
                </span>
                <span className="font-mono text-[15px] tabular-nums text-ink">
                  {formatEta(w.t_ingress, masterTime)}
                </span>
                <span
                  className={`ml-auto font-mono text-[9.5px] ${w.quality >= 0.7 ? "text-green" : "text-amber"}`}
                >
                  q {w.quality.toFixed(2)}
                </span>
              </div>
              <div className="mt-1 font-mono text-[9px] tracking-[.04em] text-ink/40">
                NORAD {w.norad_id} · {w.aoi_id.toUpperCase()} · {w.sunlit_at_peak ? "☀" : "☾"}
              </div>
            </div>
          );
        })
      )}
    </Panel>
  );
}
