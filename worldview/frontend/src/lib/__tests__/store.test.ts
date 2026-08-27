import { test, expect, beforeEach } from "vitest";
import { timelineStore } from "../store/timelineStore";
import { LAYER_IDS, type LayerId } from "../layers";

beforeEach(() => {
  const layerVisibility = LAYER_IDS.reduce(
    (acc, id) => ({ ...acc, [id]: true }),
    {} as Record<LayerId, boolean>,
  );
  const layerStatus = LAYER_IDS.reduce(
    (acc, id) => ({ ...acc, [id]: "ok" }),
    {} as Record<LayerId, "loading" | "ok" | "empty" | "error">,
  );
  timelineStore.setState({
    mode: "live",
    playing: true,
    speed: 1,
    layerVisibility,
    viewMode: "map",
    layerStatus,
    liveConnection: "connecting",
  });
});

test("toggleLayer flips a layer's visibility", () => {
  const before = timelineStore.getState().layerVisibility.adsb;
  timelineStore.getState().toggleLayer("adsb");
  expect(timelineStore.getState().layerVisibility.adsb).toBe(!before);
});

test("setMode + setMasterTime update the master clock", () => {
  timelineStore.getState().setMode("historical");
  timelineStore.getState().setMasterTime(123);
  const s = timelineStore.getState();
  expect(s.mode).toBe("historical");
  expect(s.masterTime).toBe(123);
});

test("goLive resets to live mode and resumes playback", () => {
  timelineStore.getState().setMode("historical");
  timelineStore.getState().setPlaying(false);
  timelineStore.getState().goLive();
  const s = timelineStore.getState();
  expect(s.mode).toBe("live");
  expect(s.playing).toBe(true);
});

test("all five layers start visible", () => {
  const v = timelineStore.getState().layerVisibility;
  expect(Object.values(v).every(Boolean)).toBe(true);
});

test("selectEntity sets and clears the tracked entity", () => {
  timelineStore.getState().selectEntity({ layer: "ais", id: "636092297" });
  expect(timelineStore.getState().selectedEntity).toEqual({ layer: "ais", id: "636092297" });
  timelineStore.getState().selectEntity(null);
  expect(timelineStore.getState().selectedEntity).toBeNull();
});

test("setZoom updates the zoom used for level-of-detail", () => {
  timelineStore.getState().setZoom(3.2);
  expect(timelineStore.getState().zoom).toBe(3.2);
});

test("viewMode defaults to map", () => {
  expect(timelineStore.getState().viewMode).toBe("map");
});

test("setViewMode switches between map and globe", () => {
  timelineStore.getState().setViewMode("globe");
  expect(timelineStore.getState().viewMode).toBe("globe");
  timelineStore.getState().setViewMode("map");
  expect(timelineStore.getState().viewMode).toBe("map");
});

test("setLayerStatus records a per-layer fetch outcome without touching others", () => {
  timelineStore.getState().setLayerStatus("adsb", "error");
  expect(timelineStore.getState().layerStatus.adsb).toBe("error");
  expect(timelineStore.getState().layerStatus.ais).toBe("ok"); // unchanged
  timelineStore.getState().setLayerStatus("adsb", "empty");
  expect(timelineStore.getState().layerStatus.adsb).toBe("empty");
});

test("setLiveConnection records the live WebSocket connection state", () => {
  timelineStore.getState().setLiveConnection("reconnecting");
  expect(timelineStore.getState().liveConnection).toBe("reconnecting");
  timelineStore.getState().setLiveConnection("open");
  expect(timelineStore.getState().liveConnection).toBe("open");
});

test("goLive flips mode to live — the signal the replay loop aborts on (finding #4)", () => {
  // ReplayControl's abort effect keys off mode leaving "historical"; goLive must set mode:live.
  timelineStore.getState().setMode("historical");
  timelineStore.getState().setPlaying(false);
  timelineStore.getState().goLive();
  const s = timelineStore.getState();
  expect(s.mode).toBe("live"); // replay watcher sees mode !== "historical" → setReplaying(false)
  expect(s.playing).toBe(true); // live driver takes the cursor
});
