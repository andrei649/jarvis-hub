"use client";

import type { LayerData } from "@/lib/useWorldViewData";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { deriveAlerts, type Alert, type AlertSeverity } from "@/lib/alerts";

// Severity → dot color (Tailwind), mirroring the cockpit palette used elsewhere.
const SEVERITY_DOT: Record<AlertSeverity, string> = {
  high: "bg-red-400",
  medium: "bg-amber-400",
  low: "bg-sky-400",
};

// Active-intel feed: dark vessels + geopolitical events as a clickable alert list. Sits under
// the StatsHud (bottom-right) and ties into the shared selection so clicking an alert with a
// position opens the Inspector for that entity.
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
    <div className="pointer-events-auto absolute bottom-4 right-4 z-10 flex w-64 flex-col gap-1 rounded-lg bg-cockpit/85 p-3 text-xs backdrop-blur">
      <div className="mb-1 font-semibold text-signal">Active alerts</div>
      {alerts.length === 0 ? (
        <div className="text-white/50">No active alerts</div>
      ) : (
        <ul className="flex max-h-64 flex-col gap-0.5 overflow-y-auto">
          {alerts.map((alert) => {
            const locatable = alert.entityId != null && alert.lon != null && alert.lat != null;
            return (
              <li key={alert.id}>
                <button
                  type="button"
                  onClick={() => onSelect(alert)}
                  disabled={!locatable}
                  className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-white/85 ${
                    locatable ? "hover:bg-white/10" : "cursor-default"
                  }`}
                >
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${SEVERITY_DOT[alert.severity]}`}
                    aria-hidden
                  />
                  <span className="truncate">{alert.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
