import { LAYER_IDS } from "@/lib/layers";

// STEP 2 scaffold: a placeholder shell. The Deck.gl map, timeline scrubber, and
// Zustand-driven layer sync are implemented in STEP 5.
export default function Home() {
  return (
    <main className="flex h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-3xl font-semibold text-signal">WorldView</h1>
      <p className="max-w-xl text-sm opacity-80">
        4D OSINT command center scaffold. The Deck.gl globe, timeline scrubber, and live
        layer synchronization land in STEP 5.
      </p>
      <ul className="text-xs opacity-60">
        {LAYER_IDS.map((id) => (
          <li key={id}>{id}</li>
        ))}
      </ul>
    </main>
  );
}
