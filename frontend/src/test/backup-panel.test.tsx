// @ts-nocheck
/* HUD-v3 C9 — the Console Backup & Export panel reads the admin backup registry
   (/api/admin/backup) and drives back-up / restore-drill / export-me. fetch is
   mocked, like kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { BackupPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('BackupPanel — data-sovereignty controls are live', () => {
  it('GETs /api/admin/backup and lists a snapshot with its size + encrypted tag', async () => {
    const fn = mockFetch({ backups: [
      { name: 'jarvis-2026-06-28.tar.gz.enc', bytes: 2_400_000, encrypted: true, modified_at: 1 },
    ] });
    render(<BackupPanel />);
    await waitFor(() => expect(screen.getByText('jarvis-2026-06-28.tar.gz.enc')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/admin/backup'))).toBe(true);
    expect(screen.getByText('enc')).toBeTruthy();
    expect(screen.getByText('2.4MB')).toBeTruthy();
  });

  it('POSTs a backup when "back up now" is clicked', async () => {
    const fn = mockFetch({ backups: [], ok: true, bytes: 1024 });
    render(<BackupPanel />);
    await waitFor(() => expect(screen.getByText('back up now')).toBeTruthy());
    fireEvent.click(screen.getByText('back up now'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/admin/backup') && c[1]?.method === 'POST')
    ).toBe(true));
  });

  it('runs the restore-drill (POST verify) and surfaces the OK result', async () => {
    mockFetch({ backups: [], ok: true, file_count: 7 });
    render(<BackupPanel />);
    await waitFor(() => expect(screen.getByText('verify')).toBeTruthy());
    fireEvent.click(screen.getByText('verify'));
    await waitFor(() => expect(screen.getByText(/restore-drill OK/)).toBeTruthy());
  });

  it('exports the user data (POST export) and reports the size', async () => {
    mockFetch({ backups: [], bytes: 512_000 });
    render(<BackupPanel />);
    await waitFor(() => expect(screen.getByText('export my data')).toBeTruthy());
    fireEvent.click(screen.getByText('export my data'));
    await waitFor(() => expect(screen.getByText(/export written/)).toBeTruthy());
  });
});
