import { test, expect, beforeEach } from "vitest";
import { useTimelineStore } from "../store/useTimelineStore";
import { LAYER_IDS, type LayerId } from "../layers";

beforeEach(() => {
  const layerVisibility = LAYER_IDS.reduce(
    (acc, id) => ({ ...acc, [id]: true }),
    {} as Record<LayerId, boolean>,
  );
  useTimelineStore.setState({ mode: "live", playing: true, speed: 1, layerVisibility });
});

test("toggleLayer flips a layer's visibility", () => {
  const before = useTimelineStore.getState().layerVisibility.adsb;
  useTimelineStore.getState().toggleLayer("adsb");
  expect(useTimelineStore.getState().layerVisibility.adsb).toBe(!before);
});

test("setMode + setMasterTime update the master clock", () => {
  useTimelineStore.getState().setMode("historical");
  useTimelineStore.getState().setMasterTime(123);
  const s = useTimelineStore.getState();
  expect(s.mode).toBe("historical");
  expect(s.masterTime).toBe(123);
});

test("goLive resets to live mode and resumes playback", () => {
  useTimelineStore.getState().setMode("historical");
  useTimelineStore.getState().setPlaying(false);
  useTimelineStore.getState().goLive();
  const s = useTimelineStore.getState();
  expect(s.mode).toBe("live");
  expect(s.playing).toBe(true);
});

test("all five layers start visible", () => {
  const v = useTimelineStore.getState().layerVisibility;
  expect(Object.values(v).every(Boolean)).toBe(true);
});

test("selectEntity sets and clears the tracked entity", () => {
  useTimelineStore.getState().selectEntity({ layer: "ais", id: "636092297" });
  expect(useTimelineStore.getState().selectedEntity).toEqual({ layer: "ais", id: "636092297" });
  useTimelineStore.getState().selectEntity(null);
  expect(useTimelineStore.getState().selectedEntity).toBeNull();
});

test("setZoom updates the zoom used for level-of-detail", () => {
  useTimelineStore.getState().setZoom(3.2);
  expect(useTimelineStore.getState().zoom).toBe(3.2);
});
