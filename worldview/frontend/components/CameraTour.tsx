"use client";

import { useEffect, useRef, useState } from "react";
import { useTimelineStore } from "@/lib/store/useTimelineStore";
import { defaultTour, type TourStep } from "@/lib/cameraTour";

// Camera-tour sequencer (H19.5.4). The start/stop button lives in the AppBar (store.tour);
// this component owns the tour TIMING — advance after each waypoint's fly-in + dwell — and
// hands each target viewState to DeckGlobe via `onViewState`. While active it shows the
// waypoint chip top-center (the only thing that may occupy that space, and only mid-tour).

export interface CameraTourProps {
  /** Called with each waypoint's deck viewState (incl. transitionDuration) as the tour advances. */
  onViewState: (viewState: TourStep["viewState"]) => void;
}

export function CameraTour({ onViewState }: CameraTourProps) {
  const tour = useTimelineStore((s) => s.tour);
  const [label, setLabel] = useState("");
  const stepsRef = useRef<TourStep[]>([]);
  const idxRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!tour) {
      setLabel("");
      return;
    }
    stepsRef.current = defaultTour({ loop: true });
    idxRef.current = 0;
    let cancelled = false;

    const run = () => {
      if (cancelled) return;
      const steps = stepsRef.current;
      if (steps.length === 0) {
        useTimelineStore.getState().setTour(false);
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
      if (timerRef.current != null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tour]);

  if (!tour || !label) return null;
  return (
    <div className="pointer-events-none absolute left-1/2 top-3.5 z-10 -translate-x-1/2 rounded-2xl border border-signal-dim bg-surface-2 px-4 py-1.5 font-mono text-[10px] tracking-[.18em] text-signal-light backdrop-blur-[10px]">
      → {label.toUpperCase()}
    </div>
  );
}
