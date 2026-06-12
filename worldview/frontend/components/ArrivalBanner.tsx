"use client";

import { useTimelineStore } from "@/lib/store/useTimelineStore";

// The arrival moment (spec §5.1): landing from a JARVIS/Argus digest deep link, the session
// opens with the camera pre-positioned, the replay window armed (violet bracket), the entity
// selected — and this banner explaining where you came from, with the one action that matters.
// Mode is REPLAY from the first frame (uiMode derivation) — never fake-LIVE.

function clock(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(11, 16);
}

export function ArrivalBanner() {
  const arrival = useTimelineStore((s) => s.arrival);
  const setArrival = useTimelineStore((s) => s.setArrival);
  const setReplaying = useTimelineStore((s) => s.setReplaying);

  if (!arrival) return null;

  return (
    <div
      role="status"
      className="wv-arrive absolute left-1/2 top-[64px] z-30 flex -translate-x-1/2 items-center gap-3 rounded-lg border border-red/40 bg-surface-2 px-4 py-2.5 backdrop-blur-[10px]"
    >
      <span className="flex items-center gap-1.5 font-mono text-[9px] tracking-[.12em] text-violet">
        ◈ {arrival.agent} · VIA JARVIS DIGEST
      </span>
      {arrival.entity && (
        <span className="text-[12px] text-ink">
          {arrival.entity.layer.toUpperCase()} · {arrival.entity.id}
        </span>
      )}
      <span className="font-mono text-[9.5px] text-ink/40">
        window {clock(arrival.window.from)} → {clock(arrival.window.to)} pre-set
      </span>
      <button
        onClick={() => setReplaying(true)}
        className="rounded-md border border-red/45 bg-red/5 px-2.5 py-1 font-mono text-[9px] tracking-[.06em] text-red hover:bg-red/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
      >
        ▶ REPLAY THE GAP
      </button>
      <button
        onClick={() => setArrival(null)}
        className="rounded-md border border-line px-2.5 py-1 font-mono text-[9px] tracking-[.06em] text-ink/65 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
      >
        DISMISS
      </button>
    </div>
  );
}
