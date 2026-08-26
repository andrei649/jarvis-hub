import { replaySampleAt } from "@/lib/replaySchedule";
import { timelineStore } from "@/lib/store/timelineStore";

// The replay driver (spec §4, H19.2.7). The window lives in the STORE (shared with the
// scrubber's violet bracket and the arrival deep link); this driver moves masterTime from
// `from` to `to` on a DETERMINISTIC schedule — a fixed-step frame counter (replaySampleAt), so
// the sequence of sampled masterTimes is a pure function of {from, to, speed} and reproducible
// regardless of frame cadence.
//
// The master clock's own ticker is paused while a replay runs (playing = false) so exactly one
// driver owns the cursor, and the loop aborts cleanly the moment another one takes it (● LIVE
// flips mode → live / playing → true).

export function startReplayDriver(): () => void {
  let raf: number | null = null;
  let frame = 0;
  let running = false;

  function stop() {
    if (raf != null) cancelAnimationFrame(raf);
    raf = null;
    running = false;
  }

  function tick() {
    const s = timelineStore.getState();
    const win = s.replayWindow;
    if (!s.replaying || !win) {
      stop();
      return;
    }
    // Another driver took over: abort cleanly rather than fighting for the cursor.
    if (s.mode !== "historical" || s.playing) {
      stop();
      s.setReplaying(false);
      return;
    }
    frame += 1;
    const next = replaySampleAt(win.from, win.to, s.speed, frame);
    if (next >= win.to) {
      s.setMasterTime(win.to);
      stop();
      s.setReplaying(false);
      return;
    }
    s.setMasterTime(next);
    raf = requestAnimationFrame(tick);
  }

  const unsubscribe = timelineStore.subscribe((state) => {
    if (state.replaying && state.replayWindow && !running) {
      running = true;
      frame = 0;
      state.setMode("historical");
      state.setPlaying(false); // we drive the cursor; don't let the master clock double-advance
      state.setMasterTime(state.replayWindow.from);
      raf = requestAnimationFrame(tick);
      return;
    }
    if (!state.replaying && running) stop();
  });

  return () => {
    unsubscribe();
    stop();
  };
}
