import { LAYER_IDS, type LayerId } from "@/lib/layers";
import type { LayerData } from "@/lib/layerData";
import { timelineStore } from "@/lib/store/timelineStore";
import { cx, esc, mount, type Surface } from "./dom";
import { glyph, type GlyphKind } from "./glyph";
import { panel } from "./panel";

// Legend = the layer panel (spec §3.2, P1): one surface where every mark on the globe is decoded
// AND toggled. Each row shows the actual glyph the globe renders (same shapes as the billboard
// icons), the layer name, and its live count; sub-encodings (military, dark vessel) indent under
// their layer. Footer rows decode the trail + dead-reckoned path. Zero clicks to reach.

const LAYER_META: Record<
  LayerId,
  { label: string; sub: string; glyph: GlyphKind; extras: { glyph: GlyphKind; label: string }[] }
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

export function createLayerPanel(host: HTMLElement, data: () => LayerData): Surface {
  let open = true;
  const surface = mount(host, {
    actions: {
      collapse: () => {
        open = !open;
        surface.update();
      },
      toggle: (_e, _el, arg) => timelineStore.getState().toggleLayer(arg as LayerId),
      clear: () => timelineStore.getState().selectEntity(null),
    },
    render() {
      const s = timelineStore.getState();
      const layers = data();

      const rows = LAYER_IDS.map((id) => {
        const meta = LAYER_META[id];
        const on = s.layerVisibility[id];
        const extras = on
          ? meta.extras
              .map(
                (extra) => `
                  <div class="grid grid-cols-[22px_1fr] items-center gap-1.5 py-0.5 pl-[19px]">
                    ${glyph(extra.glyph)}
                    <span class="font-mono text-[9px] text-ink/40">${esc(extra.label)}</span>
                  </div>`,
              )
              .join("")
          : "";
        return `
          <div>
            <div class="grid grid-cols-[18px_22px_1fr_auto] items-center gap-1.5 py-1 ${on ? "" : "opacity-30"}">
              <button data-act="toggle" data-arg="${id}" role="checkbox" aria-checked="${on}"
                aria-label="Toggle ${esc(meta.label)}"
                class="${cx(
                  "flex h-[13px] w-[13px] items-center justify-center rounded-[3px] border text-[9px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal",
                  on ? "border-signal-dim bg-signal-faint text-signal-light" : "border-line",
                )}">${on ? "✓" : ""}</button>
              ${glyph(meta.glyph)}
              <span class="truncate">
                <span class="text-[11.5px] text-ink">${esc(meta.label)}</span>
                <span class="font-mono text-[8px] tracking-[.04em] text-ink/40">${esc(meta.sub)}</span>
              </span>
              <span class="font-mono text-[10px] tabular-nums text-ink/65">${layers[id].features.length}</span>
            </div>
            ${extras}
          </div>`;
      }).join("");

      const selected = s.selectedEntity;
      const selectedRow = selected
        ? `
          <div class="mt-1.5 flex items-center justify-between gap-2 border-t border-line-2 pt-1.5">
            <span class="text-[10.5px] text-ink/65">trail: <span class="font-mono text-signal-light">${esc(selected.id)}</span></span>
            <button data-act="clear" class="rounded-md border border-line px-2 py-0.5 font-mono text-[8.5px] tracking-[.06em] text-ink/65 hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal">CLEAR</button>
          </div>`
        : "";

      const footer = `
        <div class="grid grid-cols-[22px_1fr] items-center gap-1.5 py-0.5 pl-[19px]">
          <svg width="20" height="14" aria-hidden="true"><line x1="2" y1="7" x2="18" y2="7" stroke="#EEF1F5" stroke-width="1.4" opacity=".85" /></svg>
          <span class="font-mono text-[9px] text-ink/40">Selected trail (1h)</span>
        </div>
        <div class="grid grid-cols-[22px_1fr] items-center gap-1.5 py-0.5 pl-[19px]">
          <svg width="20" height="14" aria-hidden="true"><line x1="2" y1="7" x2="18" y2="7" stroke="#FF5A52" stroke-width="1.4" stroke-dasharray="4 3" opacity=".7" /></svg>
          <span class="font-mono text-[9px] text-ink/40">Dead-reckoned path</span>
        </div>`;

      return panel(
        { title: "Layers · Legend", meta: "decode + toggle", collapseAction: "collapse", open },
        `${rows}${footer}${selectedRow}`,
      );
    },
  });
  return surface;
}
