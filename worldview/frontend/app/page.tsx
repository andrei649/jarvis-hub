"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import { AppBar } from "@/components/AppBar";
import { ModeFrame } from "@/components/ModeFrame";
import { LayerPanel } from "@/components/LayerPanel";
import { StatsHud } from "@/components/StatsHud";
import { AlertsPanel } from "@/components/AlertsPanel";
import { ReconPanel } from "@/components/ReconPanel";
import { ExportPanel } from "@/components/ExportPanel";
import { Inspector } from "@/components/Inspector";
import { TimelineScrubber } from "@/components/TimelineScrubber";
import { SystemStatus } from "@/components/SystemStatus";
import { HelpOverlay } from "@/components/HelpOverlay";
import { GlobeErrorBoundary } from "@/components/GlobeErrorBoundary";
import { useMasterClock } from "@/lib/useMasterClock";
import { useKeyboardShortcuts } from "@/lib/useKeyboardShortcuts";
import { useWorldViewData } from "@/lib/useWorldViewData";
import { useReconWindows } from "@/lib/useReconWindows";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { deriveUiMode, isDemoFeed } from "@/lib/uiMode";

// The globe uses WebGL + mapbox-gl (browser-only); load it client-side without SSR.
const DeckGlobe = dynamic(() => import("@/components/DeckGlobe").then((m) => m.DeckGlobe), {
  ssr: false,
});

// Zone system (spec §2): app bar on top, timeline at the bottom, and two fixed-width flex
// rails over the map — NAVIGATE (left: legend+layers, recon) and MONITOR/INSPECT (right:
// stats, inspector, alerts, export). Panels stack with a gap and never overlap by construction;
// there are no absolute pixel offsets to fall out of sync.

export default function Home() {
  useMasterClock(); // drives the global master clock that every layer follows
  useKeyboardShortcuts(); // space · L · ←/→ · esc · 1–5 · G · ? (see lib/shortcuts.ts)
  const data = useWorldViewData(); // single data source, shared by the globe and the panels

  const mode = useTimelineStore((s) => s.mode);
  const masterTime = useTimelineStore((s) => s.masterTime);
  const liveConnection = useTimelineStore((s) => s.liveConnection);
  const replaying = useTimelineStore((s) => s.replaying);
  const replayWindow = useTimelineStore((s) => s.replayWindow);
  const arrival = useTimelineStore((s) => s.arrival);

  // One recon fetch feeds both the panel and the timeline's markers (they can't disagree).
  const recon = useReconWindows(masterTime);

  // One derivation feeds every mode surface (frame, pill, timeline restate, watermark).
  const demoFeed = useMemo(() => isDemoFeed(data), [data]);
  const uiMode = deriveUiMode({
    mode,
    liveConnection,
    replaying,
    replayArmed: arrival != null && replayWindow != null,
    demoFeed,
  });

  return (
    <main className="relative flex h-screen w-screen flex-col overflow-hidden bg-void">
      <AppBar uiMode={uiMode} />

      <div className="relative min-h-0 flex-1">
        <GlobeErrorBoundary>
          <DeckGlobe data={data} />
        </GlobeErrorBoundary>

        {/* DEMO is identifiable from any screenshot (honesty system): pill + this watermark. */}
        {uiMode === "demo" && (
          <div className="pointer-events-none absolute bottom-3.5 right-[310px] z-[5] font-mono text-[9px] tracking-[.18em] text-amber/50">
            ◐ SYNTHETIC FEED — NOT REAL-WORLD DATA
          </div>
        )}

        {/* NAVIGATE rail */}
        <div className="pointer-events-none absolute bottom-3.5 left-3.5 top-3.5 z-10 flex w-[252px] flex-col gap-2.5">
          <LayerPanel data={data} />
          <ReconPanel windows={recon} />
        </div>

        {/* MONITOR / INSPECT rail */}
        <div className="pointer-events-none absolute bottom-3.5 right-3.5 top-3.5 z-10 flex w-[286px] flex-col gap-2.5">
          <StatsHud data={data} />
          <Inspector data={data} />
          <AlertsPanel data={data} />
          <div className="flex-1" />
          <ExportPanel data={data} />
        </div>

        <SystemStatus data={data} />
        <HelpOverlay />
      </div>

      <TimelineScrubber data={data} recon={recon} uiMode={uiMode} />

      <ModeFrame uiMode={uiMode} />
    </main>
  );
}
