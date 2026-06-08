"use client";

import type { LayerData } from "@/lib/useWorldViewData";
import { LAYER_IDS, type LayerId } from "@/lib/layers";
import { useTimelineStore, type FetchStatus } from "@/lib/store/useTimelineStore";

const LABELS: Record<LayerId, string> = {
  adsb: "Aircraft",
  ais: "Vessels",
  tle: "Satellites",
  ew: "Jam cells",
  context: "Intel",
};

// Per-layer status dot — distinguishes a genuinely empty time slice from a backend failure.
const STATUS_DOT: Record<FetchStatus, { cls: string; title: string } | null> = {
  ok: null, // healthy: no dot, keep the HUD quiet
  loading: { cls: "text-white/40", title: "loading…" },
  empty: { cls: "text-white/30", title: "no data in this time slice" },
  error: { cls: "text-red-400", title: "fetch failed (backend error / offline)" },
};

// Top-right command-center overview: live feature counts per layer + a dark-vessel alert.
export function StatsHud({ data }: { data: LayerData }) {
  const mode = useTimelineStore((s) => s.mode);
  const layerStatus = useTimelineStore((s) => s.layerStatus);
  const liveConnection = useTimelineStore((s) => s.liveConnection);

  const darkCount = data.context.features.filter(
    (f) => f.properties.kind === "dark_vessel",
  ).length;

  // In live mode the connection state is the relevant health signal; in historical it's per-layer.
  const liveBadge =
    liveConnection === "open"
      ? null
      : {
          reconnecting: { cls: "bg-amber-500/20 text-amber-300", label: "⟳ reconnecting" },
          connecting: { cls: "bg-white/10 text-white/60", label: "… connecting" },
          closed: { cls: "bg-red-500/20 text-red-300", label: "✕ disconnected" },
        }[liveConnection];

  return (
    <div className="pointer-events-none absolute right-4 top-4 z-10 flex flex-col gap-1 rounded-lg bg-cockpit/85 p-3 text-xs backdrop-blur">
      <div className="mb-1 font-semibold text-signal">On globe</div>
      {LAYER_IDS.map((id) => {
        const dot = mode === "historical" ? STATUS_DOT[layerStatus[id]] : null;
        return (
          <div key={id} className="flex items-center justify-between gap-6 text-white/80">
            <span>{LABELS[id]}</span>
            <span className="flex items-center gap-1">
              {dot && (
                <span className={dot.cls} title={dot.title} aria-label={dot.title}>
                  ●
                </span>
              )}
              <span className="font-mono tabular-nums">{data[id].features.length}</span>
            </span>
          </div>
        );
      })}
      {mode === "live" && liveBadge && (
        <div className={`mt-2 rounded px-2 py-1 font-medium ${liveBadge.cls}`}>
          {liveBadge.label}
        </div>
      )}
      {darkCount > 0 && (
        <div className="mt-2 rounded bg-red-500/20 px-2 py-1 font-medium text-red-300">
          ⚠ {darkCount} dark vessel{darkCount > 1 ? "s" : ""} detected
        </div>
      )}
    </div>
  );
}
