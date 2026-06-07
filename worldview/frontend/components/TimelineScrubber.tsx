"use client";

import { useTimelineStore } from "@/lib/store/useTimelineStore";

const WINDOW_SECONDS = 24 * 3600; // scrub the last 24h
const SPEEDS = [1, 10, 60, 300];

export function TimelineScrubber() {
  const { masterTime, mode, playing, speed, setMasterTime, setMode, setSpeed, setPlaying, goLive } =
    useTimelineStore();

  const now = Date.now() / 1000;
  const min = now - WINDOW_SECONDS;

  function onScrub(value: number) {
    // Scrubbing implies historical playback.
    if (mode !== "historical") setMode("historical");
    setMasterTime(value);
  }

  return (
    <div className="pointer-events-auto absolute inset-x-0 bottom-0 z-10 flex flex-col gap-2 bg-cockpit/90 px-6 py-3 backdrop-blur">
      <div className="flex items-center gap-4 text-xs">
        <button
          onClick={() => setPlaying(!playing)}
          className="rounded bg-signal/20 px-3 py-1 font-medium text-signal hover:bg-signal/30"
        >
          {playing ? "⏸ Pause" : "▶ Play"}
        </button>

        <button
          onClick={goLive}
          className={`rounded px-3 py-1 font-medium ${
            mode === "live"
              ? "bg-red-500/30 text-red-300"
              : "bg-white/10 text-white/70 hover:bg-white/20"
          }`}
        >
          ● LIVE
        </button>

        <span className="tabular-nums text-white/80">
          {new Date(masterTime * 1000).toISOString().replace("T", " ").slice(0, 19)} UTC
        </span>

        <label className="ml-auto flex items-center gap-1 text-white/60">
          speed
          <select
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
            className="rounded bg-white/10 px-2 py-1"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
      </div>

      <input
        type="range"
        min={min}
        max={now}
        step={1}
        value={Math.min(masterTime, now)}
        onChange={(e) => onScrub(Number(e.target.value))}
        className="w-full accent-signal"
      />
    </div>
  );
}
