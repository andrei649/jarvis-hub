import { createStore } from "zustand/vanilla";
import { LAYER_IDS, type LayerId } from "@/lib/layers";

// The global "System Master Time" controller (design doc §8). Every visual layer is a
// pure function of `masterTime`; toggling mode or scrubbing updates all layers in lockstep.
//
// A vanilla zustand store (no React): the HUD is direct DOM, so surfaces read `getState()` and
// re-render from `subscribe()`. The state shape and actions are the framework-independent
// contract every surface — globe, rails, timeline, keyboard — shares.

export type PlaybackMode = "live" | "historical";

/** Map projection: 2.5D flattened map vs 3D globe. */
export type ViewMode = "map" | "globe";

type LayerVisibility = Record<LayerId, boolean>;

const allVisible: LayerVisibility = LAYER_IDS.reduce(
  (acc, id) => ({ ...acc, [id]: true }),
  {} as LayerVisibility,
);

/**
 * Per-layer fetch outcome so the HUD can tell a genuinely empty time slice ("empty") apart from
 * a backend 500 / network drop ("error"). "loading" while a fetch is in flight, "ok" when the
 * last fetch returned features. The API client never throws — this is how failures surface.
 */
export type FetchStatus = "loading" | "ok" | "empty" | "error";

type LayerStatus = Record<LayerId, FetchStatus>;

const allOk: LayerStatus = LAYER_IDS.reduce(
  (acc, id) => ({ ...acc, [id]: "ok" }),
  {} as LayerStatus,
);

/** Live WebSocket connection state, surfaced so the HUD can show a connection indicator. */
export type LiveConnectionState = "connecting" | "open" | "reconnecting" | "closed";

/** The entity whose trail is shown, if any. */
export interface SelectedEntity {
  layer: LayerId;
  id: string;
}

/** A replay window [from, to] in UNIX seconds (lifted here so the timeline, the replay
 *  control and the arrival deep-link all drive the same bracket — spec §3.3/§5.1). */
export interface StoreReplayWindow {
  from: number;
  to: number;
}

/** Arrival context when the session was opened from a deep link (e.g. a JARVIS/Argus digest). */
export interface ArrivalContext {
  agent: string;
  window: StoreReplayWindow;
  entity: SelectedEntity | null;
}

/** A one-shot camera request (arrival deep links); consumed by the globe. */
export interface FlyToTarget {
  longitude: number;
  latitude: number;
  zoom: number;
}

/**
 * Sensor grade applied to the rendered globe (the God's Eye View sensor stack, on Cesium's
 * post-process pipeline). "normal" is the unmodified scene; the others are clearly-labelled
 * visual grades, never a claim about the underlying data.
 */
export type SensorMode = "normal" | "thermal" | "night" | "tactical";

export const SENSOR_MODES: readonly SensorMode[] = ["normal", "thermal", "night", "tactical"];

interface TimelineState {
  /** Master clock — UNIX seconds. Drives every layer. */
  masterTime: number;
  mode: PlaybackMode;
  /** Playback speed multiplier for historical mode (1 = realtime). */
  speed: number;
  playing: boolean;
  layerVisibility: LayerVisibility;
  selectedEntity: SelectedEntity | null;
  /** Current map zoom; drives level-of-detail (raw vs minute rollups). */
  zoom: number;
  /** Map projection: flattened 2.5D map ("map") vs 3D globe ("globe"). */
  viewMode: ViewMode;
  /** Per-layer last-fetch status (historical mode), so the HUD can distinguish empty vs error. */
  layerStatus: LayerStatus;
  /** Live WebSocket connection state (live mode), surfaced for a HUD indicator. */
  liveConnection: LiveConnectionState;
  /** Camera tour running (started from the app bar, sequenced by the camera driver). */
  tour: boolean;
  /** Keyboard-shortcuts overlay visibility (driven from the app bar `?` and the key). */
  helpOpen: boolean;
  /** The current replay window bracket, if one is set. */
  replayWindow: StoreReplayWindow | null;
  /** A replay is actively driving the master clock. */
  replaying: boolean;
  /** Set when the session arrived via a deep link (?from&to…); cleared on dismiss. */
  arrival: ArrivalContext | null;
  /** One-shot camera request; the globe consumes it and clears it. */
  flyTo: FlyToTarget | null;
  /** Sensor grade applied to the globe's post-process stack. */
  sensor: SensorMode;
  /** Camera locks onto the selected entity and follows it (God's Eye View's follow cam). */
  follow: boolean;

