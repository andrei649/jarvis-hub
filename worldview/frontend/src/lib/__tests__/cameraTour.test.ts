import { test, expect, afterEach, vi } from "vitest";
import {
  tourSteps,
  tourIterator,
  defaultTour,
  defaultTourWaypoints,
  DEFAULT_TRANSITION_MS,
  DEFAULT_DWELL_MS,
  DEFAULT_TOUR_PITCH,
  type Waypoint,
} from "../cameraTour";

afterEach(() => vi.unstubAllEnvs());

const WPS: Waypoint[] = [
  { name: "A", longitude: 10, latitude: 20, zoom: 6, dwellMs: 1000 },
  { name: "B", longitude: 30, latitude: 40, zoom: 7, dwellMs: 2000 },
  { name: "C", longitude: 50, latitude: 60, zoom: 5, dwellMs: 3000 },
];

// --- tourSteps ---------------------------------------------------------------

test("tourSteps maps each waypoint to a camera pose with transition + dwell (no loop)", () => {
  const steps = tourSteps(WPS, { loop: false, transitionMs: 1500 });
  expect(steps).toHaveLength(3);
  expect(steps[0]!.waypoint.name).toBe("A");
  expect(steps[0]!.viewState).toMatchObject({
    longitude: 10,
    latitude: 20,
    zoom: 6,
    pitch: DEFAULT_TOUR_PITCH,
    bearing: 0,
    transitionDuration: 1500,
  });
  expect(steps[0]!.transitionMs).toBe(1500);
  expect(steps[0]!.dwellMs).toBe(1000);
  expect(steps[2]!.waypoint.name).toBe("C");
});

test("tourSteps appends a trailing leg back to the first waypoint when looping", () => {
  const steps = tourSteps(WPS, { loop: true });
  expect(steps).toHaveLength(4);
  expect(steps[3]!.waypoint.name).toBe("A");
  expect(steps[3]!.index).toBe(0);
});

test("tourSteps does not add a wrap leg for a single waypoint", () => {
  const steps = tourSteps([WPS[0]!], { loop: true });
  expect(steps).toHaveLength(1);
});

test("tourSteps is deterministic — same input yields identical output", () => {
  expect(tourSteps(WPS, { loop: true })).toEqual(tourSteps(WPS, { loop: true }));
});

test("tourSteps applies default transition + pitch and returns [] for no waypoints", () => {
  const steps = tourSteps(WPS, { loop: false });
  expect(steps[0]!.transitionMs).toBe(DEFAULT_TRANSITION_MS);
  expect(steps[0]!.viewState.pitch).toBe(DEFAULT_TOUR_PITCH);
  expect(tourSteps([])).toEqual([]);
});

// --- tourIterator ------------------------------------------------------------

test("tourIterator (no loop) yields each waypoint once in order then stops", () => {
  const out = [...tourIterator(WPS, { loop: false })];
  expect(out.map((s) => s.waypoint.name)).toEqual(["A", "B", "C"]);
});

test("tourIterator (loop) cycles waypoints deterministically", () => {
  const it = tourIterator(WPS, { loop: true });
  const names: string[] = [];
  for (let i = 0; i < 7; i++) names.push(it.next().value!.waypoint.name);
  expect(names).toEqual(["A", "B", "C", "A", "B", "C", "A"]);
});

test("tourIterator yields nothing for an empty tour", () => {
  expect([...tourIterator([], { loop: false })]).toEqual([]);
});

// --- defaultTourWaypoints / defaultTour --------------------------------------

test("defaultTourWaypoints returns the built-in demo AOIs when env is unset", () => {
  vi.stubEnv("VITE_TOUR_AOIS", "");
  const wps = defaultTourWaypoints();
  expect(wps.length).toBeGreaterThanOrEqual(2);
  expect(wps[0]!.name).toBe("Strait of Hormuz");
  expect(wps[0]!.dwellMs).toBe(DEFAULT_DWELL_MS);
});

test("defaultTourWaypoints parses VITE_TOUR_AOIS and skips malformed entries", () => {
  vi.stubEnv("VITE_TOUR_AOIS", "Taiwan,121,24,7,5000; ,1,2; Bad,notnum,3; Suez,32.3,30.5");
  const wps = defaultTourWaypoints();
  expect(wps).toHaveLength(2);
  expect(wps[0]).toEqual({ name: "Taiwan", longitude: 121, latitude: 24, zoom: 7, dwellMs: 5000 });
  expect(wps[1]).toMatchObject({ name: "Suez", longitude: 32.3, latitude: 30.5, zoom: 6 });
});

test("defaultTourWaypoints falls back to defaults when env has no valid entries", () => {
  vi.stubEnv("VITE_TOUR_AOIS", "garbage;,,");
  expect(defaultTourWaypoints()[0]!.name).toBe("Strait of Hormuz");
});

test("defaultTour builds looping steps over the default waypoints", () => {
  vi.stubEnv("VITE_TOUR_AOIS", "");
  const steps = defaultTour();
  const wps = defaultTourWaypoints();
  // looping adds one trailing wrap leg
  expect(steps).toHaveLength(wps.length + 1);
  expect(steps[0]!.waypoint.name).toBe("Strait of Hormuz");
});
