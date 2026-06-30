// @ts-nocheck
/* 0.62 — the Console SystemProfilePanel reads GET /api/system/profiles and renders the
   usage-mode presets with the active one marked + each profile's knobs (model_tier,
   no-heavy, no-bg). fetch is mocked (like system-profile siblings). */
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
