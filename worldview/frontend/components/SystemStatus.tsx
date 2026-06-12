"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { LayerData } from "@/lib/useWorldViewData";
import { LAYER_IDS } from "@/lib/layers";
import { useTimelineStore } from "@/lib/store/useTimelineStore";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_WORLDVIEW_API ?? "http://localhost:4000";

// First-run / degraded-state overlay (spec §3.1, P1): when the globe would otherwise be
// silently empty, a centered card explains WHAT this screen is, WHY it's empty, and the exact
// next steps — with the honesty footer. It renders nothing when data flows, so it never covers
// a working globe. Detection logic is state-driven (socket + per-layer fetch outcomes).

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[26px_1fr] items-start gap-3 border-t border-line-2 py-2.5">
      <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full border border-signal-dim font-mono text-[11px] text-signal-light">
        {n}
      </span>
      <div>
        <div className="text-[12.5px] text-ink">{title}</div>
        <div className="mt-0.5 font-mono text-[10px] text-ink/40">{children}</div>
      </div>
    </div>
  );
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded-[3px] bg-signal-faint px-1.5 py-px text-signal-light">{children}</code>
  );
}

export function SystemStatus({ data }: { data: LayerData }) {
  const mode = useTimelineStore((s) => s.mode);
  const liveConnection = useTimelineStore((s) => s.liveConnection);
  const layerStatus = useTimelineStore((s) => s.layerStatus);
  const visibility = useTimelineStore((s) => s.layerVisibility);
  const goLive = useTimelineStore((s) => s.goLive);
  const setHelpOpen = useTimelineStore((s) => s.setHelpOpen);

  // Give the live socket a moment before declaring trouble, so a healthy fast connect never flashes.
  const [graceElapsed, setGraceElapsed] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setGraceElapsed(true), 2500);
    return () => clearTimeout(t);
  }, []);

  const totalFeatures = LAYER_IDS.reduce((n, id) => n + data[id].features.length, 0);
  const visibleIds = LAYER_IDS.filter((id) => visibility[id]);
  const allErrored =
    mode === "historical" &&
    visibleIds.length > 0 &&
    visibleIds.every((id) => layerStatus[id] === "error");
  const allEmpty =
    visibleIds.length > 0 && visibleIds.every((id) => layerStatus[id] === "empty");

  const liveUnhealthy = liveConnection !== "open";

  type Variant = "down" | "connecting" | "empty" | null;
  let variant: Variant = null;
  if (mode === "live" && totalFeatures === 0 && graceElapsed && (liveConnection === "closed" || allErrored)) {
    variant = "down";
  } else if (mode === "live" && liveUnhealthy && graceElapsed && totalFeatures === 0) {
    variant = "connecting";
  } else if (allErrored) {
    variant = "down";
  } else if (allEmpty && totalFeatures === 0) {
    variant = "empty";
  }

  if (!variant) return null;

  const retry = (
    <button
      onClick={goLive}
      className="ml-auto rounded-md border border-line px-3 py-1.5 font-mono text-[9.5px] tracking-[.08em] text-ink/65 hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
    >
      RETRY ⟳
    </button>
  );

  return (
    <div className="absolute inset-0 z-[80] flex items-center justify-center bg-void/60 p-6 backdrop-blur-[3px]">
      <div
        role="status"
        aria-live="polite"
        className="w-[520px] max-w-full rounded-[10px] border border-line bg-surface-2 px-8 py-7"
      >
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.3" className="mb-3.5 text-signal" aria-hidden>
          <circle cx="12" cy="12" r="9" />
          <ellipse cx="12" cy="12" rx="9" ry="3.6" />
          <path d="M12 3v18" />
        </svg>

        {variant === "down" && (
          <>
            <div className="text-[21px] font-semibold tracking-[.01em]">
              WorldView is up — its data feed isn&apos;t.
            </div>
            <p className="mb-4 mt-2.5 text-[13px] leading-relaxed text-ink/65">
              This screen fuses live aircraft, vessels, satellites, GPS-jamming and intel onto one
              time-scrubbable map. Right now the API at{" "}
              <code className="text-signal-light">{API_URL}</code> isn&apos;t answering, so the
              globe is empty.
            </p>
            <Step n={1} title="Start the backend">
              <Code>START.bat</Code> (or <Code>npm run dev:api</Code> in <Code>worldview/</Code>) —
              boots the API + a synthetic Hormuz demo feed
            </Step>
            <Step n={2} title="Or point at a running API">
              set <Code>NEXT_PUBLIC_API_URL</Code> and reload
            </Step>
            <Step n={3} title="Then take the tour">
              press <Code>?</Code> for shortcuts · ◈ TOUR flies the camera between AOIs
            </Step>
          </>
        )}

        {variant === "connecting" && (
          <>
            <div className="text-[21px] font-semibold tracking-[.01em]">
              {liveConnection === "reconnecting" ? "Reconnecting to the live feed…" : "Connecting to the live feed…"}
            </div>
            <p className="mt-2.5 text-[13px] leading-relaxed text-ink/65">
              Waiting for data from <code className="text-signal-light">{API_URL}</code>. If this
              persists, the API may be offline — start it with{" "}
              <code className="text-signal-light">npm run dev:api</code>.
            </p>
          </>
        )}

        {variant === "empty" && (
          <>
            <div className="text-[21px] font-semibold tracking-[.01em]">
              Connected — no data in this window yet.
            </div>
            <p className="mb-4 mt-2.5 text-[13px] leading-relaxed text-ink/65">
              The API is answering but has nothing for this moment in time.
            </p>
            <Step n={1} title="Seed the demo scenario">
              <Code>npm run db:seed</Code> — a Strait of Hormuz scenario across all 5 layers
            </Step>
            <Step n={2} title="Or scrub to an active period">
              drag the timeline below, or press <Code>L</Code> for live
            </Step>
            <Step n={3} title="Shortcuts">
              press <Code>?</Code> — space, L, arrows, 1–5, G
            </Step>
          </>
        )}

        <div className="mt-4 flex items-center gap-2.5 border-t border-line-2 pt-3.5 text-[11px] text-amber">
          <span aria-hidden>◐</span>
          <span>
            The demo feed is synthetic — WorldView will badge it. It never passes demo data as real.
          </span>
          {variant !== "connecting" ? (
            retry
          ) : (
            <button
              onClick={() => setHelpOpen(true)}
              className="ml-auto rounded-md border border-line px-3 py-1.5 font-mono text-[9.5px] tracking-[.08em] text-ink/65 hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
            >
              SHORTCUTS ?
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
