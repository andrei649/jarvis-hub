import { defaultTour, type TourStep, type TourViewState } from "@/lib/cameraTour";
import { timelineStore } from "@/lib/store/timelineStore";

// Camera-tour sequencer (H19.5.4). The start/stop control lives in the app bar (store.tour);
// this owns the tour TIMING — advance after each waypoint's fly-in + dwell — and hands each
// target pose to the camera driver. The waypoint list itself is pure (lib/cameraTour.ts).

export interface TourController {
  /** The current waypoint's name while a tour runs, else "". */
  label(): string;
  destroy(): void;
}

export function createTourController(
  flyTo: (viewState: TourViewState) => void,
  onLabelChange: (label: string) => void,
): TourController {
  let label = "";
  let timer: ReturnType<typeof setTimeout> | null = null;
  let running = false;

  function setLabel(next: string) {
    if (next === label) return;
    label = next;
    onLabelChange(label);
  }

  function stop() {
    if (timer != null) clearTimeout(timer);
    timer = null;
    running = false;
    setLabel("");
  }

  function start() {
    const steps: TourStep[] = defaultTour({ loop: true });
    if (steps.length === 0) {
      timelineStore.getState().setTour(false);
      return;
    }
    running = true;
    let index = 0;

    const run = () => {
      if (!running) return;
      const step = steps[index % steps.length]!;
      setLabel(step.waypoint.name);
      flyTo(step.viewState);
      index = (index + 1) % steps.length;
      timer = setTimeout(run, step.transitionMs + step.dwellMs);
    };
    run();
  }

  const unsubscribe = timelineStore.subscribe((state) => {
    if (state.tour && !running) start();
    else if (!state.tour && running) stop();
  });

  if (timelineStore.getState().tour) start();

  return {
    label: () => label,
    destroy() {
      unsubscribe();
      stop();
    },
  };
}
