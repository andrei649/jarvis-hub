// @ts-nocheck
/* The OBSERVE panel rendered the demo seed under a green LIVE badge.
 *
 * `V2.OBSERVE` ships a complete, plausible picture — 91% success rate, 847
 * interactions, 99.97% uptime, 0 errors in 24h, 3 redactions. The live hydration
 * started from that seed (`const O = { ...V2.OBSERVE }`) and every field ended in
 * `?? O.<field>`, so anything the backend did not supply silently kept the demo
 * value. `mark('OBSERVE')` then fired if ANY of the six fetches returned something
 * truthy, which stamped the whole panel LIVE.
 *
 * Two of those fetches supplied nothing at all:
 *   /api/quality     returns {stats, alert}          — `quality.success_rate` was always undefined
 *   /api/resilience  returns {metrics, circuit_breakers} — has never emitted uptime,
 *                    ssrf_blocked, errors_24h or redactions
 * Both return truthy objects, so the panel was marked live over 100% seed data.
 */
import { describe, it, expect } from 'vitest';
import { V2 } from '../data';
// The REAL shipped function, not a re-implementation. A test that copies the
// logic passes happily while the shipped path regresses — which is the same
// class of defect this file exists to prevent.
import { hydrateObserve as _hydrate } from '../api/live';

const hydrateObserve = (bench: any, quality: any, resil: any) =>
  _hydrate(bench, quality, resil, V2.OBSERVE);

// The exact payloads the two endpoints really return.
const REAL_QUALITY = { stats: { n: 12, avg_score: 0.74, min: 0.4, max: 0.9, threshold: 0.6 }, alert: { alerting: false } };
const REAL_RESILIENCE = { metrics: { 'jarvis:local': { success: 40, failure: 2, total: 42 } }, circuit_breakers: {} };

describe('the OBSERVE seed values are what made this dangerous', () => {
  it('ships a complete, plausible picture that reads as real', () => {
    // If these ever become obviously-fake placeholders the bug loses its teeth,
    // but while they look like this the fallback must not happen.
    expect(V2.OBSERVE.quality.success_rate).toBe(0.91);
    expect(V2.OBSERVE.quality.interactions).toBe(847);
    expect(V2.OBSERVE.resilience.uptime).toBe('99.97%');
  });
});

describe('quality hydration reads the real nesting', () => {
  it('takes the rolling average from stats, not the seed', () => {
    const O = hydrateObserve(null, REAL_QUALITY, null);
    expect(O.quality.success_rate).toBe(0.74);
    expect(O.quality.interactions).toBe(12);
    expect(O.quality.success_rate).not.toBe(V2.OBSERVE.quality.success_rate);
  });

  it('reports null, not the seed, for a metric the backend does not track', () => {
    const O = hydrateObserve(null, REAL_QUALITY, null);
    expect(O.quality.escalations).toBeNull();
    expect(O.quality.escalations).not.toBe(38);      // the seed value
  });

  it('reports null when quality has no data at all', () => {
    const O = hydrateObserve(null, { stats: {}, alert: { alerting: false } }, null);
    expect(O.quality.success_rate).toBeNull();
    expect(O.quality.interactions).toBeNull();
  });
});

describe('resilience hydration does not invent uptime', () => {
  it('leaves uptime null — no endpoint emits it', () => {
    const O = hydrateObserve(null, null, REAL_RESILIENCE);
    expect(O.resilience.uptime).toBeNull();
    expect(O.resilience.uptime).not.toBe('99.97%');
  });

  it('derives the error count from the per-agent failure counts it really has', () => {
    const O = hydrateObserve(null, null, REAL_RESILIENCE);
    expect(O.resilience.errors_24h).toBe(2);
    expect(O.resilience.errors_24h).not.toBe(0);     // the seed value
  });

  it('leaves ssrf_blocked and redactions null rather than borrowing 1 and 3', () => {
    const O = hydrateObserve(null, null, REAL_RESILIENCE);
    expect(O.resilience.ssrf_blocked).toBeNull();
    expect(O.resilience.redactions).toBeNull();
  });

  it('reports null errors when there are no metrics at all', () => {
    const O = hydrateObserve(null, null, { metrics: {}, circuit_breakers: {} });
    expect(O.resilience.errors_24h).toBeNull();
  });
});

describe('bench hydration', () => {
  it('takes real percentiles', () => {
    const O = hydrateObserve({ latency: { p50: 1.1, p95: 2.2, p99: 3.3 } }, null, null);
    expect(O.bench).toEqual({ p50: 1.1, p95: 2.2, p99: 3.3 });
  });

  it('nulls a percentile the payload omits instead of using the seed 4.2', () => {
    const O = hydrateObserve({ latency: { p50: 1.1 } }, null, null);
    expect(O.bench.p95).toBeNull();
    expect(O.bench.p99).toBeNull();
  });
});

describe('the whole point, stated once', () => {
  it('hydrating from the REAL payloads leaves nothing from the seed', () => {
    const O = hydrateObserve(null, REAL_QUALITY, REAL_RESILIENCE);
    const seed = V2.OBSERVE;
    expect(O.quality.success_rate).not.toBe(seed.quality.success_rate);
    expect(O.quality.interactions).not.toBe(seed.quality.interactions);
    expect(O.resilience.uptime).not.toBe(seed.resilience.uptime);
    expect(O.resilience.ssrf_blocked).not.toBe(seed.resilience.ssrf_blocked);
    expect(O.resilience.redactions).not.toBe(seed.resilience.redactions);
  });
});
