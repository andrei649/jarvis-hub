"use client";

import type { LayerData } from "@/lib/useWorldViewData";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import type { LayerId } from "@/lib/layers";

// The property holding each layer's entity id (to match the selection back to its feature).
const ID_PROP: Record<LayerId, string> = {
  adsb: "icao24",
  ais: "mmsi",
  tle: "norad_id",
  ew: "h3_index",
  context: "entity_id",
};

// Bottom-left detail card for the currently selected entity (richer than the hover tooltip).
export function Inspector({ data }: { data: LayerData }) {
  const selected = useTimelineStore((s) => s.selectedEntity);
  const selectEntity = useTimelineStore((s) => s.selectEntity);
  if (!selected) return null;

  const idProp = ID_PROP[selected.layer];
  const feature = data[selected.layer].features.find(
    (f) => String(f.properties[idProp] ?? f.properties.entity_id ?? "") === selected.id,
  );
  const props = feature?.properties ?? {};
  const entries = Object.entries(props).filter(([k]) => k !== "coordTimes" && k !== "footprint");

  return (
    <div className="pointer-events-auto absolute bottom-24 left-4 z-10 w-64 rounded-lg bg-cockpit/90 p-3 text-xs backdrop-blur">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold text-signal">
          {selected.layer.toUpperCase()} · {selected.id}
        </span>
        <button
          onClick={() => selectEntity(null)}
          className="rounded bg-white/10 px-1.5 leading-5 hover:bg-white/20"
        >
          ×
        </button>
      </div>
      {feature ? (
        <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5">
          {entries.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-white/45">{k}</dt>
              <dd className="truncate text-right font-mono text-white/85">{render(v)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="text-white/50">no data at the current time — scrub to where it was active</div>
      )}
    </div>
  );
}

function render(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") return String(Math.round(v * 1000) / 1000);
  return String(v);
}
