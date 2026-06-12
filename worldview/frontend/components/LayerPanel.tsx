"use client";

import type { LayerData } from "@/lib/useWorldViewData";
import { LAYER_IDS, type LayerId } from "@/lib/layers";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { Panel } from "./Panel";
import { MarkGlyph } from "./MarkGlyph";
import type { MarkKind } from "@/lib/markStyle";

// Legend = the layer panel (spec §3.2, P1): one surface where every mark on the map is decoded
// AND toggled. Each row shows the actual glyph the map renders (same SVG source as the deck
// icon atlas), the layer name, and its live count; sub-encodings (military, dark vessel) indent
// under their layer. Footer rows decode the trail + dead-reckoned path. Zero clicks to reach.

const LAYER_META: Record<
  LayerId,
  { label: string; sub: string; glyph: MarkKind | "hex"; extras: { glyph: MarkKind; label: string }[] }
> = {
  adsb: {
    label: "Aircraft",
    sub: "ADS-B",
    glyph: "civil",
    extras: [{ glyph: "mil", label: "Military (hollow)" }],
  },
  ais: {
    label: "Vessels",
    sub: "AIS",
    glyph: "vessel",
    extras: [{ glyph: "dark", label: "Dark vessel (AIS gap)" }],
  },
  tle: { label: "Satellites", sub: "SGP4", glyph: "sat", extras: [] },
  ew: { label: "GPS jamming", sub: "H3 cells", glyph: "hex", extras: [] },
  context: { label: "Intel", sub: "events · zones", glyph: "intel", extras: [] },
};

export function LayerPanel({ data }: { data: LayerData }) {
  const visibility = useTimelineStore((s) => s.layerVisibility);
  const toggleLayer = useTimelineStore((s) => s.toggleLayer);
  const selected = useTimelineStore((s) => s.selectedEntity);
  const selectEntity = useTimelineStore((s) => s.selectEntity);

  return (
    <Panel title="Layers · Legend" meta="decode + toggle" collapsible>
      {LAYER_IDS.map((id) => {
        const m = LAYER_META[id];
        const on = visibility[id];
        return (
          <div key={id}>
            <div className={`grid grid-cols-[18px_22px_1fr_auto] items-center gap-1.5 py-1 ${on ? "" : "opacity-30"}`}>
              <button
                onClick={() => toggleLayer(id)}
                role="checkbox"
                aria-checked={on}
                aria-label={`Toggle ${m.label}`}
                className={`flex h-[13px] w-[13px] items-center justify-center rounded-[3px] border text-[9px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal ${
                  on ? "border-signal-dim bg-signal-faint text-signal-light" : "border-line"
                }`}
              >
                {on ? "✓" : ""}
              </button>
              <MarkGlyph kind={m.glyph} />
              <span className="truncate">
                <span className="text-[11.5px] text-ink">{m.label}</span>{" "}
                <span className="font-mono text-[8px] tracking-[.04em] text-ink/40">{m.sub}</span>
              </span>
              <span className="font-mono text-[10px] tabular-nums text-ink/65">
                {data[id].features.length}
              </span>
            </div>
            {on &&
              m.extras.map((ex) => (
                <div key={ex.label} className="grid grid-cols-[22px_1fr] items-center gap-1.5 py-0.5 pl-[19px]">
                  <MarkGlyph kind={ex.glyph} />
                  <span className="font-mono text-[9px] text-ink/40">{ex.label}</span>
                </div>
              ))}
          </div>
        );
      })}

      <div className="my-1.5 border-t border-line-2" />
      <div className="grid grid-cols-[22px_1fr] items-center gap-1.5 py-0.5 pl-[19px]">
        <svg width="20" height="14" aria-hidden>
          <line x1="2" y1="7" x2="18" y2="7" stroke="#EEF1F5" strokeWidth="1.6" opacity=".8" />
        </svg>
        <span className="font-mono text-[9px] text-ink/40">Selected trail (1h)</span>
      </div>
      <div className="grid grid-cols-[22px_1fr] items-center gap-1.5 py-0.5 pl-[19px]">
        <svg width="20" height="14" aria-hidden>
          <line x1="2" y1="7" x2="18" y2="7" stroke="#FF5A52" strokeWidth="1.4" strokeDasharray="4 3" opacity=".7" />
        </svg>
        <span className="font-mono text-[9px] text-ink/40">Dead-reckoned path</span>
      </div>

      {selected && (
        <div className="mt-1.5 flex items-center justify-between gap-2 border-t border-line-2 pt-1.5">
          <span className="text-[10.5px] text-ink/65">
            trail: <span className="font-mono text-signal-light">{selected.id}</span>
          </span>
          <button
            onClick={() => selectEntity(null)}
            className="rounded-md border border-line px-2 py-0.5 font-mono text-[8.5px] tracking-[.06em] text-ink/65 hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
          >
            CLEAR
          </button>
        </div>
      )}
    </Panel>
  );
}
