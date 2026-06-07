"use client";

import { LAYER_IDS, type LayerId } from "@/lib/layers";
import { useTimelineStore } from "@/lib/store/useTimelineStore";

const LABELS: Record<LayerId, string> = {
  adsb: "Aircraft (ADS-B)",
  ais: "Vessels (AIS)",
  tle: "Satellites (SGP4)",
  ew: "GPS Jamming (H3)",
  context: "Intel / Dark Vessels",
};

export function LayerPanel() {
  const visibility = useTimelineStore((s) => s.layerVisibility);
  const toggleLayer = useTimelineStore((s) => s.toggleLayer);
  const selected = useTimelineStore((s) => s.selectedEntity);
  const selectEntity = useTimelineStore((s) => s.selectEntity);

  return (
    <div className="pointer-events-auto absolute left-4 top-4 z-10 flex flex-col gap-1 rounded-lg bg-cockpit/85 p-3 text-xs backdrop-blur">
      <div className="mb-1 font-semibold text-signal">WorldView · Layers</div>
      {LAYER_IDS.map((id) => (
        <label key={id} className="flex cursor-pointer items-center gap-2 text-white/80">
          <input
            type="checkbox"
            checked={visibility[id]}
            onChange={() => toggleLayer(id)}
            className="accent-signal"
          />
          {LABELS[id]}
        </label>
      ))}

      {selected && (
        <div className="mt-2 flex items-center justify-between gap-2 border-t border-white/10 pt-2 text-white/70">
          <span>
            trail: <span className="font-mono text-signal">{selected.id}</span>
          </span>
          <button
            onClick={() => selectEntity(null)}
            className="rounded bg-white/10 px-2 py-0.5 hover:bg-white/20"
          >
            clear
          </button>
        </div>
      )}
      <div className="mt-1 text-[10px] text-white/40">click an entity to trace its path</div>
    </div>
  );
}
