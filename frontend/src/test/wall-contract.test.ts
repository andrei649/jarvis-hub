// @ts-nocheck
/* H18.25 — the briefing wall's state contract, asserted against shared vectors.
 *
 * wall.tsx is a canvas-composed board; only `wallState` (the word + tone it
 * announces) is portable to native. Both implementations assert the SAME file
 * (tests/_fixtures/wall_state_vectors.json) from their own suite — this covers
 * the browser, mobile/src/voice/__tests__/wallState.test.ts covers native.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { wallState } from '../wall';

const vectors = JSON.parse(
  readFileSync(join(__dirname, '..', '..', '..', 'tests', '_fixtures', 'wall_state_vectors.json'), 'utf8'),
);

describe('wallState — one contract, two implementations', () => {
  it('has a substantial shared vector set', () => {
    expect(vectors.cases.length).toBeGreaterThan(100);
  });

  it('reproduces every shared vector', () => {
    for (const c of vectors.cases) {
      expect({ in: c.input, out: wallState(c.input) }).toEqual({ in: c.input, out: c.expected });
    }
  });

  it('an explicit voice error outranks every other signal', () => {
    // Ordering is the load-bearing part: a real error must never be masked by
    // "working" or "standing by".
    expect(wallState({ voice: { status: 'listening', error: 'x' }, serverUp: true }))
      .toEqual({ word: 'voice error', tone: 'bad' });
  });

  it('never reports offline while work is actually running', () => {
    expect(wallState({ tasks: [{ state: 'running' }], serverUp: false }).word).toBe('working');
    expect(wallState({ agents: [{ status: 'busy' }], serverUp: false }).word).toBe('working');
  });
});
