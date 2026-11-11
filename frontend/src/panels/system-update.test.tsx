// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SystemUpdatePanel, ago } from './system-update';
import { CONSOLE_PANELS } from '../console-routes';

const CHECK = { version: '1.0.0', install: 'git', restart: 'self', branch: 'main', commit: 'abc123def456',
  upstream: 'origin/main', behind: 2, ahead: 0, fetched_seconds_ago: 7200, dirty: true, can_apply: false,
  apply_refused: ['no signature or pinned-ref check exists', 'the working tree has uncommitted changes'],
  manual_steps: 'docs/UPGRADE.md' };

function hub(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: String(url), method, body });
    const answer = routes(String(url), method, body, calls);
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
  });
  return calls;
}

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('Restart / Update panel', () => {
  it('is registered as an admin console panel', () => {
    expect(CONSOLE_PANELS).toContainEqual({ id: 'restart-update', label: 'Restart / Update', group: 'Admin', component: 'SystemUpdatePanel' });
  });

  it('shows the behind count with its age, the dirty tree, and why updating here is not offered', async () => {
    hub(() => ({ status: 200, body: CHECK }));
    render(<SystemUpdatePanel />);
    expect(await screen.findByText(/2 commit\(s\) · as of the last fetch, 2 h ago/)).toBeTruthy();
    expect(screen.getByText('uncommitted changes')).toBeTruthy();
    expect(screen.getByText(/Updating from here is not available: no signature/)).toBeTruthy();
    expect(screen.queryByText(/apply/i)).toBeNull();
  });

  it('checks now and shows the fetch log as it runs', async () => {
    let polls = 0;
    const calls = hub((url, method) => {
      if (url.includes('/api/admin/ops/update/fetch')) return { status: 202, body: { id: 'a1b2c3d4e5f60718', kind: 'fetch', status: 'running', lines: ['$ git fetch --prune origin'] } };
      if (url.includes('/api/admin/ops/actions/')) {
        polls += 1;
        return { status: 200, body: { id: 'a1b2c3d4e5f60718', kind: 'fetch', status: polls > 1 ? 'ok' : 'running',
          lines: polls > 1 ? ['$ git fetch --prune origin', 'behind 2 · ahead 0 · upstream origin/main'] : ['$ git fetch --prune origin'] } };
      }
      return { status: 200, body: CHECK };
    });
    render(<SystemUpdatePanel pollMs={5} />);
    await screen.findByText(/as of the last fetch/);
    fireEvent.click(screen.getByText('check now'));
    expect(await screen.findByText(/behind 2 · ahead 0/)).toBeTruthy();
    expect(calls.find((c) => c.method === 'POST').body).toEqual({});
  });

  it('asks before restarting, then waits for the hub to answer again', async () => {
    let ready = 0;
    const calls = hub((url, method) => {
      if (url.includes('/api/admin/ops/restart')) return { status: 202, body: { id: 'f0e1d2c3b4a59687', kind: 'restart', status: 'running', lines: ['restart requested'], restart: 'requested' } };
      if (url.includes('/readyz')) { ready += 1; return ready > 1 ? { status: 200, body: { ready: true } } : { status: 503, body: { ready: false } }; }
      return { status: 200, body: CHECK };
    });
    render(<SystemUpdatePanel pollMs={5} />);
    await screen.findByText(/as of the last fetch/);
    fireEvent.click(screen.getByText('restart…'));
    expect(calls.some((c) => c.url.includes('/restart'))).toBe(false);
    fireEvent.click(screen.getByText('restart now'));
    expect(await screen.findByText(/Nerva is back/)).toBeTruthy();
    expect(calls.find((c) => c.url.includes('/api/admin/ops/restart')).body).toEqual({ confirm: 'restart' });
  });

  it('says when the hub cannot restart itself', async () => {
    hub((url) => (url.includes('/api/admin/ops/update') ? { status: 200, body: { ...CHECK, restart: 'manual' } } : { status: 404, body: {} }));
    render(<SystemUpdatePanel />);
    expect(await screen.findByText('restart it the way it was started')).toBeTruthy();
    expect((screen.getByText('restart…') as HTMLButtonElement).disabled).toBe(true);
  });

  it('formats ages', () => {
    expect(ago(null)).toBe('never fetched');
    expect(ago(30)).toBe('30s ago');
    expect(ago(600)).toBe('10 min ago');
  });
});
