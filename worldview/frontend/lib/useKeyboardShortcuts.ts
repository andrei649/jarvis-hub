import { useEffect } from "react";
import { useTimelineStore } from "./store/useTimelineStore";

const SCRUB_STEP_SECONDS = 30;

// Command-center keyboard shortcuts:
//   space → play/pause · l → go live · ← / → → scrub ±30s (historical) · esc → clear selection
export function useKeyboardShortcuts(): void {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Don't hijack typing in inputs/selects.
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;

      const s = useTimelineStore.getState();
      switch (e.key) {
        case " ":
          e.preventDefault();
          s.setPlaying(!s.playing);
          break;
        case "l":
        case "L":
          s.goLive();
          break;
        case "ArrowLeft":
          s.setMode("historical");
          s.setMasterTime(s.masterTime - SCRUB_STEP_SECONDS);
          break;
        case "ArrowRight":
          s.setMode("historical");
          s.setMasterTime(s.masterTime + SCRUB_STEP_SECONDS);
          break;
        case "Escape":
          s.selectEntity(null);
          break;
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
