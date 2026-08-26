// Brand type ramp (spec §1.3): Space Grotesk for UI, JetBrains Mono for data — self-hosted, no CDN.
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
import "./styles.css";

import { parseArrival } from "@/lib/arrival";
import { deriveUiMode, isDemoFeed, type UiMode } from "@/lib/uiMode";
import { timelineStore } from "@/lib/store/timelineStore";
import { createGlobe, type Globe } from "@/globe/viewer";
import { createRenderer, type PickPayload } from "@/globe/render";
import { createSensorController } from "@/globe/sensors";
import { createCameraDriver } from "@/globe/camera";
import { createPicking } from "@/globe/picking";
import { buildScene } from "@/globe/scene";
import { createDataController } from "@/app/data";
import { createTrackController } from "@/app/track";
import { createReconController } from "@/app/reconWindows";
import { createTourController } from "@/app/tour";
import { startMasterClock } from "@/app/clock";
import { startKeyboardShortcuts } from "@/app/shortcuts";
import { startReplayDriver } from "@/app/replay";
import { host } from "@/ui/dom";
import { createAppBar } from "@/ui/appBar";
import { createLayerPanel } from "@/ui/layerPanel";
import { createReconPanel } from "@/ui/reconPanel";
import { createStatsHud } from "@/ui/statsHud";
import { createInspector } from "@/ui/inspector";
import { createAlertsPanel } from "@/ui/alertsPanel";
import { createExportPanel } from "@/ui/exportPanel";
import { createTimeline } from "@/ui/timeline";
import { createSystemStatus } from "@/ui/systemStatus";
import {
  createArrivalBanner,
  createHelpOverlay,
  createModeFrame,
  createStageOverlays,
  renderGlobeFailure,
} from "@/ui/overlays";

// Bootstrap. Zone system (spec §2): app bar on top, timeline at the bottom, and two fixed-width
// rails over the globe — NAVIGATE (left: legend + layers, recon) and MONITOR/INSPECT (right:
// stats, inspector, alerts, export). Panels stack with a gap and never overlap by construction.

const root = document.getElementById("app");
if (!root) throw new Error("#app host element is missing from index.html");

root.className = "relative flex h-screen w-screen flex-col overflow-hidden bg-void";

const appBarHost = host(
  root,
  "relative z-50 flex h-[46px] flex-none items-center gap-3.5 border-b border-line bg-surface-2 px-3.5 backdrop-blur-[10px]",
  "header",
);
const stage = host(root, "relative min-h-0 flex-1");
const globeHost = host(stage, "absolute inset-0");
const credits = host(stage, "wv-credits");
const overlayHost = host(stage, "contents");
const navigateRail = host(
  stage,
  "pointer-events-none absolute bottom-3.5 left-3.5 top-3.5 z-10 flex w-[252px] flex-col gap-2.5",
);
const monitorRail = host(
  stage,
  "pointer-events-none absolute bottom-3.5 right-3.5 top-3.5 z-10 flex w-[286px] flex-col gap-2.5",
);
const timelineHost = host(
  root,
  "relative z-50 flex-none border-t border-line bg-surface-2 px-4 pb-2.5 pt-2 backdrop-blur-[10px]",
);
const modeFrameHost = host(root, "contents");

// --- globe ----------------------------------------------------------------

let globe: Globe;
try {
  globe = createGlobe(globeHost, credits);
} catch (error) {
  renderGlobeFailure(root, error);
  throw error;
}

const renderer = createRenderer(globe.viewer, { clampToGround: globe.choice.terrain });
const sensors = createSensorController(globe.viewer.scene);
const camera = createCameraDriver(globe.viewer, (zoom) => timelineStore.getState().setZoom(zoom));
createPicking(globe.viewer, {
  onSelect(payload: PickPayload | null) {
    const state = timelineStore.getState();
    if (!payload || !payload.trackId) {
      state.selectEntity(null); // clicking empty space clears the trail
      return;
    }
    state.selectEntity({ layer: payload.layer, id: payload.trackId });
  },
});

// --- data + derived state -------------------------------------------------

const data = createDataController();
const track = createTrackController();
const recon = createReconController();

let demoFeed = false;
let lens = false;

function uiMode(): UiMode {
  const s = timelineStore.getState();
  return deriveUiMode({
    mode: s.mode,
    liveConnection: s.liveConnection,
    replaying: s.replaying,
    replayArmed: s.arrival != null && s.replayWindow != null,
    demoFeed,
  });
}

function lensAvailable(): boolean {
  return timelineStore.getState().tour || uiMode() === "demo";
}

const tour = createTourController(
  (viewState) => camera.flyToTourStep(viewState),
  () => overlays.update(),
);

// --- HUD surfaces ---------------------------------------------------------

const appBar = createAppBar(appBarHost, {
  uiMode,
  lensAvailable,
  lens: () => lens,
  toggleLens: () => {
    lens = !lens;
    appBar.update();
    overlays.update();
  },
});

const layerPanelHost = host(navigateRail, "contents");
const reconPanelHost = host(navigateRail, "contents");
const statsHost = host(monitorRail, "contents");
const inspectorHost = host(monitorRail, "contents");
const alertsHost = host(monitorRail, "contents");
host(monitorRail, "flex-1");
const exportHost = host(monitorRail, "contents");

