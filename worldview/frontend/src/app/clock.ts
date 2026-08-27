import { timelineStore } from "@/lib/store/timelineStore";

// Advances the global master clock every frame. In live mode it tracks wall-clock now; in
// historical mode it integrates elapsed time × speed. Every layer is a pure function of this
// single value (design doc §8.4), so all layers move in lockstep.

// Live mode only needs ~4 Hz: downstream consumers bucket masterTime to whole seconds, so
// writing it 60×/s just spams store notifications. Historical/replay still advance every frame
// for smooth scrubbing.
const LIVE_TICK_INTERVAL_MS = 250;

/** Start the master clock. Returns a stop function. */
export function startMasterClock(): () => void {
  let raf = 0;
  let last = performance.now();
  let lastLiveWrite = 0;

  const tick = (now: number) => {
    const dt = (now - last) / 1000;
    last = now;
    const s = timelineStore.getState();
    if (s.playing) {
      if (s.mode === "live") {
        if (now - lastLiveWrite >= LIVE_TICK_INTERVAL_MS) {
          lastLiveWrite = now;
          timelineStore.setState({ masterTime: Date.now() / 1000 });
        }
      } else {
        timelineStore.setState({ masterTime: s.masterTime + dt * s.speed });
      }
    }
    raf = requestAnimationFrame(tick);
  };

  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}
