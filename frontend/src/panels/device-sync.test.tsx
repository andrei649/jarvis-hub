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
  it.each(['pull', 'sync now'])('keeps disabled %s responses distinct from staged work', async (operation) => {
    global.fetch = vi.fn(async (url) => ({
      ok: true, status: 200,
      json: async () => String(url).endsWith('/api/sync') ? baseSync : {
        ok: false, enabled: false, reason: 'sync_disabled', inbound_mode: 'stage_only',
        config_pending_import: [], skills_pending_install: [],
      },
    }));
    render(<DeviceSyncPanel />);
    await screen.findByText(/Studio MacBook/);
    fireEvent.click(screen.getByText(operation));
    expect(await screen.findByText(/Sync disabled \(sync_disabled\)/)).toBeTruthy();
    expect(screen.queryByText(/staged for review/)).toBeNull();
  });

  it.each(['pull', 'sync now'])('reports staged candidates without claiming application for %s', async (operation) => {
    const pull = {
      ok: true, inbound_mode: 'stage_only', records_decrypted: 3,
      config_applied: 0, skills_applied: [],
      config_pending_import: [{ fingerprint: 'config-a' }, { fingerprint: 'config-b' }],
      skills_pending_install: [{ slug: 'daily-brief', fingerprint: 'skill-a' }],
      staging_errors: [],
    };
    global.fetch = vi.fn(async (url) => ({
      ok: true, status: 200,
      json: async () => String(url).endsWith('/api/sync')
        ? { ...baseSync, inbound_mode: 'stage_only' }
        : String(url).endsWith('/now') ? { ok: true, pull, push: { ok: true } } : pull,
    }));
    render(<DeviceSyncPanel />);
    await screen.findByText(/Studio MacBook/);
    fireEvent.click(screen.getByText(operation));
    expect(await screen.findByText(/2 configuration candidates and 1 skill candidate staged for review/)).toBeTruthy();
    expect(screen.getByText(/Import and installation are pending/)).toBeTruthy();
    expect(screen.queryByText(/bidirectional sync completed/)).toBeNull();
  });

  it('shows staging failures alongside preserved candidates', async () => {
    global.fetch = vi.fn(async (url) => ({
      ok: true, status: 200,
      json: async () => String(url).endsWith('/api/sync') ? baseSync : {
        ok: true, inbound_mode: 'stage_only', records_decrypted: 2,
        config_pending_import: [{ fingerprint: 'saved' }], skills_pending_install: [],
        staging_errors: [{ reason: 'inbox_capacity', artifact_type: 'skill' }],
        config_errors: ['invalid configuration'], skills_quarantined: [{ slug: 'unsafe' }],
      },
    }));
    render(<DeviceSyncPanel />);
    await screen.findByText(/Studio MacBook/);
    fireEvent.click(screen.getByText('pull'));
    expect(await screen.findByText(/1 candidate could not be staged/)).toBeTruthy();
    expect(screen.getByText(/1 configuration candidate and 0 skill candidates staged for review/)).toBeTruthy();
    expect(screen.getByText(/1 configuration validation issue/)).toBeTruthy();
    expect(screen.getByText(/1 skill quarantined/)).toBeTruthy();
  });

  it('does not infer skill installation or preservation from an older server receipt', async () => {
    global.fetch = vi.fn(async (url) => ({
      ok: true, status: 200,
      json: async () => String(url).endsWith('/api/sync') ? baseSync : {
        ok: true, records_decrypted: 2, config_applied: 1, skills_applied: ['daily-brief'],
      },
    }));
    render(<DeviceSyncPanel />);
    await screen.findByText(/Studio MacBook/);
    fireEvent.click(screen.getByText('pull'));
    expect(await screen.findByText(/Server reported 1 configuration change and 1 skill transfer/)).toBeTruthy();
    expect(screen.getByText(/installation status is unverified/)).toBeTruthy();
    expect(screen.queryByText(/automatic import is paused/)).toBeNull();
  });

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