  setMasterTime: (ts: number) => void;
  setMode: (mode: PlaybackMode) => void;
  setSpeed: (speed: number) => void;
  setPlaying: (playing: boolean) => void;
  toggleLayer: (id: LayerId) => void;
  selectEntity: (entity: SelectedEntity | null) => void;
  setZoom: (zoom: number) => void;
  setViewMode: (mode: ViewMode) => void;
  setLayerStatus: (id: LayerId, status: FetchStatus) => void;
  setLiveConnection: (state: LiveConnectionState) => void;
  setTour: (tour: boolean) => void;
  setHelpOpen: (open: boolean) => void;
  setReplayWindow: (win: StoreReplayWindow | null) => void;
  setReplaying: (replaying: boolean) => void;
  setArrival: (arrival: ArrivalContext | null) => void;
  setFlyTo: (target: FlyToTarget | null) => void;
  setSensor: (sensor: SensorMode) => void;
  setFollow: (follow: boolean) => void;
  goLive: () => void;
}

export const timelineStore = createStore<TimelineState>((set) => ({
  masterTime: Date.now() / 1000,
  mode: "live",
  speed: 1,
  playing: true,
  layerVisibility: allVisible,
  selectedEntity: null,
  zoom: 6,
  viewMode: "globe",
  layerStatus: allOk,
  liveConnection: "connecting",
  tour: false,
  helpOpen: false,
  replayWindow: null,
  replaying: false,
  arrival: null,
  flyTo: null,
  sensor: "normal",
  follow: false,

  setMasterTime: (ts) => set({ masterTime: ts }),
  setMode: (mode) => set({ mode }),
  setSpeed: (speed) => set({ speed }),
  setPlaying: (playing) => set({ playing }),
  toggleLayer: (id) =>
    set((s) => ({
      layerVisibility: { ...s.layerVisibility, [id]: !s.layerVisibility[id] },
    })),
  // Dropping the selection also drops the follow lock: there is nothing left to follow, and a
  // camera that keeps chasing a cleared entity is a camera the user can't get back.
  selectEntity: (entity) => set(entity ? { selectedEntity: entity } : { selectedEntity: null, follow: false }),
  setZoom: (zoom) => set({ zoom }),
  setViewMode: (mode) => set({ viewMode: mode }),
  setLayerStatus: (id, status) =>
    set((s) => ({ layerStatus: { ...s.layerStatus, [id]: status } })),
  setLiveConnection: (state) => set({ liveConnection: state }),
  setTour: (tour) => set({ tour }),
  setHelpOpen: (open) => set({ helpOpen: open }),
  setReplayWindow: (win) => set({ replayWindow: win }),
  setReplaying: (replaying) => set({ replaying }),
  setArrival: (arrival) => set({ arrival }),
  setFlyTo: (target) => set({ flyTo: target }),
  setSensor: (sensor) => set({ sensor }),
  // Following requires a selection; asking to follow nothing is a no-op, not a broken camera.
  setFollow: (follow) => set((s) => ({ follow: follow && s.selectedEntity != null })),
  // Going live always tears down replay state: the pill/frame must never claim REPLAY
  // (or fake LIVE) while another driver still owns the cursor.
  goLive: () =>
    set({ mode: "live", masterTime: Date.now() / 1000, playing: true, replaying: false }),
}));

/** Current state — the read path for every direct-DOM surface. */
export const getState = timelineStore.getState;
/** Subscribe to any state change (surfaces coalesce their own re-render). */
export const subscribe = timelineStore.subscribe;
