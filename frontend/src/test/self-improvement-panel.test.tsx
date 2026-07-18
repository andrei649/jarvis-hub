// @ts-nocheck
/* Self-Improvement dashboard panel — reads the real aggregation endpoint
   (/api/self-improvement/status, admin-guarded) and renders per-subsystem
   on/off state plus the enable-bundle action. fetch is mocked, like
   governance-posture-panel.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SelfImprovementPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

const STATUS_PAYLOAD = {
  available: true,
  errors: { window_hours: 48, active_groups: 2, top: [] },
  observer: { enabled: true, probes: 2, tracked: 1, unhealthy: [] },
  acquisition: { enabled: false, status: 'disabled', states: {}, reuse: {} },
  ambient: { enabled: false, status: 'disabled', monitors: 0 },
  tech_scout: { enabled: false, available: true, last_run: null, queries: [], total_seen: 0 },
};

describe('SelfImprovementPanel — the self-improvement dashboard is live', () => {
  it('GETs /api/self-improvement/status and shows per-subsystem state', async () => {
    const fn = mockFetch(STATUS_PAYLOAD);
    render(<SelfImprovementPanel />);
    await waitFor(() => expect(screen.getByText('2 groups')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/self-improvement/status'))).toBe(true);
    expect(screen.getByText('never run')).toBeTruthy();
  });

  it('offers the enable-bundle action when a subsystem is off, and posts on click', async () => {
    mockFetch(STATUS_PAYLOAD);
    render(<SelfImprovementPanel />);
    await waitFor(() => expect(screen.getByText('enable bundle')).toBeTruthy());

    const postFn = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ applied: { cognition: { enabled: true, review_enabled: true } } }),
    });
    global.fetch = postFn;
    fireEvent.click(screen.getByText('enable bundle'));
    await waitFor(() => expect(postFn.mock.calls.some((c) => String(c[0]).includes('/api/self-improvement/enable'))).toBe(true));
  });

  it('hides the enable-bundle action once every subsystem is already on', async () => {
    mockFetch({
      ...STATUS_PAYLOAD,
      acquisition: { ...STATUS_PAYLOAD.acquisition, enabled: true },
      ambient: { ...STATUS_PAYLOAD.ambient, enabled: true },
      tech_scout: { ...STATUS_PAYLOAD.tech_scout, enabled: true },
    });
    render(<SelfImprovementPanel />);
    await waitFor(() => expect(screen.getByText('2 groups')).toBeTruthy());
    expect(screen.queryByText('enable bundle')).toBeNull();
  });
});
