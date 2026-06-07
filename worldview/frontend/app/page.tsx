"use client";

import dynamic from "next/dynamic";
import { LayerPanel } from "@/components/LayerPanel";
import { TimelineScrubber } from "@/components/TimelineScrubber";
import { useMasterClock } from "@/lib/useMasterClock";

// The globe uses WebGL + mapbox-gl (browser-only); load it client-side without SSR.
const DeckGlobe = dynamic(() => import("@/components/DeckGlobe").then((m) => m.DeckGlobe), {
  ssr: false,
});

export default function Home() {
  useMasterClock(); // drives the global master clock that every layer follows

  return (
    <main className="relative h-screen w-screen overflow-hidden">
      <DeckGlobe />
      <LayerPanel />
      <TimelineScrubber />
    </main>
  );
}
