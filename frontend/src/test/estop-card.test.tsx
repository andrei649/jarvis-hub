// @ts-nocheck
/* AUTONOMY PAUSE (ESTOP) card in Admin — a pause control must never lie about
   whether it is holding: an unread state renders "not connected", never RELEASED,
   and engage is a deliberate two-step confirm (mirrors kill-switch-refusal.test.tsx). */
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AdminMode } from '../modes3';

const t = { admin: 'ADMIN' };

function mockEstop(getPayload, postPayload = {}) {
  const fn = vi.fn((url, init) => {
    if ((init?.method || 'GET') === 'GET' && String(url) === '/api/ops/estop') {
      return Promise.resolve({ ok: true, status: 200, json: async () => getPayload });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => postPayload });
  });
  global.fetch = fn;
  return fn;
}

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe('EstopCard (AUTONOMY PAUSE)', () => {
  it('is named distinctly from the Trust kill-switch and reads RELEASED when disengaged', async () => {
    mockEstop({ engaged: false, state: null });
    render(<AdminMode t={t} />);
    await waitFor(() => expect(screen.getByText(/RELEASED · autonomy running/)).toBeTruthy());
    expect(screen.getByText(/AUTONOMY PAUSE \(ESTOP\)/)).toBeTruthy();
    expect(screen.queryByText(/EMERGENCY STOP/)).toBeNull();
    expect(screen.queryByText(/halt all agents/i)).toBeNull();
  });

  it('never shows RELEASED when the state read fails', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('network down'));
    render(<AdminMode t={t} />);
    await waitFor(() => expect(screen.getByText(/estop state unavailable/)).toBeTruthy());
    expect(screen.queryByText(/RELEASED/)).toBeNull();
  });

  it('engages only through the two-step confirm and posts the trimmed reason', async () => {
    const fn = mockEstop({ engaged: false, state: null }, { engaged: true, state: { reason: 'drill', engaged_at: 't1' } });
    render(<AdminMode t={t} />);
    await waitFor(() => expect(screen.getByText('Pause new autonomous work…')).toBeTruthy());
    // step 1 arms the confirm — nothing is posted yet
    fireEvent.click(screen.getByText('Pause new autonomous work…'));
    expect(fn.mock.calls.filter(([, init]) => init?.method === 'POST').length).toBe(0);
    expect(screen.getByText(/CONFIRM PAUSE/)).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('reason (optional)'), { target: { value: ' drill ' } });
    fireEvent.click(screen.getByText('Confirm pause'));
    await waitFor(() => expect(screen.getByText(/PAUSED · new autonomous work held/)).toBeTruthy());
    const post = fn.mock.calls.find(([url, init]) => init?.method === 'POST');
    expect(String(post[0])).toBe('/api/ops/estop/engage');
    expect(JSON.parse(post[1].body)).toEqual({ reason: 'drill' });
    expect(screen.getByText(/reason: drill · since t1/)).toBeTruthy();
  });

  it('cancel backs out of the confirm without posting', async () => {
    const fn = mockEstop({ engaged: false, state: null });
    render(<AdminMode t={t} />);
    await waitFor(() => expect(screen.getByText('Pause new autonomous work…')).toBeTruthy());
    fireEvent.click(screen.getByText('Pause new autonomous work…'));
    fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() => expect(screen.getByText(/RELEASED · autonomy running/)).toBeTruthy());
    expect(fn.mock.calls.filter(([, init]) => init?.method === 'POST').length).toBe(0);
  });

  it('resumes with a single admin-authenticated click and re-syncs from the response', async () => {
    localStorage.setItem('hud.admin_token', 'admin-secret');
    const fn = mockEstop({ engaged: true, state: { reason: 'drill', engaged_at: 't1' } }, { engaged: false, lifted: true });
    render(<AdminMode t={t} />);
    await waitFor(() => expect(screen.getByText(/PAUSED · new autonomous work held/)).toBeTruthy());
    fireEvent.click(screen.getByText('Resume autonomy'));
    await waitFor(() => expect(screen.getByText(/RELEASED · autonomy running/)).toBeTruthy());
    const post = fn.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(String(post[0])).toBe('/api/ops/estop/resume');
    expect(post[1].headers['X-Admin-Token']).toBe('admin-secret');
  });
});
