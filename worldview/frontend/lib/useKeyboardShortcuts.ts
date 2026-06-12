import { useEffect } from "react";
import { useTimelineStore } from "./store/useTimelineStore";
import { LAYER_IDS } from "./layers";

const SCRUB_STEP_SECONDS = 30;

// Command-center keyboard shortcuts (the full map lives in lib/shortcuts.ts, which the help
// overlay renders — keep the two in sync):
//   space → play/pause · l → go live · ← / → → scrub ±30s (historical) · esc → close help /
//   clear selection · 1–5 → toggle layers · g → map⇄globe · ? → help overlay
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
          // Overlays first, then selection — one Esc, one dismissal.
          if (s.helpOpen) s.setHelpOpen(false);
          else s.selectEntity(null);
          break;
        case "g":
        case "G":
          s.setViewMode(s.viewMode === "map" ? "globe" : "map");
          break;
        case "?":
          s.setHelpOpen(!s.helpOpen);
          break;
        case "1":
        case "2":
        case "3":
        case "4":
        case "5": {
          const layer = LAYER_IDS[Number(e.key) - 1];
          if (layer) s.toggleLayer(layer);
          break;
        }
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
