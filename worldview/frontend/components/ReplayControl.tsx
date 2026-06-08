"use client";

import { useEffect, useRef, useState } from "react";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import {
  buildReplayLink,
  decodeReplayWindow,
  type ReplayWindow,
} from "@/lib/export";
import { replaySampleAt } from "@/lib/replaySchedule";

// Replay affordance (H19.2.7, client side). Given a [from,to] window the user drives masterTime
// from `from` to `to` at a chosen speed — it does NOT run its own clock, it sets the master-clock
// store (historical mode + speed), so every layer replays in lockstep. A "copy replay link"
// encodes {from,to} in the URL query so reopening restores the window (reproducible). On mount we
// read any ?from&to from the URL and pre-fill the window.

const DEFAULT_WINDOW_MINUTES = 15;
const REPLAY_SPEEDS = [10, 60, 300];

function defaultWindow(): ReplayWindow {
  const now = Math.floor(Date.now() / 1000);
  return { from: now - DEFAULT_WINDOW_MINUTES * 60, to: now };
}

/** "HH:MM:SS UTC" — compact enough for the inline labels. */
function clock(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(11, 19);
}

export function ReplayControl() {
  const setMasterTime = useTimelineStore((s) => s.setMasterTime);
  const setMode = useTimelineStore((s) => s.setMode);
  const setSpeed = useTimelineStore((s) => s.setSpeed);
  const setPlaying = useTimelineStore((s) => s.setPlaying);
  const masterTime = useTimelineStore((s) => s.masterTime);

  const [win, setWin] = useState<ReplayWindow>(defaultWindow);
  const [replaySpeed, setReplaySpeed] = useState(60);
  const [replaying, setReplaying] = useState(false);
  const [copied, setCopied] = useState(false);
  const rafRef = useRef<number | null>(null);
  const frameRef = useRef<number>(0);

  // On mount: if the URL carries ?from&to, restore that window (reproducible replay link).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const decoded = decodeReplayWindow(window.location.search);
    if (decoded) setWin(decoded);
  }, []);

  // Drive the master clock from `from` to `to` on a DETERMINISTIC schedule: a fixed-step frame
  // counter (replaySampleAt), so the sequence of sampled masterTimes is a pure function of
  // {from,to,speed} and reproducible regardless of RAF cadence (a late/dropped frame skips ahead
  // rather than resampling at a different point). The master clock's own ticker is paused
  // (playing=false) so we own the cursor. Stops at `to`.
  //
  // The loop also aborts if another driver takes the cursor: clicking ● LIVE (goLive →
  // mode:live, playing:true) during a replay must not leave two RAF loops stomping masterTime, so
  // we bail when the store mode leaves "historical" or playback gets re-enabled by someone else.
  useEffect(() => {
    if (!replaying) return;
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
  }, [replaying, win.from, win.to, replaySpeed]);

  // Abort-on-takeover, observed from outside the RAF loop too: if the store mode leaves
  // "historical" (e.g. ● LIVE → goLive sets mode:live) while we're replaying, stop replaying so the
  // RAF loop tears down and stops stomping masterTime. We key off mode (not `playing`) because the
  // replay setup itself toggles `playing`, but only an external driver flips us out of historical.
  const mode = useTimelineStore((s) => s.mode);
  useEffect(() => {
    if (replaying && mode !== "historical") setReplaying(false);
  }, [replaying, mode]);

  function copyLink() {
    if (typeof window === "undefined") return;
    const link = buildReplayLink(window.location.href, win);
    void navigator.clipboard?.writeText(link).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => setCopied(false),
    );
  }

  const spanMin = Math.max(0, Math.round((win.to - win.from) / 60));
  const progress =
    replaying && win.to > win.from
      ? Math.min(1, Math.max(0, (masterTime - win.from) / (win.to - win.from)))
      : 0;

  return (
    <div className="flex items-center gap-2 text-white/60">
      <span className="text-white/45">replay</span>
      <span className="tabular-nums">
        {clock(win.from)}→{clock(win.to)} ({spanMin}m)
      </span>
      <select
        value={replaySpeed}
        onChange={(e) => setReplaySpeed(Number(e.target.value))}
        className="rounded bg-white/10 px-1 py-0.5"
        aria-label="replay speed"
      >
        {REPLAY_SPEEDS.map((s) => (
          <option key={s} value={s}>
            {s}×
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => {
          if (replaying) {
            setReplaying(false);
          } else {
            // Re-anchor "now" so a default window stays fresh when re-launched live-adjacent.
            setReplaying(true);
            setSpeed(replaySpeed);
          }
        }}
        className="rounded bg-signal/20 px-2 py-0.5 font-medium text-signal hover:bg-signal/30"
      >
        {replaying ? `■ Stop (${Math.round(progress * 100)}%)` : "▶ Replay"}
      </button>
      <button
        type="button"
        onClick={copyLink}
        className="rounded bg-white/10 px-2 py-0.5 text-white/70 hover:bg-white/20"
      >
        {copied ? "✓ Copied" : "🔗 Link"}
      </button>
    </div>
  );
}
