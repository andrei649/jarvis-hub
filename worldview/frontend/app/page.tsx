"use client";

import dynamic from "next/dynamic";
import { LayerPanel } from "@/components/LayerPanel";
import { StatsHud } from "@/components/StatsHud";
import { TimelineScrubber } from "@/components/TimelineScrubber";
import { useMasterClock } from "@/lib/useMasterClock";
import { useWorldViewData } from "@/lib/useWorldViewData";

// The globe uses WebGL + mapbox-gl (browser-only); load it client-side without SSR.
const DeckGlobe = dynamic(() => import("@/components/DeckGlobe").then((m) => m.DeckGlobe), {
  ssr: false,
});

export default function Home() {
  useMasterClock(); // drives the global master clock that every layer follows
  const data = useWorldViewData(); // single data source, shared by the globe and the HUD

  return (
    <main className="relative h-screen w-screen overflow-hidden">
      <DeckGlobe data={data} />
      <LayerPanel />
      <StatsHud data={data} />
      <TimelineScrubber />
    </main>
  );
}
