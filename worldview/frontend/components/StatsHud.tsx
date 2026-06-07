"use client";

import type { LayerData } from "@/lib/useWorldViewData";
import { LAYER_IDS, type LayerId } from "@/lib/layers";

const LABELS: Record<LayerId, string> = {
  adsb: "Aircraft",
  ais: "Vessels",
  tle: "Satellites",
  ew: "Jam cells",
  context: "Intel",
};

// Top-right command-center overview: live feature counts per layer + a dark-vessel alert.
export function StatsHud({ data }: { data: LayerData }) {
  const darkCount = data.context.features.filter(
    (f) => f.properties.kind === "dark_vessel",
  ).length;

  return (
    <div className="pointer-events-none absolute right-4 top-4 z-10 flex flex-col gap-1 rounded-lg bg-cockpit/85 p-3 text-xs backdrop-blur">
      <div className="mb-1 font-semibold text-signal">On globe</div>
      {LAYER_IDS.map((id) => (
        <div key={id} className="flex items-center justify-between gap-6 text-white/80">
          <span>{LABELS[id]}</span>
          <span className="font-mono tabular-nums">{data[id].features.length}</span>
        </div>
      ))}
      {darkCount > 0 && (
        <div className="mt-2 rounded bg-red-500/20 px-2 py-1 font-medium text-red-300">
          ⚠ {darkCount} dark vessel{darkCount > 1 ? "s" : ""} detected
        </div>
      )}
    </div>
  );
}
