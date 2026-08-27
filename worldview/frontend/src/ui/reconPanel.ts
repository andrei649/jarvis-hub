import { formatEta, type ReconWindow } from "@/lib/recon";
import { timelineStore } from "@/lib/store/timelineStore";
import { esc, mount, type Surface } from "./dom";
import { panel } from "./panel";

// Recon panel (spec §4): upcoming predicted overflights with typographic hierarchy — what
// matters reads first (sensor + in how long), the identifiers second. Quality is judged
// (green ≥ .7, amber below); windows under q .5 dim to 55%. Countdown follows the master clock;
// the windows come from the shared recon controller (also feeding the timeline markers).

export function createReconPanel(host: HTMLElement, windows: () => ReconWindow[]): Surface {
  return mount(host, {
    render() {
      const masterTime = timelineStore.getState().masterTime;
      const rows = windows();
      if (rows.length === 0) {
        return panel(
          { title: "Recon · next passes", meta: "24h horizon", bodyClass: "max-h-[230px]" },
          `<div class="py-1 text-[10.5px] text-ink/40">No predicted passes in the next 24 h — or the recon API is offline.</div>`,
        );
      }
      const body = rows
        .map((w) => {
          const sensor = w.sensor_type.toLowerCase();
          const sensorClass =
            sensor === "sar" ? "bg-[#E8D27A]/15 text-[#E8D27A]" : "bg-signal-faint text-signal-light";
          return `
            <div class="border-b border-line-2 py-2 last:border-b-0 ${w.quality < 0.5 ? "opacity-55" : ""}">
              <div class="flex items-baseline gap-2">
                <span class="rounded-[9px] px-1.5 py-0.5 font-mono text-[9px] tracking-[.1em] ${sensorClass}">${esc(w.sensor_type.toUpperCase())}</span>
                <span class="font-mono text-[15px] tabular-nums text-ink">${esc(formatEta(w.t_ingress, masterTime))}</span>
                <span class="ml-auto font-mono text-[9.5px] ${w.quality >= 0.7 ? "text-green" : "text-amber"}">q ${w.quality.toFixed(2)}</span>
              </div>
              <div class="mt-1 font-mono text-[9px] tracking-[.04em] text-ink/40">
                NORAD ${esc(w.norad_id)} · ${esc(w.aoi_id.toUpperCase())} · ${w.sunlit_at_peak ? "☀" : "☾"}
              </div>
            </div>`;
        })
        .join("");
      return panel(
        { title: "Recon · next passes", meta: "24h horizon", bodyClass: "max-h-[230px]" },
        body,
      );
    },
  });
}
