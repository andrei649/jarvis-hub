// @ts-nocheck
/* H18.24 — the orb's state→visual contract, asserted for BOTH implementations.
 *
 * `frontend/src/orb.tsx` splits the orb into a pure view-model (`orbVisual`) and
 * a Canvas-2D particle renderer. Only the view-model is portable: React Native
 * has no canvas. `mobile/src/voice/orbVisual.ts` is that port.
 *
 * Two implementations of one contract is exactly how they drift, so BOTH sides
 * assert the SAME vector file (tests/_fixtures/orb_visual_vectors.json) from
 * their own suite — this file covers the browser, and
 * `mobile/src/voice/__tests__/orbVisual.test.ts` covers native. That mirrors the
 * repo's existing cross-language WorldView capability vectors (a shared fixture
 * checked by two independent suites) rather than importing across the two
 * tsconfig boundaries, which does not resolve (mobile extends expo's base).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { orbVisual as browserOrb } from '../orb';

const vectors = JSON.parse(
  readFileSync(join(__dirname, '..', '..', '..', 'tests', '_fixtures', 'orb_visual_vectors.json'), 'utf8'),
);

describe('orbVisual — one contract, two implementations', () => {
  it('has a substantial shared vector set', () => {
    expect(vectors.cases.length).toBeGreaterThan(50);
  });

  it('the BROWSER implementation reproduces every shared vector', () => {
    for (const c of vectors.cases) {
      expect({ in: c.input, out: browserOrb(c.input) }).toEqual({ in: c.input, out: c.expected });
    }
  });

  it('only reports a measured mic level while listening', () => {
    // The honesty rule the orb exists to keep: a moving sphere must mean real
    // input, never a decorative animation presented as a live signal.
    for (const impl of [browserOrb]) {
      for (const c of vectors.cases) {
        const out = impl(c.input);
        if (out.energySource === 'mic') expect(out.status).toBe('listening');
      }
    }
  });

  it('both fall back to "off" on an unknown status instead of throwing', () => {
    for (const impl of [browserOrb]) {
      expect(impl({ status: 'nonsense' }).status).toBe('off');
      expect(impl().status).toBe('off');
    }
  });
});
