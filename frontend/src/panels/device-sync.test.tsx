// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DeviceSyncPanel } from './device-sync';

const baseSync = {
  enabled: true,
  available: true,
  backend: 'aes-256-gcm',
  device_id: 'dev-mbp',
  device_label: 'Studio MacBook',
  skill_policies: { 'daily-brief': true },
  peers: [{ peer_id: 'home-hub', url: 'https://hub.local:8443', label: 'home-hub' }],
  transports: ['local', 'http-peers(1)'],
};

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('DeviceSyncPanel (H040)', () => {
  it('drives E2E sync status, bidirectional sync, device label, skill toggle, and peer hubs', async () => {
    const calls = [];
    global.fetch = vi.fn(async (url, init = {}) => {
      const path = String(url);
      calls.push([path, init]);
      if (path.endsWith('/api/sync') && (!init.method || init.method === 'GET')) {
        return { ok: true, status: 200, json: async () => baseSync };
      }
      return { ok: true, status: 200, json: async () => ({ ok: true, artefact_count: 2, records_decrypted: 2 }) };
    });

    render(<DeviceSyncPanel />);
    await screen.findByText(/Studio MacBook/);

    fireEvent.click(screen.getByText('sync now'));
    await waitFor(() => expect(calls.some(([u]) => u.endsWith('/api/sync/now'))).toBe(true));

    fireEvent.click(screen.getByText('push'));
    await waitFor(() => expect(calls.some(([u]) => u.endsWith('/api/sync/push'))).toBe(true));

    fireEvent.click(screen.getByText('pull'));
    await waitFor(() => expect(calls.some(([u]) => u.endsWith('/api/sync/pull'))).toBe(true));

    fireEvent.change(screen.getByLabelText('Skill slug'), { target: { value: 'ops-pack' } });
    fireEvent.click(screen.getByText('enable skill'));
    await waitFor(() => expect(calls.some(([u]) => u.includes('/api/sync/skills/ops-pack'))).toBe(true));

    fireEvent.change(screen.getByLabelText('Peer ID'), { target: { value: 'lab-node' } });
    fireEvent.change(screen.getByLabelText('Peer URL'), { target: { value: 'https://lab.example:8443' } });
    fireEvent.click(screen.getByText('+ peer'));
    await waitFor(() => expect(calls.some(([u]) => u.endsWith('/api/sync/peers'))).toBe(true));
  });
});
