"use client";

import { useEffect, useState } from "react";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import type { LayerData } from "@/lib/useWorldViewData";
import type { ReconWindow } from "@/lib/recon";
import type { UiMode } from "@/lib/uiMode";
import { deriveTimelineMarkers, markerPct } from "@/lib/timelineMarkers";
import { ReplayControl } from "./ReplayControl";

const WINDOW_SECONDS = 24 * 3600; // scrub the last 24h
const SPEEDS = [1, 10, 60, 300];
const TICKS = ["-24h", "-18h", "-12h", "-6h", "now"];

const MARKER_CLS: Record<string, string> = {
  alert: "bg-red shadow-[0_0_6px_rgba(255,90,82,.6)]",
  recon: "bg-[#E8D27A]",
  intel: "bg-violet",
};

// Mode signal #3 of 3 (spec §3.3): the timeline restates the mode in words — the clock shows
// the VIEWED time, a mode note explains it, and the LIVE button is filled green only when
// live (hollow otherwise; one click back, plus `L`). Event markers (spec §4) pin alerts /
// recon passes / intel onto the 24h track so history is navigable.
export function TimelineScrubber({
  data,
  recon,
  uiMode,
}: {
  data: LayerData;
  recon: ReconWindow[];
  uiMode: UiMode;
}) {
  const { masterTime, mode, playing, speed, setMasterTime, setMode, setSpeed, setPlaying, goLive } =
    useTimelineStore();
  const replayWindow = useTimelineStore((s) => s.replayWindow);

  // `masterTime` and `now` derive from Date.now() → hydration mismatch unless gated (house pattern).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const now = Date.now() / 1000;
  const min = now - WINDOW_SECONDS;
  const headPct = mounted ? Math.min(100, Math.max(0, ((Math.min(masterTime, now) - min) / WINDOW_SECONDS) * 100)) : 100;

  const markers = mounted ? deriveTimelineMarkers(data, recon, masterTime) : [];

  function onScrub(value: number) {
    // Scrubbing implies historical playback; the mode system announces it everywhere.
    if (mode !== "historical") setMode("historical");
    setMasterTime(value);
  }

  const live = uiMode === "live" || uiMode === "demo";
  const modeNote = {
    live: "master clock · all layers in lockstep",
    demo: "master clock · synthetic feed",
    historical: "VIEWING THE PAST — world state as of this moment",
    replay: replayWindow
      ? `REPLAY ${new Date(replayWindow.from * 1000).toISOString().slice(11, 16)}→${new Date(replayWindow.to * 1000).toISOString().slice(11, 16)} · deterministic`
      : "REPLAY",
    offline: "feed unreachable — clock paused at last data",
  }[uiMode];

  return (
    <div className="relative z-50 flex-none border-t border-line bg-surface-2 px-4 pb-2.5 pt-2 backdrop-blur-[10px]">
      <div className="flex items-center gap-3.5">
        <button
          onClick={() => setPlaying(!playing)}
          aria-label={playing ? "Pause" : "Play"}
          className="h-8 w-8 rounded-full border border-line text-[12px] text-ink transition-colors hover:border-signal-dim hover:text-signal-light focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
        >
          {playing ? "⏸" : "▶"}
        </button>

        <button
          onClick={goLive}
          title={live ? "Receiving real-time data" : "Click (or press L) to return to real-time"}
          className={`flex items-center gap-1.5 rounded-2xl border px-3.5 py-1.5 font-mono text-[10px] font-bold tracking-[.14em] transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal ${
            live
              ? "border-green bg-green text-[#04150c] shadow-[0_0_16px_rgba(65,245,155,.35)]"
              : "border-line text-ink/40 hover:border-green/40 hover:text-green"
          }`}
        >
          ● LIVE
        </button>

        <span suppressHydrationWarning className="font-mono text-[14px] tabular-nums tracking-[.04em]">
          {mounted ? (
            <>
              {new Date(masterTime * 1000).toISOString().slice(11, 19)}
              <span className="ml-1 text-[9px] text-ink/40">
                UTC · {new Date(masterTime * 1000).toISOString().slice(0, 10)}
              </span>
            </>
          ) : (
            "--:--:--"
          )}
        </span>

        <span className="font-mono text-[9px] tracking-[.06em] text-ink/40">{modeNote}</span>

        <div className="flex-1" />

        <ReplayControl />

        <label className="flex items-center gap-1.5 font-mono text-[9px] text-ink/40">
          <select
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
            aria-label="Playback speed"
            className="rounded-md border border-line bg-void-2 px-2 py-1 text-[9.5px] text-ink/65"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* The 24h scrubber: custom track + fill + event markers + replay bracket, with a native
          range input stretched invisibly across it for dragging, clicking and keyboard a11y. */}
      <div className="relative mt-1.5 h-[34px]">
        <div className="absolute left-0 right-0 top-[14px] h-1 rounded-sm border border-line-2 bg-void-2" aria-hidden />
        <div
          aria-hidden
          className="absolute top-[14px] h-1 rounded-sm bg-gradient-to-r from-signal/25 to-signal"
          style={{ left: 0, width: `${headPct}%` }}
        />

        {mounted && replayWindow && (
          <div
            aria-hidden
            className="absolute top-[11px] h-2.5 rounded-[3px] border-[1.5px] border-violet bg-violet/10"
            style={{
              left: `${Math.max(0, markerPct(replayWindow.from, min, now) ?? 0)}%`,
              width: `${Math.max(0.5, (markerPct(replayWindow.to, min, now) ?? 100) - (markerPct(replayWindow.from, min, now) ?? 0))}%`,
            }}
          />
        )}

        {markers.map((m, i) => {
          const pct = markerPct(m.t, min, now);
          if (pct == null) return null;
          return (
            <button
              key={`${m.kind}:${m.t}:${i}`}
              title={m.label}
              aria-label={`Scrub to: ${m.label}`}
              onClick={() => onScrub(m.t)}
              className={`absolute top-[9px] z-10 h-3.5 w-[2.5px] -translate-x-1/2 rounded-[1px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal ${MARKER_CLS[m.kind]}`}
              style={{ left: `${pct}%` }}
            />
          );
        })}

        <div
          aria-hidden
          className="absolute top-[8px] h-4 w-4 -translate-x-1/2 rounded-full border-2 border-void bg-signal-light shadow-[0_0_10px_rgba(43,184,240,.4)]"
          style={{ left: `${headPct}%` }}
        />

        {mounted ? (
          <input
            type="range"
            min={min}
            max={now}
            step={1}
            value={Math.min(masterTime, now)}
            onChange={(e) => onScrub(Number(e.target.value))}
            aria-label="24 hour timeline"
            className="absolute inset-x-0 top-0 h-[26px] w-full cursor-pointer opacity-0"
          />
        ) : (
          <div className="h-[26px] w-full" aria-hidden />
        )}

        {TICKS.map((t, i) => (
          <span
            key={t}
            aria-hidden
            className="absolute top-[28px] -translate-x-1/2 font-mono text-[8px] text-ink/20"
            style={{ left: `${i * 25}%` }}
          >
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}
