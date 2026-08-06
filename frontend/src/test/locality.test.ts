// @ts-nocheck
/* The App-level %-on-device derivation. A hand-built props fixture cannot reach these
   branches: in DEMO the app skips locality loading and the loader clears it, so the demo
   fallback is only reachable through this path. Pinned here because a strict-local 100%
   is an inference from governance, not a measurement, and the wall must be told which. */
import { describe, it, expect } from 'vitest';
import { localityFigure } from '../locality';

describe('localityFigure — the number and where it came from', () => {
  it('prefers a real measured split over everything else', () => {
    expect(localityFigure({ locality: { local_pct: 94 }, trust: { strict_local: true }, demo: true }))
      .toEqual({ pct: 94, source: 'measured' });
  });

  it('reports strict-local 100% as DERIVED, never as measured', () => {
    const r = localityFigure({ locality: null, trust: { strict_local: true }, demo: false });
    expect(r.pct).toBe(100);
    expect(r.source).toBe('strict-local');
    expect(r.source).not.toBe('measured');
  });

  it('only a literal boolean true counts as strict-local', () => {
    expect(localityFigure({ trust: { strict_local: 'true' } }).source).toBeNull();
    expect(localityFigure({ trust: { strict_local: 1 } }).source).toBeNull();
  });

  it('falls back to the demo sample only in demo, and to nothing otherwise', () => {
    expect(localityFigure({ demo: true })).toEqual({ pct: 87, source: 'seeded' });
    expect(localityFigure({ demo: false })).toEqual({ pct: null, source: null });
    expect(localityFigure()).toEqual({ pct: null, source: null });
  });

  it('demo with a measured split reports measured, not seeded', () => {
    expect(localityFigure({ locality: { local_pct: 91 }, demo: true }).source).toBe('measured');
  });
});
