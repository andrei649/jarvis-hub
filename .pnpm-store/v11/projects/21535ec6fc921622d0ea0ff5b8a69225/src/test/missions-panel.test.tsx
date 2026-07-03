// @ts-nocheck
/* HUD-v3 C1 — the Console Missions board reads /api/missions and surfaces each
   workspace with its status + contextual governed-action controls. fetch is mocked,
   like kernel-safety-panels.test.tsx — asserts the wiring, the per-status display,
   and that the action buttons match the mission state machine. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MissionsPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('MissionsPanel — the Mission Workspaces board is live', () => {
  it('GETs /api/missions and lists a workspace with status + budget', async () => {
    const fn = mockFetch({ missions: [
      { id: 7, title: 'Draft Q3 brief', status: 'active', steps_used: 2, max_steps: 8 },
    ] });
    render(<MissionsPanel />);
    await waitFor(() => expect(screen.getByText('Draft Q3 brief')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/missions'))).toBe(true);
    expect(screen.getByText('active')).toBeTruthy();
    expect(screen.getByText('2/8')).toBeTruthy();
  });

  it('offers contextual controls per status (active → pause/complete/cancel; paused → resume)', async () => {
    mockFetch({ missions: [
      { id: 1, title: 'A', status: 'active', steps_used: 0, max_steps: 5 },
      { id: 2, title: 'B', status: 'paused', steps_used: 1, max_steps: 5 },
      { id: 3, title: 'C', status: 'done', steps_used: 5, max_steps: 5 },
    ] });
    render(<MissionsPanel />);
    await waitFor(() => expect(screen.getByText('pause')).toBeTruthy());
    expect(screen.getByText('complete')).toBeTruthy();
    expect(screen.getByText('resume')).toBeTruthy();      // the paused one
    // a terminal (done) mission exposes no transition buttons
    expect(screen.queryByText('start')).toBeNull();
  });

  it('POSTs the governed action to the real route when a control is clicked', async () => {
    const fn = mockFetch({ missions: [
      { id: 42, title: 'Ship it', status: 'active', steps_used: 1, max_steps: 4 },
    ] });
    render(<MissionsPanel />);
    await waitFor(() => expect(screen.getByText('pause')).toBeTruthy());
    fireEvent.click(screen.getByText('pause'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/missions/42/pause'))
    ).toBe(true));
  });
});
