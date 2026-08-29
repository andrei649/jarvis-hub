import { describe, expect, it } from '@jest/globals';
import { orbVisual } from '../orbVisual';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');

// The SAME file the browser suite asserts (frontend/src/test/orb-contract.test.ts),
// so a change to either implementation that isn't made to both fails here.
const vectorsPath = join(__dirname, '..', '..', '..', '..', 'tests', '_fixtures', 'orb_visual_vectors.json');
const { cases } = JSON.parse(readFileSync(vectorsPath, 'utf8'));

describe('H18.24 — native orbVisual matches the browser contract', () => {
  it('loads the shared vector file', () => {
    expect(Array.isArray(cases)).toBe(true);
    expect(cases.length).toBeGreaterThan(50);
  });

  it('reproduces every shared vector exactly', () => {
    for (const c of cases) {
      expect({ input: c.input, out: orbVisual(c.input) })
        .toEqual({ input: c.input, out: c.expected });
    }
  });

  it('only ever reports a measured mic level while listening', () => {
    // The honesty rule the orb exists to keep: a moving sphere must mean real
    // input, never a decorative animation dressed up as a live signal.
    for (const c of cases) {
      const out = orbVisual(c.input);
      if (out.energySource === 'mic') expect(out.status).toBe('listening');
    }
  });

  it('falls back to "off" for an unknown status instead of throwing', () => {
    expect(orbVisual({ status: 'nonsense' }).status).toBe('off');
    expect(orbVisual().status).toBe('off');
  });
});
