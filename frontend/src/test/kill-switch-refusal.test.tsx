// @ts-nocheck
/* 2026-07-27 QA run, finding F-02 — a refused halt must never look like a working one.
   Engaging the kill-switch is kernel-mediated (agents/core/routers/security.py) and
   answers 403 "kernel denied" without a capability token. `actA` swallowed every
   rejection, so the run pressed HALT ALL and got no error, no state change, and no hint
   it had been refused: the card kept reading "ARMED · operational". For a safety control
   that is a false-safety state, not a cosmetic gap. fetch is mocked, like
   backup-panel.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { KillSwitchPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

/** GET returns `status`; POST returns `postStatus` (403 by default = kernel denied). */
function mockFetch(status, postStatus = 403) {
  const fn = vi.fn().mockImplementation((_url, init) => {
    if ((init?.method || 'GET') === 'POST') {
      return Promise.resolve({ ok: postStatus < 400, status: postStatus, json: async () => ({}) });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => status });
  });
  global.fetch = fn;
  return fn;
}

describe('KillSwitchPanel — a refused halt is reported, not hidden', () => {
  it('reads ARMED when nothing is halted', async () => {
    mockFetch({ global: false, halted: {} });
    render(<KillSwitchPanel />);
    await waitFor(() => expect(screen.getByText(/ARMED · operational/)).toBeTruthy());
  });

  it('says HALT REFUSED and keeps the true state when the POST is denied', async () => {
    mockFetch({ global: false, halted: {} }, 403);
    render(<KillSwitchPanel />);
    await waitFor(() => expect(screen.getByText('HALT ALL')).toBeTruthy());
    fireEvent.click(screen.getByText('HALT ALL'));
    // the operator must be told the switch did not move
    const alert = await waitFor(() => screen.getByRole('alert'));
    expect(alert.textContent).toMatch(/HALT REFUSED/);
    expect(alert.textContent).toMatch(/403/);
    expect(alert.textContent).toMatch(/did NOT change state/);
    // and the state shown stays honest (still ARMED — because it really is)
    expect(screen.getByText(/ARMED · operational/)).toBeTruthy();
  });

  it('re-reads state after a refusal, so the card can never drift from the server', async () => {
    const fn = mockFetch({ global: false, halted: {} }, 403);
    render(<KillSwitchPanel />);
    await waitFor(() => expect(screen.getByText('HALT ALL')).toBeTruthy());
    const getsBefore = fn.mock.calls.filter((c) => (c[1]?.method || 'GET') === 'GET').length;
    fireEvent.click(screen.getByText('HALT ALL'));
    await waitFor(() => expect(
      fn.mock.calls.filter((c) => (c[1]?.method || 'GET') === 'GET').length,
    ).toBeGreaterThan(getsBefore));
  });

  it('shows ENGAGED when the switch really is engaged', async () => {
    mockFetch({ global: true, halted: { global: { reason: 'hud' } } });
    render(<KillSwitchPanel />);
    await waitFor(() => expect(screen.getByText(/ENGAGED · all agents halted/)).toBeTruthy());
    expect(screen.getByText('disengage')).toBeTruthy();
  });

  it('does not show a stale refusal banner on a later successful toggle', async () => {
    mockFetch({ global: false, halted: {} }, 403);
    render(<KillSwitchPanel />);
    await waitFor(() => expect(screen.getByText('HALT ALL')).toBeTruthy());
    fireEvent.click(screen.getByText('HALT ALL'));
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    mockFetch({ global: false, halted: {} }, 200);   // now permitted
    fireEvent.click(screen.getByText('HALT ALL'));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
});

describe('KillSwitchPanel — an unread state is never reported as ARMED', () => {
  it('says UNKNOWN, not "ARMED · operational", when the status GET fails', async () => {
    // The card derived `halted` from an empty response, and false meant ARMED. So a
    // status read that never came back told the operator the safety system was fine.
    // For a kill-switch that is the worst possible default direction.
    global.fetch = vi.fn().mockRejectedValue(new Error('network down'));
    render(<KillSwitchPanel />);
    await waitFor(() =>
      expect(screen.getByText(/UNKNOWN · could not read kill-switch state/)).toBeTruthy());
    expect(screen.queryByText(/ARMED · operational/)).toBeNull();
  });

  it('says UNKNOWN while the status is still in flight', async () => {
    global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));  // never resolves
    render(<KillSwitchPanel />);
    expect(screen.queryByText(/ARMED · operational/)).toBeNull();
    expect(screen.getByText(/UNKNOWN · could not read kill-switch state/)).toBeTruthy();
  });

  it('still offers HALT ALL when the state is unknown — halting is the safe direction', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('network down'));
    render(<KillSwitchPanel />);
    await waitFor(() => expect(screen.getByText(/UNKNOWN/)).toBeTruthy());
    expect(screen.getByText('HALT ALL')).toBeTruthy();
  });

  it('reports ENGAGED normally once a real halted state is read', async () => {
    mockFetch({ global: true, halted: {} });
    render(<KillSwitchPanel />);
    await waitFor(() => expect(screen.getByText(/ENGAGED · all agents halted/)).toBeTruthy());
  });
});
