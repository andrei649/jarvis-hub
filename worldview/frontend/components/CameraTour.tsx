"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { defaultTour, type TourStep } from "@/lib/cameraTour";

// Camera-tour control (H19.5.4, remaining slice). Drives the deck viewState through a sequence
// of AOI waypoints. This component owns the tour timing (advance after each waypoint's dwell +
// fly-in) and hands the target viewState back to DeckGlobe via `onViewState`. The pure tour
// model lives in lib/cameraTour.ts; here we just sequence it on a timer and stop on demand.

export interface CameraTourProps {
  /** Called with each waypoint's deck viewState (incl. transitionDuration) as the tour advances. */
  onViewState: (viewState: TourStep["viewState"]) => void;
  /** Called when the tour starts/stops so the parent can switch to controlled viewState. */
  onActiveChange?: (active: boolean) => void;
}

export function CameraTour({ onViewState, onActiveChange }: CameraTourProps) {
  const [active, setActive] = useState(false);
  const [label, setLabel] = useState("");
  const stepsRef = useRef<TourStep[]>([]);
  const idxRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = () => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const stop = useCallback(() => {
    clearTimer();
    setActive(false);
    setLabel("");
    onActiveChange?.(false);
  }, [onActiveChange]);

  // Sequence the tour: fly to the current step, then after (transition + dwell) advance.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const run = () => {
      if (cancelled) return;
      const steps = stepsRef.current;
      if (steps.length === 0) {
        stop();
        return;
      }
      const step = steps[idxRef.current % steps.length]!;
      setLabel(step.waypoint.name);
      onViewState(step.viewState);
      idxRef.current = (idxRef.current + 1) % steps.length;
      timerRef.current = setTimeout(run, step.transitionMs + step.dwellMs);
    };
    run();

    return () => {
      cancelled = true;
      clearTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  function start() {
    stepsRef.current = defaultTour({ loop: true });
    idxRef.current = 0;
    setActive(true);
    onActiveChange?.(true);
  }

  return (
    <div className="pointer-events-auto absolute left-1/2 top-16 z-10 flex -translate-x-1/2 items-center gap-2 rounded-lg bg-cockpit/85 px-3 py-1.5 text-xs backdrop-blur">
      <button
        type="button"
        onClick={() => (active ? stop() : start())}
        className="rounded bg-signal/20 px-3 py-1 font-medium text-signal hover:bg-signal/30"
      >
        {active ? "■ Stop tour" : "🎬 Tour AOIs"}
      </button>
      {active && label && <span className="text-white/70">→ {label}</span>}
    </div>
  );
}
