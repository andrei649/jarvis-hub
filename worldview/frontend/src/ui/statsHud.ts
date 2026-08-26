import { LAYER_IDS, type LayerId } from "@/lib/layers";
import type { LayerData } from "@/lib/layerData";
import { timelineStore, type FetchStatus } from "@/lib/store/timelineStore";
import { esc, mount, type Surface } from "./dom";
import { glyph, type GlyphKind } from "./glyph";
import { panel } from "./panel";

const META: Record<LayerId, { label: string; glyph: GlyphKind }> = {
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

// "On globe" overview (spec §3.4): glyph + label + tabular count per layer; the connection badge
// lives in the app bar, so this panel only adds per-layer detail and the dark strip.
export function createStatsHud(host: HTMLElement, data: () => LayerData): Surface {
  return mount(host, {
    render() {
      const s = timelineStore.getState();
      const layers = data();

      const rows = LAYER_IDS.map((id) => {
        const status = s.mode === "historical" ? STATUS[s.layerStatus[id]] : null;
        const statusHtml = status
          ? `<span class="font-mono text-[9px] ${status.cls}" title="${status.label}" aria-label="${esc(META[id].label)}: ${status.label}">${status.sym} ${status.label}</span>`
          : "";
        return `
          <div class="grid grid-cols-[20px_1fr_auto] items-center gap-2 py-1">
            ${glyph(META[id].glyph)}
            <span class="text-[11px] text-ink/65">${esc(META[id].label)}</span>
            <span class="flex items-center gap-1.5">
              ${statusHtml}
              <span class="font-mono text-[12px] tabular-nums text-ink">${layers[id].features.length}</span>
            </span>
          </div>`;
      }).join("");

      const darkCount = layers.context.features.filter((f) => f.properties.kind === "dark_vessel").length;
      const darkStrip =
        darkCount > 0
          ? `<div role="alert" class="mt-2 flex items-center gap-2 rounded-md border border-red/35 bg-red/10 px-2.5 py-1.5 font-mono text-[10px] text-red">⚠ ${darkCount} dark vessel${darkCount > 1 ? "s" : ""} detected</div>`
          : "";

      return panel({ title: "On globe", meta: s.mode === "live" ? "tick 1s" : "as-of T" }, `${rows}${darkStrip}`);
    },
  });
}
