import { deriveAlerts, type AlertSeverity } from "@/lib/alerts";
import type { LayerData } from "@/lib/layerData";
import { timelineStore } from "@/lib/store/timelineStore";
import { esc, mount, shortClock, type Surface } from "./dom";
import { panel } from "./panel";

// Active-intel feed (spec §3.4): severity is shape + TAG + color (never color alone); rows with
// a position offer LOCATE →, which opens the Inspector directly above this panel — the
// alert-triage chain stays on one rail (journey 3).

const SEV: Record<AlertSeverity, { dot: string; tag: string; pulse: boolean }> = {
  high: { dot: "bg-red shadow-[0_0_8px_rgba(255,90,82,.5)]", tag: "bg-red/15 text-red", pulse: true },
  medium: { dot: "bg-amber", tag: "bg-amber/15 text-amber", pulse: false },
  low: { dot: "bg-signal", tag: "bg-signal-faint text-signal-light", pulse: false },
};

export function createAlertsPanel(host: HTMLElement, data: () => LayerData): Surface {
  return mount(host, {
    actions: {
      locate: (_e, _el, arg) => {
        if (arg) timelineStore.getState().selectEntity({ layer: "context", id: arg });
      },
    },
    render() {
      const s = timelineStore.getState();
      const alerts = deriveAlerts(data(), s.masterTime);
      if (alerts.length === 0) {
        return panel(
          { title: "Active alerts", meta: "0", bodyClass: "max-h-[220px]" },
          `<div class="py-1 text-[10.5px] text-ink/40">No active alerts in this window.</div>`,
        );
      }

      const rows = alerts
        .map((alert) => {
          const locatable = alert.entityId != null && alert.lon != null && alert.lat != null;
          const sev = SEV[alert.severity];
          const tag = alert.severity === "medium" ? "MED" : alert.severity.toUpperCase();
          return `
            <li class="border-b border-line-2 last:border-b-0">
              <button type="button" data-act="locate" data-arg="${esc(locatable ? alert.entityId : "")}" ${locatable ? "" : "disabled"}
                class="grid w-full grid-cols-[14px_1fr] gap-2 py-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal disabled:cursor-default [&amp;:hover_.al-t]:text-signal-light">
                <span class="mt-[3px] h-[9px] w-[9px] rounded-full ${sev.dot} ${sev.pulse ? "wv-pulse" : ""}" aria-hidden="true"></span>
                <span>
                  <span class="al-t block text-[11.5px] leading-snug text-ink transition-colors">
                    <span class="mr-1.5 rounded-[7px] px-1.5 py-px font-mono text-[7.5px] tracking-[.1em] ${sev.tag}">${tag}</span>
                    ${esc(alert.label)}
                  </span>
                  <span class="mt-0.5 flex gap-2 font-mono text-[8.5px] tracking-[.04em] text-ink/40">
                    ${alert.ts > 0 ? `<span>${shortClock(alert.ts)} UTC</span>` : ""}
                    ${locatable ? `<span class="text-signal-light">LOCATE →</span>` : ""}
                  </span>
                </span>
              </button>
            </li>`;
        })
        .join("");

      return panel(
        { title: "Active alerts", meta: String(alerts.length), bodyClass: "max-h-[220px]" },
        `<ul>${rows}</ul>`,
      );
    },
  });
}