const layerPanel = createLayerPanel(layerPanelHost, data.get);
const reconPanel = createReconPanel(reconPanelHost, recon.get);
const statsHud = createStatsHud(statsHost, data.get);
const inspector = createInspector(inspectorHost, data.get);
const alertsPanel = createAlertsPanel(alertsHost, data.get);
const exportPanel = createExportPanel(exportHost, data.get);
const timeline = createTimeline(timelineHost, { data: data.get, recon: recon.get, uiMode });
const systemStatus = createSystemStatus(host(stage, "contents"), data.get);
const arrivalBanner = createArrivalBanner(host(stage, "contents"));
const helpOverlay = createHelpOverlay(host(stage, "contents"));
const modeFrame = createModeFrame(modeFrameHost, uiMode);
const overlays = createStageOverlays(overlayHost, {
  uiMode,
  lens: () => lens,
  setLens: (on) => {
    lens = on;
    appBar.update();
    overlays.update();
  },
  tourLabel: () => tour.label(),
  basemap: globe.choice,
});

const surfaces = [
  appBar,
  layerPanel,
  reconPanel,
  statsHud,
  inspector,
  alertsPanel,
  exportPanel,
  timeline,
  systemStatus,
  arrivalBanner,
  helpOverlay,
  modeFrame,
  overlays,
];

function updateHud() {
  for (const surface of surfaces) surface.update();
}

// --- globe <- state -------------------------------------------------------

let sceneDirty = true;
let scenePending = false;

function markSceneDirty() {
  sceneDirty = true;
  if (scenePending) return;
  scenePending = true;
  requestAnimationFrame(() => {
    scenePending = false;
    if (!sceneDirty) return;
    sceneDirty = false;
    const s = timelineStore.getState();
    renderer.apply(buildScene(data.get(), s.layerVisibility, track.get(), s.zoom));
    if (s.follow) followSelection();
  });
}

/** Keep the camera locked on the selected entity's newest position while FOLLOW is on. */
function followSelection() {
  const s = timelineStore.getState();
  const selected = s.selectedEntity;
  if (!selected) return;
  const scene = buildScene(data.get(), s.layerVisibility, undefined, s.zoom);
  const mark = scene.points.find((p) => p.layer === selected.layer && p.trackId === selected.id);
  if (!mark) return;
  camera.follow(mark.lon, mark.lat, mark.alt);
}

data.subscribe((layers) => {
  demoFeed = isDemoFeed(layers);
  markSceneDirty();
  updateHud();
});
track.subscribe(() => {
  markSceneDirty();
  updateHud();
});
recon.subscribe(() => updateHud());

let lastViewMode = timelineStore.getState().viewMode;
let lastSensor = timelineStore.getState().sensor;
let lastVisibility = timelineStore.getState().layerVisibility;
let lastZoomBand = Math.round(timelineStore.getState().zoom);
let lastFollow = timelineStore.getState().follow;

timelineStore.subscribe((state) => {
  globe.setSceneTime(state.masterTime);

  if (state.viewMode !== lastViewMode) {
    lastViewMode = state.viewMode;
    camera.setViewMode(state.viewMode);
  }
  if (state.sensor !== lastSensor) {
    lastSensor = state.sensor;
    sensors.apply(state.sensor);
  }
  if (state.follow !== lastFollow) {
    lastFollow = state.follow;
    if (state.follow) followSelection();
    else camera.stopFollowing();
  }
  if (state.layerVisibility !== lastVisibility || Math.round(state.zoom) !== lastZoomBand) {
    lastVisibility = state.layerVisibility;
    lastZoomBand = Math.round(state.zoom);
    markSceneDirty();
  }
  // A one-shot camera request from an arrival deep link; consume it and clear it.
  if (state.flyTo) {
    const target = state.flyTo;
    state.setFlyTo(null);
    camera.flyTo({ ...target, transitionDuration: 1200 });
  }

  updateHud();
});

// --- drivers --------------------------------------------------------------

startMasterClock();
startKeyboardShortcuts();
startReplayDriver();
camera.setViewMode(timelineStore.getState().viewMode);
camera.openOnAoi(timelineStore.getState().viewMode);
markSceneDirty();

// Arrival deep link (spec §5.1): ?from&to restores the replay window; +agent/entity makes it an
// ARRIVAL — camera pre-positioned, entity selected, banner shown, REPLAY from frame one.
const parsed = parseArrival(window.location.search);
if (parsed) {
  const s = timelineStore.getState();
  s.setReplayWindow({ from: parsed.window.from, to: parsed.window.to });
  s.setMode("historical");
  s.setPlaying(false);
  s.setMasterTime(parsed.window.from);
  if (parsed.entity) s.selectEntity(parsed.entity);
  if (parsed.view) s.setFlyTo(parsed.view);
  if (parsed.isArrival) {
    s.setArrival({
      agent: parsed.agent ?? "ARGUS",
      window: { from: parsed.window.from, to: parsed.window.to },
      entity: parsed.entity,
    });
  }
}
