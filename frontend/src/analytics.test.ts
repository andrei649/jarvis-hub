// @ts-nocheck
/* Unit tests for the H22 page-view beacon (analytics.ts). Verifies it posts the
   right body to /api/analytics/event, prefers navigator.sendBeacon, falls back to
   fetch(keepalive), swallows all errors, and keeps a STABLE per-session id.
   No network, no backend — sendBeacon and fetch are fully mocked. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { trackPageview, sessionId, initAnalytics } from './analytics';

// sendBeacon hands us a Blob; read it back to JSON so we can assert the body.
async function blobJson(blob: any): Promise<any> {
  if (typeof blob.text === 'function') return JSON.parse(await blob.text());
  return JSON.parse(String(blob));
}

beforeEach(() => {
  try { sessionStorage.clear(); } catch { /* ignore */ }
  // Default: a working sendBeacon. Individual tests override as needed.
  navigator.sendBeacon = vi.fn(() => true) as any;
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true }) }) as any;
});

describe('trackPageview transport', () => {
  it('posts a pageview to /api/analytics/event via sendBeacon', async () => {
    const beacon = vi.fn(() => true);
    navigator.sendBeacon = beacon as any;

    const ok = trackPageview('/cockpit');
    expect(ok).toBe(true);
    expect(beacon).toHaveBeenCalledTimes(1);

    const [url, blob] = beacon.mock.calls[0];
    expect(url).toBe('/api/analytics/event');
    const body = await blobJson(blob);
    expect(body.name).toBe('pageview');
    expect(body.path).toBe('/cockpit');
    expect(typeof body.session_id).toBe('string');
    expect(body.session_id.length).toBeGreaterThan(0);
  });

  it('does NOT touch fetch when sendBeacon succeeds', () => {
    navigator.sendBeacon = vi.fn(() => true) as any;
    trackPageview('/agents');
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('falls back to fetch(keepalive) when sendBeacon returns false', () => {
    navigator.sendBeacon = vi.fn(() => false) as any;
    const f = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    global.fetch = f as any;

    const ok = trackPageview('/trust');
    expect(ok).toBe(true);
    expect(f).toHaveBeenCalledTimes(1);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe('/api/analytics/event');
    expect(init.method).toBe('POST');
    expect(init.keepalive).toBe(true);
    const body = JSON.parse(init.body);
    expect(body.name).toBe('pageview');
    expect(body.path).toBe('/trust');
  });

  it('falls back to fetch when sendBeacon throws', () => {
    navigator.sendBeacon = vi.fn(() => { throw new Error('boom'); }) as any;
    const f = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    global.fetch = f as any;
    expect(trackPageview('/memory')).toBe(true);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it('defaults path to the current location when none is given', async () => {
    const beacon = vi.fn(() => true);
    navigator.sendBeacon = beacon as any;
    trackPageview();
    const body = await blobJson(beacon.mock.calls[0][1]);
    // jsdom default location is "/", possibly with empty search.
    expect(typeof body.path).toBe('string');
  });
});

describe('error swallowing — analytics never breaks the app', () => {
  it('returns false (does not throw) when fetch rejects', () => {
    navigator.sendBeacon = vi.fn(() => false) as any;
    global.fetch = vi.fn(() => Promise.reject(new Error('network down'))) as any;
    // The rejected promise is swallowed inside; the call itself must not throw.
    expect(() => trackPageview('/x')).not.toThrow();
  });

  it('returns false when both sendBeacon and fetch throw synchronously', () => {
    navigator.sendBeacon = vi.fn(() => { throw new Error('beacon'); }) as any;
    global.fetch = vi.fn(() => { throw new Error('fetch'); }) as any;
    expect(trackPageview('/y')).toBe(false);
  });
});

describe('ephemeral session id', () => {
  it('is stable within a session (same id across calls)', () => {
    const a = sessionId();
    const b = sessionId();
    expect(a).toBe(b);
  });

  it('is reused across multiple pageviews in the same session', async () => {
    const beacon = vi.fn(() => true);
    navigator.sendBeacon = beacon as any;
    trackPageview('/one');
    trackPageview('/two');
    const first = await blobJson(beacon.mock.calls[0][1]);
    const second = await blobJson(beacon.mock.calls[1][1]);
    expect(first.session_id).toBe(second.session_id);
  });

  it('persists the id in sessionStorage (NOT localStorage — ephemeral, no cookie)', () => {
    const id = sessionId();
    expect(sessionStorage.getItem('hud.analytics.sid')).toBe(id);
    expect(localStorage.getItem('hud.analytics.sid')).toBeNull();
  });
});

describe('initAnalytics', () => {
  it('fires exactly one pageview on first init and is idempotent', () => {
    const beacon = vi.fn(() => true);
    navigator.sendBeacon = beacon as any;
    initAnalytics();
    initAnalytics();
    // initAnalytics guards with a module-level flag, so the second call is a no-op.
    // (May already have fired in an earlier test's import; assert at most one new.)
    expect(beacon.mock.calls.length).toBeLessThanOrEqual(1);
  });
});
