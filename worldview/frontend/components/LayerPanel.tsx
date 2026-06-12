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

// Swatch CSS colors mirror the globe fill colors in lib/deckLayers.ts so the legend is honest.
// Two-tone layers (aircraft mil/civ, vessels normal/dark) show both.
const SWATCHES: Record<LayerId, { c: string; t: string }[]> = {
  adsb: [
    { c: "rgb(80,180,255)", t: "civilian" },
    { c: "rgb(255,92,92)", t: "military" },
  ],
  ais: [
    { c: "rgb(120,230,180)", t: "vessel" },
    { c: "rgb(255,70,70)", t: "dark (AIS gap)" },
  ],
  tle: [{ c: "rgb(240,210,120)", t: "satellite + footprint" }],
  ew: [{ c: "rgb(255,140,40)", t: "jamming cell" }],
  context: [{ c: "rgb(230,220,255)", t: "intel / event" }],
};

export function LayerPanel() {
  const visibility = useTimelineStore((s) => s.layerVisibility);
  const toggleLayer = useTimelineStore((s) => s.toggleLayer);
  const selected = useTimelineStore((s) => s.selectedEntity);
  const selectEntity = useTimelineStore((s) => s.selectEntity);

  return (
    <div className="pointer-events-auto absolute left-4 top-4 z-10 flex w-56 flex-col gap-1 rounded-lg bg-cockpit/85 p-3 text-xs backdrop-blur">
      <div className="mb-1 font-semibold text-signal">WorldView · Layers</div>
      {LAYER_IDS.map((id) => (
        <div key={id}>
          <label className="flex cursor-pointer items-center gap-2 text-white/85">
            <input
              type="checkbox"
              checked={visibility[id]}
              onChange={() => toggleLayer(id)}
              className="accent-signal"
              aria-label={`Toggle ${LABELS[id]}`}
            />
            {LABELS[id]}
          </label>
          {/* Legend: tiny color swatches so symbols on the globe are decipherable. */}
          <div className={`ml-6 flex flex-wrap gap-x-3 gap-y-0.5 ${visibility[id] ? "" : "opacity-40"}`}>
            {SWATCHES[id].map((sw) => (
              <span key={sw.t} className="flex items-center gap-1 text-[10px] text-white/55">
                <span
                  className="inline-block h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: sw.c }}
                  aria-hidden
                />
                {sw.t}
              </span>
            ))}
          </div>
        </div>
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
      <div className="mt-1 text-[10px] text-white/45">
        click an entity to trace its path · press <kbd className="rounded bg-white/15 px-1">?</kbd> for shortcuts
      </div>
    </div>
  );
}
