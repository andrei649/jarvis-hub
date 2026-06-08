import { test, expect } from "vitest";
import {
  REPLAY_FPS,
  replayStep,
  replaySampleAt,
  replaySequence,
} from "../replaySchedule";

test("replayStep is speed / fps", () => {
  expect(replayStep(60)).toBeCloseTo(60 / REPLAY_FPS);
  expect(replayStep(10)).toBeCloseTo(10 / REPLAY_FPS);
});

test("replaySampleAt steps linearly and clamps to `to`", () => {
  expect(replaySampleAt(1000, 1100, 30, 0)).toBe(1000); // starts at from
  expect(replaySampleAt(1000, 1100, 30, 1)).toBeCloseTo(1001); // +1s at 30× / 30fps
  expect(replaySampleAt(1000, 1100, 30, 100_000)).toBe(1100); // clamped to to
});

test("two runs of the same window produce the identical masterTime sequence", () => {
  // Reproducibility guarantee: the sampled sequence is a pure function of {from,to,speed},
  // independent of frame cadence. Same args → byte-identical arrays.
  const a = replaySequence(1_700_000_000, 1_700_000_900, 60);
  const b = replaySequence(1_700_000_000, 1_700_000_900, 60);
  expect(a).toEqual(b);
});

test("a different speed produces a different (still deterministic) sequence", () => {
  const slow = replaySequence(0, 300, 10);
  const fast = replaySequence(0, 300, 60);
  expect(fast.length).toBeLessThan(slow.length); // fewer frames at higher speed
  // but each is itself reproducible
  expect(replaySequence(0, 300, 60)).toEqual(fast);
});

test("sequence always begins at `from` and ends exactly at `to`", () => {
  const seq = replaySequence(50, 123, 17);
  expect(seq[0]).toBe(50);
  expect(seq[seq.length - 1]).toBe(123);
  // monotonic non-decreasing
  for (let i = 1; i < seq.length; i += 1) expect(seq[i]!).toBeGreaterThanOrEqual(seq[i - 1]!);
});

test("degenerate window (to <= from) or non-positive speed yields a single sample at `to`", () => {
  expect(replaySequence(100, 100, 60)).toEqual([100]);
  expect(replaySequence(100, 50, 60)).toEqual([50]);
  expect(replaySequence(0, 100, 0)).toEqual([100]);
});
