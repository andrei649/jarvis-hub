// @ts-nocheck
import { beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MediaDirectorPanel } from '../gap';

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

function mockRoutes(routes) {
  const fn = vi.fn().mockImplementation((url, opts = {}) => {
    const path = String(url);
    const entry = Object.entries(routes).find(([key]) => path.includes(key));
    const payload = entry
      ? (typeof entry[1] === 'function' ? entry[1](opts) : entry[1])
      : {};
    return Promise.resolve({ ok: true, status: 200, json: async () => payload });
  });
  global.fetch = fn;
  return fn;
}

describe('MediaDirectorPanel (H29)', () => {
  it('reads and renders the live device registry and session board', async () => {
    const fetchMock = mockRoutes({
      '/api/media/devices': {
        enabled: true,
        devices: [
          { id: 'tv-1', name: 'Living TV', kind: 'tv', room: 'living', supports: ['play', 'show'] },
        ],
      },
      '/api/media/session': {
        enabled: true,
        sessions: [
          {
            device_id: 'tv-1',
            content: { type: 'catalog', value: 'asset-7' },
            mode: 'play',
            privacy: 'household',
            state: 'playing',
          },
        ],
      },
    });

    render(<MediaDirectorPanel />);

    await waitFor(() => expect(screen.getAllByText('Living TV').length).toBeGreaterThan(0));
    expect(screen.getByText(/playing/)).toBeTruthy();
    expect(screen.getByText(/asset-7/)).toBeTruthy();
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/api/media/devices'))).toBe(true);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/api/media/session'))).toBe(true);
  });

  it('shows the default-off state and exposes no actuation control while disabled', async () => {
    mockRoutes({
      '/api/media/devices': { enabled: false, hint: 'set JARVIS_MEDIA_DIRECTOR=1' },
      '/api/media/session': { enabled: false, hint: 'set JARVIS_MEDIA_DIRECTOR=1' },
    });

    render(<MediaDirectorPanel />);

    await waitFor(() => expect(screen.getByText(/off by default/i)).toBeTruthy());
    expect(screen.getByText('SEED')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^present$/i })).toBeNull();
  });

  it('submits only a bounded, typed present request for a registered device', async () => {
    const fetchMock = mockRoutes({
      '/api/media/devices': {
        enabled: true,
        devices: [{ id: 'speaker-1', name: 'Kitchen speaker', kind: 'speaker', room: 'kitchen', supports: ['play', 'announce'] }],
      },
      '/api/media/session': { enabled: true, sessions: [] },
      '/api/media/present': { enabled: true, status: 'queued', reason: 'approval_required' },
    });
    render(<MediaDirectorPanel />);
    await waitFor(() => expect(screen.getAllByText('Kitchen speaker').length).toBeGreaterThan(0));

    const type = screen.getByLabelText('content type');
    const value = screen.getByLabelText('content reference');
    const duration = screen.getByLabelText('duration seconds');
    expect(value.getAttribute('maxlength')).toBe('2048');
    expect(duration.getAttribute('min')).toBe('1');
    expect(duration.getAttribute('max')).toBe('86400');

    fireEvent.change(type, { target: { value: 'query' } });
    expect(value.getAttribute('maxlength')).toBe('256');
    fireEvent.change(value, { target: { value: 'morning briefing' } });
    fireEvent.change(screen.getByLabelText('target device'), { target: { value: 'speaker-1' } });
    const mode = screen.getByLabelText('mode');
    expect(Array.from(mode.options).map((option) => option.value)).toEqual(['play', 'announce']);
    fireEvent.change(mode, { target: { value: 'announce' } });
    fireEvent.change(screen.getByLabelText('privacy'), { target: { value: 'household' } });
    fireEvent.change(screen.getByLabelText('urgency'), { target: { value: 'normal' } });
    fireEvent.change(duration, { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: /^present$/i }));

    await waitFor(() => expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/api/media/present'))).toBe(true));
    const presentCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/api/media/present'));
    expect(presentCall[1].method).toBe('POST');
    expect(JSON.parse(presentCall[1].body)).toEqual({
      content: { type: 'query', value: 'morning briefing' },
      target: 'speaker-1',
      mode: 'announce',
      privacy: 'household',
      urgency: 'normal',
      duration_seconds: 30,
    });
  });

  it('renders a queued kernel decision as waiting for approval, never as success', async () => {
    mockRoutes({
      '/api/media/devices': {
        enabled: true,
        devices: [{ id: 'tv-1', name: 'Living TV', kind: 'tv', supports: ['show'] }],
      },
      '/api/media/session': { enabled: true, sessions: [] },
      '/api/media/present': {
        enabled: true,
        status: 'queued',
        reason: 'approval_required',
        card: { title: 'Present on Living TV' },
      },
    });
    render(<MediaDirectorPanel />);
    await waitFor(() => expect(screen.getByLabelText('content reference')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('content type'), { target: { value: 'catalog' } });
    fireEvent.change(screen.getByLabelText('content reference'), { target: { value: 'asset-7' } });
    fireEvent.change(screen.getByLabelText('target device'), { target: { value: 'tv-1' } });
    fireEvent.change(screen.getByLabelText('mode'), { target: { value: 'show' } });
    fireEvent.click(screen.getByRole('button', { name: /^present$/i }));

    await waitFor(() => expect(screen.getByText(/queued for approval/i)).toBeTruthy());
    expect(screen.getByText(/approval_required/)).toBeTruthy();
    expect(screen.queryByText(/verified success/i)).toBeNull();
  });

  it('renders a kernel refusal as denied without implying device actuation', async () => {
    mockRoutes({
      '/api/media/devices': {
        enabled: true,
        devices: [{ id: 'tv-1', name: 'Living TV', kind: 'tv', supports: ['show'] }],
      },
      '/api/media/session': { enabled: true, sessions: [] },
      '/api/media/present': { enabled: true, status: 'refused', reason: 'kernel_halted' },
    });
    render(<MediaDirectorPanel />);
    await waitFor(() => expect(screen.getByLabelText('content reference')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('content reference'), { target: { value: 'https://media.example/brief' } });
    fireEvent.change(screen.getByLabelText('target device'), { target: { value: 'tv-1' } });
    fireEvent.change(screen.getByLabelText('mode'), { target: { value: 'show' } });
    fireEvent.click(screen.getByRole('button', { name: /^present$/i }));

    await waitFor(() => expect(screen.getByText(/refused · kernel_halted/i)).toBeTruthy());
    expect(screen.queryByText(/verified success/i)).toBeNull();
  });

  it('treats completed with nested output.ok=false as a refusal', async () => {
    mockRoutes({
      '/api/media/devices': {
        enabled: true,
        devices: [{ id: 'tv-1', name: 'Living TV', kind: 'tv', supports: ['play'] }],
      },
      '/api/media/session': { enabled: true, sessions: [] },
      '/api/media/present': {
        enabled: true,
        status: 'completed',
        reason: 'kernel_granted',
        output: { ok: false, reason: 'session_etiquette' },
      },
    });
    render(<MediaDirectorPanel />);
    await waitFor(() => expect(screen.getByLabelText('content reference')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('content reference'), { target: { value: 'https://media.example/brief' } });
    fireEvent.change(screen.getByLabelText('target device'), { target: { value: 'tv-1' } });
    fireEvent.click(screen.getByRole('button', { name: /^present$/i }));

    await waitFor(() => expect(screen.getByText(/refused · session_etiquette/i)).toBeTruthy());
    expect(screen.queryByText(/verified success/i)).toBeNull();
  });

  it('shows success only when the nested driver outcome is explicitly verified', async () => {
    mockRoutes({
      '/api/media/devices': {
        enabled: true,
        devices: [{ id: 'tv-1', name: 'Living TV', kind: 'tv', supports: ['play'] }],
      },
      '/api/media/session': { enabled: true, sessions: [] },
      '/api/media/present': {
        enabled: true,
        status: 'completed',
        reason: 'kernel_granted',
        output: { ok: true, verified: true, device: 'tv-1', verification: 'driver-status-match' },
      },
    });
    render(<MediaDirectorPanel />);
    await waitFor(() => expect(screen.getByLabelText('content reference')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('content reference'), { target: { value: 'https://media.example/brief' } });
    fireEvent.change(screen.getByLabelText('target device'), { target: { value: 'tv-1' } });
    fireEvent.click(screen.getByRole('button', { name: /^present$/i }));

    await waitFor(() => expect(screen.getByText(/verified success · tv-1 · driver-status-match/i)).toBeTruthy());
  });

  it('does not promote an unverified nested success to completed playback', async () => {
    mockRoutes({
      '/api/media/devices': {
        enabled: true,
        devices: [{ id: 'tv-1', name: 'Living TV', kind: 'tv', supports: ['play'] }],
      },
      '/api/media/session': { enabled: true, sessions: [] },
      '/api/media/present': {
        enabled: true,
        status: 'completed',
        output: { ok: true, verified: false, device: 'tv-1', verification: 'unverified-driver-status' },
      },
    });
    render(<MediaDirectorPanel />);
    await waitFor(() => expect(screen.getByLabelText('content reference')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('content reference'), { target: { value: 'https://media.example/brief' } });
    fireEvent.change(screen.getByLabelText('target device'), { target: { value: 'tv-1' } });
    fireEvent.click(screen.getByRole('button', { name: /^present$/i }));

    await waitFor(() => expect(screen.getByText(/unverified · success not claimed/i)).toBeTruthy());
    expect(screen.queryByText(/verified success/i)).toBeNull();
  });

  it('restores an active device through the governed restore endpoint', async () => {
    const fetchMock = mockRoutes({
      '/api/media/devices': {
        enabled: true,
        devices: [{ id: 'tv-1', name: 'Living TV', kind: 'tv', supports: ['play'] }],
      },
      '/api/media/session': {
        enabled: true,
        sessions: [{ device_id: 'tv-1', content: { type: 'catalog', value: 'asset-7' }, mode: 'play', privacy: 'household', state: 'playing' }],
      },
      // MediaDirector.restore() really returns {ok, restored} with no `verified`,
      // so the honest render is the unverified branch — success is never claimed.
      '/api/media/restore/tv-1': {
        enabled: true,
        status: 'completed',
        output: { ok: true, restored: 'previous_session' },
      },
    });
    render(<MediaDirectorPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'restore tv-1' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'restore tv-1' }));

    await waitFor(() => expect(screen.getByText(/unverified · success not claimed/i)).toBeTruthy());
    const restoreCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/api/media/restore/tv-1'));
    expect(restoreCall[1].method).toBe('POST');
  });

  it('uses admin-authenticated controls to register and remove owner-curated devices', async () => {
    localStorage.setItem('hud.admin_token', 'admin-secret');
    const fetchMock = mockRoutes({
      '/api/media/devices': (opts) => {
        if (opts.method === 'POST') return { enabled: true, device: { id: 'speaker-2', name: 'Office speaker' } };
        if (opts.method === 'DELETE') return { enabled: true, removed: 'tv-1' };
        return { enabled: true, devices: [{ id: 'tv-1', name: 'Living TV', kind: 'tv', supports: ['play'] }] };
      },
      '/api/media/session': { enabled: true, sessions: [] },
    });
    render(<MediaDirectorPanel />);
    await waitFor(() => expect(screen.getByText(/ADMIN · DEVICE REGISTRY/)).toBeTruthy());
    const adminZone = screen.getByRole('region', { name: 'media admin controls' });
    expect(within(adminZone).getByRole('button', { name: 'remove tv-1' })).toBeTruthy();

    fireEvent.change(screen.getByLabelText('admin device id'), { target: { value: 'speaker-2' } });
    fireEvent.change(screen.getByLabelText('admin device name'), { target: { value: 'Office speaker' } });
    fireEvent.change(screen.getByLabelText('admin device kind'), { target: { value: 'speaker' } });
    fireEvent.change(screen.getByLabelText('admin device room'), { target: { value: 'office' } });
    fireEvent.change(screen.getByLabelText('admin device supports'), { target: { value: 'play,announce' } });
    fireEvent.click(screen.getByRole('button', { name: 'register device' }));
    await waitFor(() => expect(fetchMock.mock.calls.some((call) => call[1]?.method === 'POST' && String(call[0]).endsWith('/api/media/devices'))).toBe(true));

    const createCall = fetchMock.mock.calls.find((call) => call[1]?.method === 'POST' && String(call[0]).endsWith('/api/media/devices'));
    expect(createCall[1].headers['X-Admin-Token']).toBe('admin-secret');
    expect(JSON.parse(createCall[1].body)).toEqual({
      id: 'speaker-2', name: 'Office speaker', kind: 'speaker', room: 'office', supports: ['play', 'announce'],
    });

    fireEvent.click(within(adminZone).getByRole('button', { name: 'remove tv-1' }));
    await waitFor(() => expect(fetchMock.mock.calls.some((call) => call[1]?.method === 'DELETE')).toBe(true));
    const deleteCall = fetchMock.mock.calls.find((call) => call[1]?.method === 'DELETE');
    expect(String(deleteCall[0])).toContain('/api/media/devices/tv-1');
    expect(deleteCall[1].headers['X-Admin-Token']).toBe('admin-secret');
  });
});
