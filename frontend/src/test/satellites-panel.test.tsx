// @ts-nocheck
/* HUD-v3 §4.4 — the Console Mic Satellites panel reads the satellite hub
   (/api/satellites), pairs a device (POST /api/satellites/register) and unpairs one
   (DELETE /api/satellites/{id}). fetch is mocked, like kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SatellitesPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('SatellitesPanel — the mic-satellite pairing flow is live', () => {
  it('GETs /api/satellites and lists a paired device with its kind', async () => {
    const fn = mockFetch({ satellites: [
      { id: 'pixel-8', kind: 'mic', last_seen: 1 },
    ], stats: {} });
    render(<SatellitesPanel />);
    await waitFor(() => expect(screen.getByText('pixel-8')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/satellites'))).toBe(true);
    expect(screen.getByText('mic')).toBeTruthy();
  });

  it('pairs a device (POST /api/satellites/register) only when an id is given', async () => {
    const fn = mockFetch({ satellites: [], stats: {} });
    render(<SatellitesPanel />);
    await waitFor(() => expect(screen.getByText('pair')).toBeTruthy());
    // empty id → no register
    fireEvent.click(screen.getByText('pair'));
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/satellites/register'))).toBe(false);
    // with id → POST {satellite_id}
    fireEvent.change(screen.getByPlaceholderText('device id (pair a phone as a mic)'), { target: { value: 'iphone-15' } });
    fireEvent.click(screen.getByText('pair'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/satellites/register')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"satellite_id":"iphone-15"'))
    ).toBe(true));
  });

  it('unpairs a satellite (DELETE /api/satellites/{id})', async () => {
    const fn = mockFetch({ satellites: [{ id: 'tablet-2', kind: 'mic' }], stats: {} });
    render(<SatellitesPanel />);
    await waitFor(() => expect(screen.getByText('tablet-2')).toBeTruthy());
    fireEvent.click(screen.getByTitle('unpair'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/satellites/tablet-2') && c[1]?.method === 'DELETE')
    ).toBe(true));
  });
});
