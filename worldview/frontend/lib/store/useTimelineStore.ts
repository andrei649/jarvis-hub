import { create } from "zustand";
import { LAYER_IDS, type LayerId } from "@/lib/layers";

// The global "System Master Time" controller (design doc §8). Every visual layer is a
// pure function of `masterTime`; toggling mode or scrubbing updates all layers in lockstep.
//
// STEP 2 scaffold: state shape + actions only. The data-fetch fan-out (live WebSocket vs
// historical as-of-T REST) is wired in STEP 5.

export type PlaybackMode = "live" | "historical";

/** Map projection: 2.5D Mapbox basemap vs 3D Deck.gl globe. */
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
  /** Map projection: 2.5D Mapbox basemap ("map") vs 3D Deck.gl globe ("globe"). */
  viewMode: ViewMode;
  /** Per-layer last-fetch status (historical mode), so the HUD can distinguish empty vs error. */
  layerStatus: LayerStatus;
  /** Live WebSocket connection state (live mode), surfaced for a HUD indicator. */
  liveConnection: LiveConnectionState;

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
  goLive: () => void;
}

export const useTimelineStore = create<TimelineState>((set) => ({
  masterTime: Date.now() / 1000,
  mode: "live",
  speed: 1,
  playing: true,
  layerVisibility: allVisible,
  selectedEntity: null,
  zoom: 6,
  viewMode: "map",
  layerStatus: allOk,
  liveConnection: "connecting",

  setMasterTime: (ts) => set({ masterTime: ts }),
  setMode: (mode) => set({ mode }),
  setSpeed: (speed) => set({ speed }),
  setPlaying: (playing) => set({ playing }),
  toggleLayer: (id) =>
    set((s) => ({
      layerVisibility: { ...s.layerVisibility, [id]: !s.layerVisibility[id] },
    })),
  selectEntity: (entity) => set({ selectedEntity: entity }),
  setZoom: (zoom) => set({ zoom }),
  setViewMode: (mode) => set({ viewMode: mode }),
  setLayerStatus: (id, status) =>
    set((s) => ({ layerStatus: { ...s.layerStatus, [id]: status } })),
  setLiveConnection: (state) => set({ liveConnection: state }),
  goLive: () => set({ mode: "live", masterTime: Date.now() / 1000, playing: true }),
}));
