"use client";

import { useEffect, useRef, useState } from "react";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { buildReplayLink } from "@/lib/export";
import { replaySampleAt } from "@/lib/replaySchedule";

// Replay chip (spec §4, H19.2.7). The window lives in the STORE (shared with the scrubber's
// violet bracket and the arrival deep link); this control arms it, drives masterTime from
// `from` to `to` on a deterministic schedule, and copies the reproducible ?from&to link.
// It does NOT run its own clock — it sets the master-clock store so every layer replays in
// lockstep, and it aborts cleanly if another driver (● LIVE) takes the cursor.

const DEFAULT_WINDOW_MINUTES = 15;
const REPLAY_SPEEDS = [10, 60, 300];

/** "HH:MM:SS" — compact enough for the inline labels. */
function clock(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(11, 19);
}

export function ReplayControl() {
  const setMasterTime = useTimelineStore((s) => s.setMasterTime);
  const setMode = useTimelineStore((s) => s.setMode);
  const setSpeed = useTimelineStore((s) => s.setSpeed);
  const setPlaying = useTimelineStore((s) => s.setPlaying);
  const masterTime = useTimelineStore((s) => s.masterTime);
  const win = useTimelineStore((s) => s.replayWindow);
  const setWin = useTimelineStore((s) => s.setReplayWindow);
  const replaying = useTimelineStore((s) => s.replaying);
  const setReplaying = useTimelineStore((s) => s.setReplaying);

  const [replaySpeed, setReplaySpeed] = useState(60);
  const [copied, setCopied] = useState(false);
  const rafRef = useRef<number | null>(null);
  const frameRef = useRef<number>(0);

  // Times derive from Date.now() — gate display behind mount (hydration, house pattern).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // Drive the master clock from `from` to `to` on a DETERMINISTIC schedule: a fixed-step frame
  // counter (replaySampleAt), so the sequence of sampled masterTimes is a pure function of
  // {from,to,speed} and reproducible regardless of RAF cadence. The master clock's own ticker
  // is paused (playing=false) so we own the cursor. Stops at `to`.
  useEffect(() => {
    if (!replaying || !win) return;
    setMode("historical");
    setPlaying(false); // we drive the cursor; don't let useMasterClock double-advance it
    setMasterTime(win.from);
    frameRef.current = 0;

    const tick = () => {
      const s = useTimelineStore.getState();
      // Another driver took over (e.g. goLive flipped mode→live / playing→true): abort cleanly.
      if (s.mode !== "historical" || s.playing) {
        setReplaying(false);
        return;
      }
      frameRef.current += 1;
      const next = replaySampleAt(win.from, win.to, replaySpeed, frameRef.current);
      if (next >= win.to) {
        setMasterTime(win.to);
        setReplaying(false);
        return;
      }
      setMasterTime(next);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replaying, win?.from, win?.to, replaySpeed]);

  // Abort-on-takeover, observed from outside the RAF loop too (● LIVE → mode:live).
  const mode = useTimelineStore((s) => s.mode);
  useEffect(() => {
    if (replaying && mode !== "historical") setReplaying(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replaying, mode]);

  function arm() {
    const now = Math.floor(Date.now() / 1000);
    setWin({ from: now - DEFAULT_WINDOW_MINUTES * 60, to: now });
  }

  function copyLink() {
    if (typeof window === "undefined" || !win) return;
    const link = buildReplayLink(window.location.href, win);
    void navigator.clipboard?.writeText(link).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => setCopied(false),
    );
  }

  const chipBtn =
    "font-mono text-[9.5px] text-violet hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal";

  if (!win) {
    return (
      <button
        onClick={arm}
        className="flex items-center gap-2 rounded-md border border-violet/35 bg-violet/5 px-2.5 py-1 font-mono text-[9.5px] tracking-[.04em] text-violet/75 hover:bg-violet/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
        title="Arm a replay window (last 15 minutes) you can play, share and reproduce"
      >
        SET REPLAY WINDOW ⧉
      </button>
    );
  }

  const spanMin = Math.max(0, Math.round((win.to - win.from) / 60));
  const progress =
    replaying && win.to > win.from
      ? Math.min(1, Math.max(0, (masterTime - win.from) / (win.to - win.from)))
      : 0;

  return (
    <span className="flex items-center gap-2.5 rounded-md border border-violet/35 bg-violet/5 px-2.5 py-1 font-mono text-[9.5px] text-violet">
      <span suppressHydrationWarning className="tabular-nums">
        REPLAY {mounted ? `${clock(win.from)} → ${clock(win.to)}` : "—"} ({spanMin}m)
      </span>
      <select
        value={replaySpeed}
        onChange={(e) => setReplaySpeed(Number(e.target.value))}
        className="rounded border border-line bg-void-2 px-1 py-0.5 text-[9px] text-ink/65"
        aria-label="Replay speed"
      >
        {REPLAY_SPEEDS.map((s) => (
          <option key={s} value={s}>
            {s}×
          </option>
        ))}
      </select>
      <button
        className={chipBtn}
        onClick={() => {
          if (replaying) {
            setReplaying(false);
          } else {
            setReplaying(true);
            setSpeed(replaySpeed);
          }
        }}
      >
        {replaying ? `■ STOP (${Math.round(progress * 100)}%)` : "▶ REPLAY"}
      </button>
      <button className={chipBtn} onClick={copyLink}>
        {copied ? "✓ COPIED" : "🔗 LINK"}
      </button>
      <button
        className="font-mono text-[9.5px] text-ink/40 hover:text-ink/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal"
        onClick={() => {
          setReplaying(false);
          setWin(null);
        }}
        aria-label="Clear replay window"
      >
        ✕
      </button>
    </span>
  );
}
