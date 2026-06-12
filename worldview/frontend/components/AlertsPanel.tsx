"use client";

import type { LayerData } from "@/lib/useWorldViewData";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { deriveAlerts, type Alert, type AlertSeverity } from "@/lib/alerts";
import { Panel } from "./Panel";

// Active-intel feed (spec §3.4): severity is shape + TAG + color (never color alone); rows
// with a position offer LOCATE →, which opens the Inspector directly above this panel — the
// alert-triage chain stays on one rail (journey 3).

const SEV: Record<AlertSeverity, { dot: string; tag: string; pulse: boolean }> = {
  high: { dot: "bg-red shadow-[0_0_8px_rgba(255,90,82,.5)]", tag: "bg-red/15 text-red", pulse: true },
  medium: { dot: "bg-amber", tag: "bg-amber/15 text-amber", pulse: false },
  low: { dot: "bg-signal", tag: "bg-signal-faint text-signal-light", pulse: false },
};

function clock(ts: number): string {
  return ts > 0 ? new Date(ts * 1000).toISOString().slice(11, 16) : "";
}

export function AlertsPanel({ data }: { data: LayerData }) {
  const masterTime = useTimelineStore((s) => s.masterTime);
  const selectEntity = useTimelineStore((s) => s.selectEntity);
  const alerts = deriveAlerts(data, masterTime);

  function onSelect(alert: Alert) {
    // Only entities with a known position + id can be located on the globe / inspected.
    if (alert.entityId && alert.lon != null && alert.lat != null) {
      selectEntity({ layer: "context", id: alert.entityId });
    }
  }

  return (
    <Panel title="Active alerts" meta={String(alerts.length)} maxBodyClass="max-h-[220px]">
      {alerts.length === 0 ? (
        <div className="py-1 text-[10.5px] text-ink/40">No active alerts in this window.</div>
      ) : (
        <ul>
          {alerts.map((alert) => {
            const locatable = alert.entityId != null && alert.lon != null && alert.lat != null;
            const sev = SEV[alert.severity];
            const tag = alert.severity === "medium" ? "MED" : alert.severity.toUpperCase();
            return (
              <li key={alert.id} className="border-b border-line-2 last:border-b-0">
                <button
                  type="button"
                  onClick={() => onSelect(alert)}
                  disabled={!locatable}
                  className="grid w-full grid-cols-[14px_1fr] gap-2 py-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal disabled:cursor-default [&:hover_.al-t]:text-signal-light"
                >
                  <span
                    className={`mt-[3px] h-[9px] w-[9px] rounded-full ${sev.dot} ${sev.pulse ? "wv-pulse" : ""}`}
                    aria-hidden
                  />
                  <span>
                    <span className="al-t block text-[11.5px] leading-snug text-ink transition-colors">
                      <span className={`mr-1.5 rounded-[7px] px-1.5 py-px font-mono text-[7.5px] tracking-[.1em] ${sev.tag}`}>
                        {tag}
                      </span>
                      {alert.label}
                    </span>
                    <span className="mt-0.5 flex gap-2 font-mono text-[8.5px] tracking-[.04em] text-ink/40">
                      {alert.ts > 0 && <span>{clock(alert.ts)} UTC</span>}
                      {locatable && <span className="text-signal-light">LOCATE →</span>}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
