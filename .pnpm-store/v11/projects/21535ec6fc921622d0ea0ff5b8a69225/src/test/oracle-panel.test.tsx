// @ts-nocheck
/* HUD-v3 (Oracle bridge) — the Console Oracle Sync panel reads the truth-sync status
   (/api/oracle/status), triggers a sync (POST /api/oracle/sync) and clears resolved
   conflicts (POST /api/oracle/conflicts/resolve). fetch is mocked, like
   kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { OraclePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('OraclePanel — the truth-sync reconciler is live', () => {
  it('GETs /api/oracle/status and lists a conflict + the watcher status', async () => {
    const fn = mockFetch({
      watcher_running: true, last_checked: 'abc1234',
      conflicts: [{ file_path: 'JARVIS.md', local_hash: 'a', remote_hash: 'b', resolved: false }],
      total_conflicts: 1,
    });
    render(<OraclePanel />);
    await waitFor(() => expect(screen.getByText('JARVIS.md')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/oracle/status'))).toBe(true);
    expect(screen.getByText('conflict')).toBeTruthy();
  });

  it('triggers a sync (POST /api/oracle/sync) when "sync now" is clicked', async () => {
    const fn = mockFetch({ watcher_running: true, last_checked: 'x', conflicts: [] });
    render(<OraclePanel />);
    await waitFor(() => expect(screen.getByText('sync now')).toBeTruthy());
    fireEvent.click(screen.getByText('sync now'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/oracle/sync') && c[1]?.method === 'POST')
    ).toBe(true));
  });

  it('shows the in-sync state when there are no conflicts', async () => {
    mockFetch({ watcher_running: false, last_checked: '', conflicts: [] });
    render(<OraclePanel />);
    await waitFor(() => expect(screen.getByText(/in sync/)).toBeTruthy());
  });
});
