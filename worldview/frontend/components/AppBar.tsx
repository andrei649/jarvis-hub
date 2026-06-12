"use client";

import { useEffect, useState } from "react";
import { useTimelineStore, type ViewMode } from "@/lib/store/useTimelineStore";
import { MODE_META, type UiMode } from "@/lib/uiMode";

// The app bar (spec §2): wordmark · AOI chip · projection toggle · tour ··· mode pill · clock ·
// connection badge · help. Top-center of the stage stays empty at rest — everything that used
// to float there (ViewToggle, the tour button) lives here now.

const AOI_LABEL = process.env.NEXT_PUBLIC_AOI_LABEL ?? "STRAIT OF HORMUZ";

const VIEWS: { id: ViewMode; label: string }[] = [
  { id: "map", label: "2.5D MAP" },
  { id: "globe", label: "3D GLOBE" },
];

function clockText(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(11, 19);
}

export function AppBar({
  uiMode,
  lensAvailable = false,
  lens = false,
  onToggleLens,
}: {
  uiMode: UiMode;
  /** The demo lens is offered only on the tour/demo journey (spec §5.2). */
  lensAvailable?: boolean;
  lens?: boolean;
  onToggleLens?: () => void;
}) {
  const masterTime = useTimelineStore((s) => s.masterTime);
  const mode = useTimelineStore((s) => s.mode);
  const liveConnection = useTimelineStore((s) => s.liveConnection);
  const viewMode = useTimelineStore((s) => s.viewMode);
  const setViewMode = useTimelineStore((s) => s.setViewMode);
  const tour = useTimelineStore((s) => s.tour);
  const setTour = useTimelineStore((s) => s.setTour);
  const setHelpOpen = useTimelineStore((s) => s.setHelpOpen);
  const replayWindow = useTimelineStore((s) => s.replayWindow);
  const speed = useTimelineStore((s) => s.speed);
  const goLive = useTimelineStore((s) => s.goLive);

  // Time values render only after mount (SSR hydration — same pattern as the timeline).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const meta = MODE_META[uiMode];
  const note = (() => {
    switch (uiMode) {
      case "live":
        return "real feed";
      case "demo":
        return "synthetic data";
      case "historical":
        return mounted ? `as of ${clockText(masterTime)} UTC` : "as of —";
      case "replay":
        return replayWindow && mounted
          ? `${clockText(replayWindow.from)} → ${clockText(replayWindow.to)} · ${speed}×`
          : "window armed";
      case "offline":
        return liveConnection === "reconnecting" ? "reconnecting…" : "feed unreachable";
    }
  })();

  // In historical mode the socket is closed by design — describe the data path instead of
  // dressing a deliberate close up as a failure.
  const conn =
    mode === "historical"
      ? { cls: "text-ink/40", dot: "bg-ink/40", label: "HTTP · AS-OF", pulse: "" }
      : {
          open: { cls: "text-green", dot: "bg-green", label: "WS OPEN", pulse: "" },
          connecting: { cls: "text-amber", dot: "bg-amber", label: "CONNECTING", pulse: "wv-pulse-fast" },
          reconnecting: { cls: "text-amber", dot: "bg-amber", label: "RECONNECTING", pulse: "wv-pulse-fast" },
          closed: { cls: "text-red", dot: "bg-red", label: "DISCONNECTED", pulse: "" },
        }[liveConnection];

  const barBtn =
    "rounded-md border border-line px-2.5 py-1.5 font-mono text-[9.5px] tracking-[.08em] text-ink/65 transition-colors hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal";

  return (
    <header className="relative z-50 flex h-[46px] flex-none items-center gap-3.5 border-b border-line bg-surface-2 px-3.5 backdrop-blur-[10px]">
      <div className="flex items-center gap-2">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" className="text-signal" aria-hidden>
          <circle cx="12" cy="12" r="9" />
          <ellipse cx="12" cy="12" rx="9" ry="3.6" />
          <path d="M12 3v18" />
        </svg>
        <div>
          <div className="text-[12.5px] font-semibold tracking-[.22em]">WORLDVIEW</div>
          <div className="mt-px font-mono text-[8.5px] tracking-[.14em] text-ink/40">4D OSINT · JARVIS HUB</div>
        </div>
      </div>

      <span className="hidden rounded-xl border border-line px-2.5 py-1 font-mono text-[9.5px] tracking-[.1em] text-ink/65 lg:inline">
        AOI · {AOI_LABEL}
      </span>

      <div className="flex overflow-hidden rounded-md border border-line" role="group" aria-label="Projection">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            onClick={() => setViewMode(v.id)}
            aria-pressed={viewMode === v.id}
            className={`px-3 py-1.5 font-mono text-[9.5px] tracking-[.08em] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal ${
              viewMode === v.id ? "bg-signal-faint text-signal-light" : "text-ink/40 hover:text-ink/80"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      <button className={barBtn} onClick={() => setTour(!tour)} aria-pressed={tour}>
        {tour ? "■ STOP TOUR" : "◈ TOUR AOIs"}
      </button>

      {lensAvailable && onToggleLens && (
        <button className={barBtn} onClick={onToggleLens} aria-pressed={lens}>
          {lens ? "LENS ✕" : "LENS"}
        </button>
      )}

      <div className="flex-1" />

      <span
        className={`flex items-center gap-2 rounded-[13px] border px-3 py-1 font-mono text-[10px] font-semibold tracking-[.14em] ${meta.pill}`}
      >
        <span className={`h-[7px] w-[7px] rounded-full ${meta.dot} ${uiMode === "live" ? "wv-pulse" : ""}`} aria-hidden />
        {meta.label}
        <span className="font-normal opacity-75">· {note}</span>
        {(uiMode === "historical" || uiMode === "replay") && (
          <button
            onClick={goLive}
            className="rounded-[10px] bg-green px-2 py-0.5 font-mono text-[9px] font-bold tracking-[.1em] text-[#04150c] focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
          >
            GO LIVE
          </button>
        )}
      </span>

      <span suppressHydrationWarning className="font-mono text-[13px] tabular-nums tracking-[.06em]">
        {mounted ? clockText(masterTime) : "--:--:--"}
        <span className="ml-1 text-[9px] text-ink/40">UTC</span>
      </span>

      <span className={`flex items-center gap-1.5 font-mono text-[9px] tracking-[.08em] ${conn.cls}`}>
        <span className={`h-[7px] w-[7px] rounded-full ${conn.dot} ${conn.pulse}`} aria-hidden />
        {conn.label}
      </span>

      <button className={barBtn} onClick={() => setHelpOpen(true)} aria-label="Keyboard shortcuts">
        ?
      </button>
    </header>
  );
}
