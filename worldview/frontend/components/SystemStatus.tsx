"use client";

import { useEffect, useState } from "react";
import type { LayerData } from "@/lib/useWorldViewData";
import { LAYER_IDS } from "@/lib/layers";
import { useTimelineStore } from "@/lib/store/useTimelineStore";

const API_URL =
  process.env.NEXT_PUBLIC_WORLDVIEW_API ?? "http://localhost:4000";

/**
 * Centered status overlay — the "what am I looking at / why is it empty" layer the UX review
 * flagged as the #1 gap. It only appears when something needs explaining: the live socket is
 * stuck connecting/closed, or every visible layer came back empty/errored. When data is flowing
 * it renders nothing, so it never covers a working globe.
 */
export function SystemStatus({ data }: { data: LayerData }) {
  const mode = useTimelineStore((s) => s.mode);
  const liveConnection = useTimelineStore((s) => s.liveConnection);
  const layerStatus = useTimelineStore((s) => s.layerStatus);
  const visibility = useTimelineStore((s) => s.layerVisibility);
  const goLive = useTimelineStore((s) => s.goLive);

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

  // Decide which (if any) message to show.
  let panel: { tone: "warn" | "info" | "wait"; title: string; body: React.ReactNode } | null = null;

  // A socket that never connects cycles connecting→closed→reconnecting; with zero data on
  // screen, every one of those states needs the explanation, not just "closed".
  const liveUnhealthy = liveConnection !== "open";

  if (mode === "live" && totalFeatures === 0 && graceElapsed && (liveConnection === "closed" || allErrored)) {
    panel = {
      tone: "warn",
      title: "Can't reach the live feed",
      body: (
        <>
          <p>
            The WorldView API at <code className="text-white/80">{API_URL}</code> isn't responding,
            so the globe has no data yet.
          </p>
          <ol className="mt-2 list-decimal space-y-0.5 pl-4 text-white/65">
            <li>Start the API: <code className="text-white/80">npm run dev:api</code> (in <code className="text-white/80">worldview/</code>)</li>
            <li>Or seed the demo feed: <code className="text-white/80">npm run db:seed</code></li>
            <li>Then it reconnects automatically — or press <kbd className="rounded bg-white/15 px-1">L</kbd> to retry live.</li>
          </ol>
        </>
      ),
    };
  } else if (mode === "live" && liveUnhealthy && graceElapsed && totalFeatures === 0) {
    panel = {
      tone: "wait",
      title: liveConnection === "reconnecting" ? "Reconnecting to the live feed…" : "Connecting to the live feed…",
      body: (
        <p>
          Waiting for data from <code className="text-white/80">{API_URL}</code>. If this persists,
          the API may be offline — start it with <code className="text-white/80">npm run dev:api</code>.
        </p>
      ),
    };
  } else if (allErrored) {
    panel = {
      tone: "warn",
      title: "Data fetch failed",
      body: (
        <p>
          Every active layer returned an error from <code className="text-white/80">{API_URL}</code>.
          Check that the API is running, then scrub or press <kbd className="rounded bg-white/15 px-1">L</kbd> for live.
        </p>
      ),
    };
  } else if (allEmpty && totalFeatures === 0) {
    panel = {
      tone: "info",
      title: "No data in this time window",
      body: (
        <p>
          The API is connected but has nothing for this moment. Scrub the timeline to an active
          period, or press <kbd className="rounded bg-white/15 px-1">L</kbd> to jump to live.
        </p>
      ),
    };
  }

  if (!panel) return null;

  const tone = {
    warn: "border-red-500/40 bg-red-500/10",
    info: "border-signal/40 bg-signal/10",
    wait: "border-amber-500/40 bg-amber-500/10",
  }[panel.tone];

  return (
    <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center p-6">
      <div
        role="status"
        aria-live="polite"
        className={`pointer-events-auto max-w-md rounded-xl border ${tone} p-5 text-sm text-white/90 shadow-2xl backdrop-blur-md`}
      >
        <div className="mb-1.5 font-semibold text-white">{panel.title}</div>
        <div className="leading-relaxed text-white/80">{panel.body}</div>
        {(panel.tone === "warn" || panel.tone === "info") && (
          <button
            onClick={goLive}
            className="mt-3 rounded bg-signal/25 px-3 py-1 font-medium text-signal hover:bg-signal/40"
          >
            ● Retry live
          </button>
        )}
      </div>
    </div>
  );
}
