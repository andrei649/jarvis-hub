// @ts-nocheck
import { beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { HousePanel } from '../gap';

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

function response(payload) {
  return Promise.resolve({ ok: true, status: 200, json: async () => payload });
}

function state(overrides = {}) {
  return {
    enabled: true,
    status: 'live',
    reason: '',
    observed_at: 100,
    freshness_seconds: 2,
    rooms: [{ room_id: 'kitchen', name: 'Kitchen' }],
    devices: [
      { entity_id: 'light.kitchen', domain: 'light', state: 'on', room_id: 'kitchen' },
      { entity_id: 'climate.living', domain: 'climate', state: 'heat', room_id: 'living' },
      { entity_id: 'lock.front', domain: 'lock', state: 'locked', room_id: 'entry' },
    ],
    presence: [
      { occupant_id: `occ-${'a'.repeat(32)}`, status: 'present', room_id: 'kitchen', privacy: 'household', confidence: 0.9, fresh: true },
      { occupant_id: `occ-${'b'.repeat(32)}`, status: 'present', privacy: 'private', confidence: 0.8, fresh: true },
    ],
    privacy_status: 'live',
    ...overrides,
  };
}

describe('HousePanel (H30.5)', () => {
  it('renders the bounded house graph and pseudonymous presence', async () => {
    global.fetch = vi.fn(() => response(state()));

    render(<HousePanel />);

    await waitFor(() => expect(screen.getByText('Kitchen')).toBeTruthy());
    expect(screen.getAllByText(/light.kitchen/).length).toBeGreaterThan(0);
    expect(screen.getByText(/locked/)).toBeTruthy();
    expect(screen.getByText(/aaaaaaaa/)).toBeTruthy();
    expect(screen.getByText(/private/)).toBeTruthy();
    expect(screen.queryByText(/Alice|Bob|bedroom/i)).toBeNull();
  });

  it('shows an honest default-off state and no control forms', async () => {
    global.fetch = vi.fn(() => response(state({ enabled: false, status: 'disabled', reason: 'house_brain_disabled', rooms: [], devices: [], presence: [] })));

    render(<HousePanel />);

    await waitFor(() => expect(screen.getByText(/house brain is off/i)).toBeTruthy());
    expect(screen.getByText('SEED')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /propose light control/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /propose security control/i })).toBeNull();
  });

  it('sends a narrow light proposal and renders queued without claiming success', async () => {
    const fetchMock = vi.fn((url, opts = {}) => {
      if (String(url).includes('/api/house/control/light')) {
        return response({ enabled: true, status: 'queued', reason: 'approval_required', task_id: 11, strong_confirmation_required: false });
      }
      return response(state());
    });
    global.fetch = fetchMock;
    render(<HousePanel />);
    await waitFor(() => expect(screen.getByLabelText('light target')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('light state'), { target: { value: 'on' } });
    fireEvent.change(screen.getByLabelText('light brightness'), { target: { value: '45' } });
    fireEvent.click(screen.getByRole('button', { name: /propose light control/i }));

    await waitFor(() => expect(screen.getByText(/queued for approval · task 11/i)).toBeTruthy());
    expect(screen.queryByText(/verified success/i)).toBeNull();
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/house/control/light'));
    expect(JSON.parse(call[1].body)).toEqual({ entity_id: 'light.kitchen', state: 'on', brightness_pct: 45 });
  });

  it.each([
    [{ status: 'denied', reason: 'kernel_halted' }, /denied · kernel_halted/i],
    [{ status: 'unverified', reason: 'governed_queue_unavailable' }, /unverified · no action claimed/i],
    [{ status: 'verified', reason: 'state_verified' }, /verified success · state_verified/i],
  ])('renders the %s outcome honestly', async (outcome, label) => {
    global.fetch = vi.fn((url) => String(url).includes('/api/house/control/climate')
      ? response({ enabled: true, strong_confirmation_required: false, ...outcome })
      : response(state()));
    render(<HousePanel />);
    await waitFor(() => expect(screen.getByLabelText('climate target')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /propose climate control/i }));
    await waitFor(() => expect(screen.getByText(label)).toBeTruthy());
  });

  it('keeps security as a proposal that requires the separate owner ceremony', async () => {
    global.fetch = vi.fn((url) => String(url).includes('/api/house/control/security')
      ? response({ enabled: true, status: 'queued', reason: 'strong_confirmation_required', task_id: 77, strong_confirmation_required: true })
      : response(state()));
    render(<HousePanel />);
    await waitFor(() => expect(screen.getByLabelText('security target')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('security action'), { target: { value: 'unlock' } });
    fireEvent.click(screen.getByRole('button', { name: /propose security control/i }));
    await waitFor(() => expect(screen.getByText(/strong confirmation required · task 77/i)).toBeTruthy());
    expect(screen.queryByRole('button', { name: /confirm exact security action/i })).toBeNull();
  });

  it('uses an admin-authenticated, deliberate two-step confirmation bound to the challenge', async () => {
    localStorage.setItem('hud.admin_token', 'admin-secret');
    const fetchMock = vi.fn((url, opts = {}) => {
      if (String(url).includes('/challenge')) {
        return response({ enabled: true, status: 'challenge_minted', task_id: 77, token: 'server-minted-token-123456', target: 'lock.front', intended_state: 'unlocked', expires_at: 999 });
      }
      if (String(url).includes('/confirm')) {
        return response({ enabled: true, status: 'confirmed', confirmation_id: 9, receipt: 'receipt-token' });
      }
      return response(state());
    });
    global.fetch = fetchMock;
    render(<HousePanel />);
    await waitFor(() => expect(screen.getByLabelText('security task id')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('security task id'), { target: { value: '77' } });
    fireEvent.click(screen.getByRole('button', { name: /mint owner challenge/i }));

    await waitFor(() => expect(screen.getByText(/lock.front → unlocked/)).toBeTruthy());
    const confirm = screen.getByRole('button', { name: /confirm exact security action/i });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('type intended state'), { target: { value: 'unlocked' } });
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(confirm);

    await waitFor(() => expect(screen.getByText(/owner confirmation recorded/i)).toBeTruthy());
    const challengeCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/challenge'));
    const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/confirm'));
    expect(challengeCall[1].headers['X-Admin-Token']).toBe('admin-secret');
    expect(challengeCall[1].body).toBe('{}');
    expect(confirmCall[1].headers['X-Admin-Token']).toBe('admin-secret');
    expect(JSON.parse(confirmCall[1].body)).toEqual({ challenge_token: 'server-minted-token-123456' });
  });
});
