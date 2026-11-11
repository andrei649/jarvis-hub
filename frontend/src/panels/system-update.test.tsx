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

  it('with trust pinned, plans the update and queues an approval card (H624)', async () => {
    const READY = { ...CHECK, dirty: false, can_apply: true, apply_refused: [],
      trust: { configured: true, mode: 'gpg', fingerprints: ['ABCDEF'] }, in_progress: null, last_receipt: null };
    const PLAN = { can_apply: true, refused: [], from: 'a'.repeat(40), to: 'b'.repeat(40), from_version: '1.0.0', to_version: '1.1.0',
      commit_count: 1, file_count: 2, migrations: [], dependencies: { changed: false, command: null },
      commits: [{ sha: 'b'.repeat(40), subject: 'release 1.1.0' }] };
    const calls = hub((url, method) => {
      if (url.includes('/api/admin/ops/update/plan')) return { status: 200, body: PLAN };
      if (url.includes('/api/admin/ops/update/apply')) return { status: 202, body: { task_id: 7, status: 'pending_approval' } };
      return { status: 200, body: READY };
    });
    render(<SystemUpdatePanel />);
    expect(await screen.findByText(/gpg · ABCDEF/)).toBeTruthy();
    fireEvent.click(screen.getByText('plan'));
    expect(await screen.findByText(/release 1.1.0/)).toBeTruthy();
    fireEvent.click(screen.getByText('request update'));
    expect(await screen.findByText(/approval card #7 queued/)).toBeTruthy();
    expect(calls.find((c) => c.url.includes('/update/apply')).body).toEqual({});
  });

  it('shows the target signature and plans a typed tag even when the upstream is not ahead (H624 review)', async () => {
    const PINNED = { ...CHECK, dirty: false, behind: 0, can_apply: false, apply_refused: ['nothing to apply'],
      trust: { configured: true, mode: 'ssh', fingerprints: ['SHA256:abc'] },
      target: { ref: '@{u}', commit: 'c'.repeat(40), signature: 'unverified', reason: 'signature_not_trusted' },
      in_progress: null, last_receipt: null };
    const PLAN = { can_apply: true, refused: [], from: 'a'.repeat(40), to: 'd'.repeat(40), from_version: '1.0.0', to_version: '1.2.0',
      commit_count: 2, file_count: 3, migrations: ['agents/core/security/audit.py'], dependencies: { changed: false, command: null },
      commits: [], verdict: { trusted: true, how: 'signed_tag', signer: 'SHA256:abc' } };
    const calls = hub((url) => {
      if (url.includes('/api/admin/ops/update/plan')) return { status: 200, body: PLAN };
      if (url.includes('/api/admin/ops/update/apply')) return { status: 202, body: { task_id: 8 } };
      return { status: 200, body: PINNED };
    });
    render(<SystemUpdatePanel />);
    expect(await screen.findByText(/unverified: signature_not_trusted/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('update target'), { target: { value: 'v1.2.0' } });
    fireEvent.click(screen.getByText('plan'));
    expect(await screen.findByText(/possible data migration in: agents\/core\/security\/audit.py/)).toBeTruthy();
    expect(screen.getByText(/verified \(signed_tag · SHA256:abc\)/)).toBeTruthy();
    expect(calls.find((c) => c.url.includes('/update/plan')).url).toContain('ref=v1.2.0');
    fireEvent.click(screen.getByText('request update'));
    expect(await screen.findByText(/approval card #8 queued/)).toBeTruthy();
    expect(calls.find((c) => c.url.includes('/update/apply')).body).toEqual({ ref: 'v1.2.0' });
  });

  it('offers a rollback card after a verified update and shows one in flight', async () => {
    const DONE = { ...CHECK, dirty: false, behind: 0, trust: { configured: true, mode: 'pinned', commit: 'c'.repeat(40) },
      in_progress: null, last_receipt: { id: 'r1', kind: 'update', from: 'a'.repeat(40), to: 'b'.repeat(40), result: 'verified' } };
    const calls = hub((url) => (url.includes('/update/rollback') ? { status: 202, body: { task_id: 9 } } : { status: 200, body: DONE }));
    render(<SystemUpdatePanel />);
    expect(await screen.findByText(/update aaaaaaaaaaaa → bbbbbbbbbbbb · verified/)).toBeTruthy();
    fireEvent.click(screen.getByText('request rollback'));
    expect(await screen.findByText(/approval card #9 queued: roll back to aaaaaaaaaaaa/)).toBeTruthy();
    expect(calls.some((c) => c.url.includes('/update/rollback') && c.method === 'POST')).toBe(true);
  });

  it('formats ages', () => {
    expect(ago(null)).toBe('never fetched');
    expect(ago(30)).toBe('30s ago');
    expect(ago(600)).toBe('10 min ago');
  });
});
