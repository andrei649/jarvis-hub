// @ts-nocheck
/* 0.62 — the Console SystemProfilePanel reads GET /api/system/profiles and renders the
   usage-mode presets with the active one marked + each profile's knobs (model_tier,
   no-heavy, no-bg). fetch is mocked (like system-profile siblings).

   DRA-44 adds the hardware leg: GET /api/system/hardware — the spec score, the
   profile the box suggests, and (the load-bearing part) `not measured` instead of a
   numeral for any component that was never probed. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { SystemProfilePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('SystemProfilePanel — usage-mode presets', () => {
  it('GETs /api/system/profiles and marks the active profile + its knobs', async () => {
    const fn = mockFetch({
      active: 'gaming',
      default: 'balanced',
      profiles: {
        balanced: { description: 'd', background_autonomy: true, heavy_features: true, max_parallel_agents: null, model_tier: 'auto' },
        gaming: { description: 'd', background_autonomy: false, heavy_features: false, max_parallel_agents: 1, model_tier: 'local-light' },
      },
    });
    render(<SystemProfilePanel />);
    await waitFor(() => expect(screen.getByText('▸ gaming')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/system/profiles'))).toBe(true);
    // the active (gaming) profile shows its constrained knobs
    expect(screen.getByText('local-light')).toBeTruthy();
    expect(screen.getByText('no-heavy')).toBeTruthy();
    expect(screen.getByText('no-bg')).toBeTruthy();
  });
});

function mockRoutes(routes) {
  const fn = vi.fn().mockImplementation(async (url) => {
    const u = String(url);
    const hit = Object.keys(routes).find((k) => u.includes(k));
    return { ok: true, status: 200, json: async () => (hit ? routes[hit] : {}) };
  });
  global.fetch = fn;
  return fn;
}

const PROFILES = {
  active: 'balanced',
  default: 'balanced',
  profiles: {
    balanced: { description: 'd', background_autonomy: true, heavy_features: true, max_parallel_agents: null, model_tier: 'auto' },
    headless: { description: 'd', background_autonomy: true, heavy_features: false, max_parallel_agents: 1, model_tier: 'local-light' },
  },
};

describe('SystemProfilePanel — the DRA-44 hardware leg', () => {
  it('renders the spec score, the tier and the recommended profile beside the active one', async () => {
    const fn = mockRoutes({
      '/api/system/profiles': PROFILES,
      '/api/system/hardware': {
        detected: { gpu: { name: 'big card', vram_total_mb: 24576, measured: true }, cpu_threads: 32, ram_total_gb: 128 },
        score: { score: 100, tier: 'high', components: { gpu: 'measured', cpu: 'measured', ram: 'measured' }, reasons: ['big card · 24576 MB VRAM'] },
        recommended_profile: 'ai',
        active_profile: 'balanced',
      },
    });
    render(<SystemProfilePanel />);
    await waitFor(() => expect(screen.getByText(/recommended · ai/)).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/system/hardware'))).toBe(true);
    expect(screen.getByText(/high/)).toBeTruthy();
    expect(screen.getByText(/24576 MB/)).toBeTruthy();
  });

  it('prints "not measured" instead of a numeral for an unprobed component', async () => {
    mockRoutes({
      '/api/system/profiles': PROFILES,
      '/api/system/hardware': {
        detected: { gpu: { name: 'none', vram_total_mb: null, measured: false }, cpu_threads: 8, ram_total_gb: 32 },
        score: { score: 18, tier: 'low', components: { gpu: 'not_measured', cpu: 'measured', ram: 'measured' }, reasons: [] },
        recommended_profile: 'headless',
        active_profile: 'balanced',
      },
    });
    render(<SystemProfilePanel />);
    await waitFor(() => expect(screen.getByText(/gpu · not measured/)).toBeTruthy());
    // never a 0 or a dash standing in for VRAM we did not probe
    expect(screen.queryByText(/0 MB/)).toBeNull();
    expect(screen.getByText(/recommended · headless/)).toBeTruthy();
  });
});
