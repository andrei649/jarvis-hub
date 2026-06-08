// Scripted camera tours (ticket H19.5.4, remaining slice).
//
// A pure, deterministic tour model: an ordered list of waypoints, each a camera pose over an
// AOI plus how long to dwell there. `tourSteps()` yields the transition for each leg (the deck
// viewState to fly to + the transition + dwell durations), so the UI layer only has to apply
// each step with setViewState and a timer — no animation logic leaks into this module, which
// keeps it unit-testable without a WebGL context.
//
// The default tour sweeps the platform's demo AOIs (Strait of Hormuz and its neighbours). AOIs
// can be overridden via NEXT_PUBLIC_TOUR_AOIS (read at call time so tests can stub it), falling
// back to a built-in constant.

/** One stop on a camera tour: a globe pose over an AOI and how long to linger. */
export interface Waypoint {
  longitude: number;
  latitude: number;
  zoom: number;
  /** Human-readable AOI name, shown in the tour HUD. */
  name: string;
  /** How long to hold on this waypoint before flying to the next, in ms. */
  dwellMs: number;
}

/** A deck viewState target for a tour leg (subset deck consumes; pitch/bearing optional). */
export interface TourViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch?: number;
  bearing?: number;
  /** Deck transition duration (ms) for flying into this waypoint. */
  transitionDuration: number;
}

/** A single tour step: which waypoint, the deck viewState to fly to, and the timings. */
export interface TourStep {
  /** Index of this waypoint in the tour's waypoint list. */
  index: number;
  waypoint: Waypoint;
  viewState: TourViewState;
  /** Fly-in time to this waypoint (ms). */
  transitionMs: number;
  /** Dwell after arriving, before the next step (ms). */
  dwellMs: number;
}

export interface TourOptions {
  /** Fly-in duration between waypoints, ms. Default 2500. */
  transitionMs?: number;
  /** Camera pitch held through the tour. Default 30 (matches the map's initial view). */
  pitch?: number;
  /** Loop back to the first waypoint after the last. Default true. */
  loop?: boolean;
}

/** Default fly-in duration between waypoints (ms). */
export const DEFAULT_TRANSITION_MS = 2500;
/** Default dwell on a waypoint when one isn't specified (ms). */
export const DEFAULT_DWELL_MS = 4000;
/** Default camera pitch for the tour. */
export const DEFAULT_TOUR_PITCH = 30;

// Built-in demo AOIs — the Strait of Hormuz reference choke point and its neighbourhood.
// Mirrors DeckGlobe's INITIAL_VIEW_STATE centroid; kept here so the tour is self-contained.
const DEFAULT_AOIS: Waypoint[] = [
  { name: "Strait of Hormuz", longitude: 56.4, latitude: 26.6, zoom: 6, dwellMs: DEFAULT_DWELL_MS },
  { name: "Bandar Abbas", longitude: 56.28, latitude: 27.18, zoom: 7, dwellMs: DEFAULT_DWELL_MS },
  { name: "Strait of Bab-el-Mandeb", longitude: 43.35, latitude: 12.58, zoom: 6, dwellMs: DEFAULT_DWELL_MS },
  { name: "Suez Canal", longitude: 32.35, latitude: 30.5, zoom: 6, dwellMs: DEFAULT_DWELL_MS },
];

/**
 * Parse NEXT_PUBLIC_TOUR_AOIS into waypoints, or return the built-in default tour. The env
 * format is a semicolon-separated list of `name,lng,lat[,zoom[,dwellMs]]`. Malformed entries
 * are skipped; an empty/unset env yields the default. Read at call time, so tests can stub it.
 */
export function defaultTourWaypoints(): Waypoint[] {
  const raw = (process.env.NEXT_PUBLIC_TOUR_AOIS ?? "").trim();
  if (raw === "") return DEFAULT_AOIS.map((w) => ({ ...w }));
  const parsed: Waypoint[] = [];
  for (const entry of raw.split(";")) {
    const parts = entry.split(",").map((s) => s.trim());
    if (parts.length < 3) continue;
    const [name, lngStr, latStr, zoomStr, dwellStr] = parts;
    const longitude = Number(lngStr);
    const latitude = Number(latStr);
    if (!name || !Number.isFinite(longitude) || !Number.isFinite(latitude)) continue;
    const zoom = Number.isFinite(Number(zoomStr)) ? Number(zoomStr) : 6;
    const dwellMs = Number.isFinite(Number(dwellStr)) ? Number(dwellStr) : DEFAULT_DWELL_MS;
    parsed.push({ name, longitude, latitude, zoom, dwellMs });
  }
  return parsed.length > 0 ? parsed : DEFAULT_AOIS.map((w) => ({ ...w }));
}

/**
 * Build the ordered list of tour steps for `waypoints`. Pure + deterministic: same input → same
 * output. Each step carries the deck viewState to fly to (with transitionDuration) plus the
 * dwell. With `loop` (default) an extra trailing step flies back to the first waypoint so the
 * tour cycles seamlessly; without it the tour ends on the last waypoint.
 */
export function tourSteps(waypoints: Waypoint[], opts: TourOptions = {}): TourStep[] {
  const transitionMs = opts.transitionMs ?? DEFAULT_TRANSITION_MS;
  const pitch = opts.pitch ?? DEFAULT_TOUR_PITCH;
  const loop = opts.loop ?? true;
  if (waypoints.length === 0) return [];

  const toStep = (wp: Waypoint, index: number): TourStep => ({
    index,
    waypoint: wp,
    viewState: {
      longitude: wp.longitude,
      latitude: wp.latitude,
      zoom: wp.zoom,
      pitch,
      bearing: 0,
      transitionDuration: transitionMs,
    },
    transitionMs,
    dwellMs: wp.dwellMs,
  });

  const steps = waypoints.map(toStep);
  if (loop && waypoints.length > 1) {
    // Trailing leg back to the first waypoint, so play wraps without a jump.
    steps.push({ ...toStep(waypoints[0]!, 0) });
  }
  return steps;
}

/**
 * A deterministic iterator over a tour's steps. Honors `loop` (default true): when looping it
 * yields steps forever (cycling); otherwise it stops after the last waypoint. Pull-based so the
 * UI can drive it from a timer (advance on each dwell) without re-deriving the step list.
 */
export function* tourIterator(
  waypoints: Waypoint[],
  opts: TourOptions = {},
): Generator<TourStep, void, unknown> {
  const loop = opts.loop ?? true;
  if (waypoints.length === 0) return;

  // Non-looping path: yield each waypoint once, in order.
  const linear = tourSteps(waypoints, { ...opts, loop: false });
  if (!loop) {
    for (const step of linear) yield step;
    return;
  }
  // Looping path: cycle the waypoints forever (no synthetic trailing duplicate).
  let i = 0;
  while (true) {
    yield linear[i % linear.length]!;
    i += 1;
  }
}

/** Convenience: the default demo tour's steps (looping), for the UI's "Tour" control. */
export function defaultTour(opts: TourOptions = {}): TourStep[] {
  return tourSteps(defaultTourWaypoints(), opts);
}
