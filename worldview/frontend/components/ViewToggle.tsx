"use client";

import { useTimelineStore, type ViewMode } from "@/lib/store/useTimelineStore";

const MODES: { id: ViewMode; label: string }[] = [
  { id: "map", label: "2.5D Map" },
  { id: "globe", label: "3D Globe" },
];

export function ViewToggle() {
  const viewMode = useTimelineStore((s) => s.viewMode);
  const setViewMode = useTimelineStore((s) => s.setViewMode);

  return (
    <div className="pointer-events-auto absolute left-1/2 top-4 z-10 flex -translate-x-1/2 gap-1 rounded-lg bg-cockpit/85 p-1 text-xs backdrop-blur">
      {MODES.map((m) => {
        const active = viewMode === m.id;
        return (
          <button
            key={m.id}
            onClick={() => setViewMode(m.id)}
            aria-pressed={active}
            className={
              "rounded px-3 py-1 transition-colors " +
              (active
                ? "bg-signal/20 font-semibold text-signal"
                : "text-white/60 hover:bg-white/10 hover:text-white/90")
            }
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}
