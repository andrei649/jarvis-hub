import { timelineStore, SENSOR_MODES } from "@/lib/store/timelineStore";
import { LAYER_IDS } from "@/lib/layers";

const SCRUB_STEP_SECONDS = 30;

// Command-center keyboard shortcuts (the full map lives in lib/shortcuts.ts, which the help
// overlay renders — keep the two in sync):
//   space → play/pause · l → go live · ← / → → scrub ±30s (historical) · esc → close help /
//   clear selection · 1–5 → toggle layers · g → map⇄globe · v → cycle sensor grade ·
//   f → follow the selection · ? → help overlay
export function startKeyboardShortcuts(): () => void {
  function onKey(e: KeyboardEvent) {
    // Don't hijack typing in inputs/selects.
    const tag = (e.target as HTMLElement | null)?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;

    const s = timelineStore.getState();
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
      case "v":
      case "V": {
        const next = SENSOR_MODES[(SENSOR_MODES.indexOf(s.sensor) + 1) % SENSOR_MODES.length];
        if (next) s.setSensor(next);
        break;
      }
      case "f":
      case "F":
        s.setFollow(!s.follow);
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
}
