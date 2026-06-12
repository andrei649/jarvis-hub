"use client";

import type { LayerData } from "@/lib/useWorldViewData";
import { LAYER_IDS, type LayerId } from "@/lib/layers";
import { useTimelineStore, type FetchStatus } from "@/lib/store/useTimelineStore";
import { Panel } from "./Panel";
import { MarkGlyph } from "./MarkGlyph";
import type { MarkKind } from "@/lib/markStyle";

const META: Record<LayerId, { label: string; glyph: MarkKind | "hex" }> = {
  adsb: { label: "Aircraft", glyph: "civil" },
  ais: { label: "Vessels", glyph: "vessel" },
  tle: { label: "Satellites", glyph: "sat" },
  ew: { label: "Jam cells", glyph: "hex" },
  context: { label: "Intel", glyph: "intel" },
};

// Per-layer fetch status (historical mode), as symbol + word — never color alone, AA contrast
// (spec §3.4). Healthy stays quiet.
const STATUS: Record<FetchStatus, { sym: string; cls: string; label: string } | null> = {
  ok: null,
  loading: { sym: "◌", cls: "text-ink/40", label: "loading" },
  empty: { sym: "—", cls: "text-amber/80", label: "empty" },
  error: { sym: "✕", cls: "text-red", label: "error" },
};

// "On globe" overview (spec §3.4): glyph + label + tabular count per layer; the connection
// badge lives in the app bar, so this panel only adds per-layer detail and the dark strip.
export function StatsHud({ data }: { data: LayerData }) {
  const mode = useTimelineStore((s) => s.mode);
  const layerStatus = useTimelineStore((s) => s.layerStatus);

  const darkCount = data.context.features.filter(
    (f) => f.properties.kind === "dark_vessel",
  ).length;

  return (
    <Panel title="On globe" meta={mode === "live" ? "tick 1s" : "as-of T"}>
      {LAYER_IDS.map((id) => {
        const st = mode === "historical" ? STATUS[layerStatus[id]] : null;
        return (
          <div key={id} className="grid grid-cols-[20px_1fr_auto] items-center gap-2 py-1">
            <MarkGlyph kind={META[id].glyph} />
            <span className="text-[11px] text-ink/65">{META[id].label}</span>
            <span className="flex items-center gap-1.5">
              {st && (
                <span
                  className={`font-mono text-[9px] ${st.cls}`}
                  title={st.label}
                  aria-label={`${META[id].label}: ${st.label}`}
                >
                  {st.sym} {st.label}
                </span>
              )}
              <span className="font-mono text-[12px] tabular-nums text-ink">
                {data[id].features.length}
              </span>
            </span>
          </div>
        );
      })}
      {darkCount > 0 && (
        <div
          role="alert"
          className="mt-2 flex items-center gap-2 rounded-md border border-red/35 bg-red/10 px-2.5 py-1.5 font-mono text-[10px] text-red"
        >
          ⚠ {darkCount} dark vessel{darkCount > 1 ? "s" : ""} detected
        </div>
      )}
    </Panel>
  );
}
