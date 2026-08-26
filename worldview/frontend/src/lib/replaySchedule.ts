// Deterministic replay schedule (H19.2.7, reproducibility fix).
//
// The replay used to integrate wall-clock RAF deltas (cur += dt × speed), so the sampled
// masterTimes depended on the machine's frame cadence — two runs of the same link produced
// different timestamp sequences and weren't frame-reproducible. Instead we advance on a fixed
// schedule: a frame counter at a fixed fps, stepping `speed / fps` seconds per frame. The
// sequence of sampled masterTimes is then a pure function of {from, to, speed}, independent of
// how fast RAF actually fires (a dropped/late frame just means we skip frames, never resample at
// a different point). The RAF loop only decides *when* to read the next scheduled sample.

/** The fixed virtual frame rate the schedule steps at. Decoupled from real RAF cadence. */
export const REPLAY_FPS = 30;

/** Seconds of master time advanced per scheduled frame at a given speed multiplier. */
export function replayStep(speed: number): number {
  return speed / REPLAY_FPS;
}

/**
 * The masterTime for frame `n` (n ≥ 0) of a replay window, clamped to `to`. Pure: depends only on
 * {from, to, speed} and the frame index, never on wall-clock timing.
 */
export function replaySampleAt(
  from: number,
  to: number,
  speed: number,
  frame: number,
): number {
  return Math.min(to, from + frame * replayStep(speed));
}

/**
 * The full, deterministic sequence of sampled masterTimes for a replay window: [from, …, to].
 * Always starts at `from` and ends exactly at `to`. A degenerate window (to ≤ from) or a
 * non-positive speed yields a single sample at `to`. Pure — two calls with the same args return
 * identical sequences, which is the reproducibility guarantee.
 */
export function replaySequence(from: number, to: number, speed: number): number[] {
  if (!(to > from) || !(speed > 0)) return [to];
  const seq: number[] = [];
  const step = replayStep(speed);
  for (let frame = 0; ; frame += 1) {
    const t = from + frame * step;
    if (t >= to) break;
    seq.push(t);
  }
  seq.push(to);
  return seq;
}
