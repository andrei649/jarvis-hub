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
    </div>
  );
}
