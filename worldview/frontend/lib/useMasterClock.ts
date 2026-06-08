import { useEffect } from "react";
import { useTimelineStore } from "./store/useTimelineStore";

// Advances the global master clock every frame. In live mode it tracks wall-clock now; in
// historical mode it integrates elapsed time × speed. Every layer is a pure function of this
// single value (design doc §8.4), so all layers move in lockstep.
export function useMasterClock(): void {
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      const s = useTimelineStore.getState();
      if (s.playing) {
        if (s.mode === "live") {
          useTimelineStore.setState({ masterTime: Date.now() / 1000 });
        } else {
          useTimelineStore.setState({ masterTime: s.masterTime + dt * s.speed });
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);
}
