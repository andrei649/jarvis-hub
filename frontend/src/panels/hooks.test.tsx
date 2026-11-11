// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { HooksPanel, splitArgv } from './hooks';
import { CONSOLE_PANELS } from '../console-routes';

const EVENTS = [
  { event: 'tool.before', blocking: true, hermes: 'pre_tool_call', matcher: true, doc: 'Before a tool call runs.' },
  { event: 'session.started', blocking: false, hermes: 'on_session_start', matcher: false, doc: 'A session started.' },
];
const HOOK = { id: 'hk-0123456789', name: 'guard', event: 'tool.before', command: '/usr/bin/python3 /opt/guard.py',
  matcher: 'terminal_*', guard: true, timeout_s: 10, status: 'active', task_id: 4, binding_current: true,
  last_run: { outcome: 'blocked', reason: null }, pending_card: false };

function hub(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    calls.push({ url: String(url), method, body });
    const answer = routes(String(url), method, body);
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
  });
  return calls;
}

const listing = (extra = {}) => ({ hooks: [HOOK], events: EVENTS, runs: [],
  status: { ready: true, blockers: [], max_timeout_s: 30 }, ...extra });

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('Hooks panel', () => {
  it('is registered as an admin console panel', () => {
    expect(CONSOLE_PANELS).toContainEqual({ id: 'hooks', label: 'Hooks', group: 'Admin', component: 'HooksPanel' });
  });

  it('splits a command line into argv without a shell', () => {
    expect(splitArgv('/usr/bin/python3 "/opt/my hooks/g.py" --x')).toEqual(['/usr/bin/python3', '/opt/my hooks/g.py', '--x']);
  });

  it('lists hooks and asks for a card when adding one', async () => {
    const calls = hub((url, method) => {
      if (url.endsWith('/api/hooks') && method === 'GET') return { status: 200, body: listing() };
      if (url.endsWith('/api/hooks') && method === 'POST') return { status: 202, body: { ok: true, task_id: 9, hook: { id: 'hk-1' } } };
      return { status: 404, body: {} };
    });
    render(<HooksPanel />);
    await screen.findByText('/usr/bin/python3 /opt/guard.py');
    expect(screen.getByText('guard · fails closed')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('command'), { target: { value: '/usr/bin/python3 /opt/new.py' } });
    fireEvent.click(screen.getByText('guard (block if it fails)').querySelector('input') || screen.getByRole('checkbox'));
    fireEvent.click(screen.getByText('ask to add'));
    await screen.findByText(/approval card 9 queued/);
    const post = calls.find((c) => c.method === 'POST');
    expect(post.body).toMatchObject({ event: 'tool.before', argv: ['/usr/bin/python3', '/opt/new.py'], guard: true });
  });

  it('switches a hook off, tests and removes it', async () => {
    const calls = hub((url, method) => {
      if (url.endsWith('/api/hooks') && method === 'GET') return { status: 200, body: listing() };
      if (url.includes('/disable')) return { status: 200, body: { ok: true } };
      if (url.includes('/test')) return { status: 200, body: { ok: true, run: { outcome: 'blocked', blocked: true } } };
      if (method === 'DELETE') return { status: 200, body: { ok: true, removed: HOOK.id } };
      return { status: 404, body: {} };
    });
    render(<HooksPanel />);
    await screen.findByText('switch off');
    fireEvent.click(screen.getByText('test'));
    await screen.findByText(/test run: blocked · would block/);
    fireEvent.click(screen.getByText('switch off'));
    await waitFor(() => expect(calls.some((c) => c.url.includes(`/api/hooks/${HOOK.id}/disable`))).toBe(true));
    fireEvent.click(screen.getByLabelText(`remove ${HOOK.id}`));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true));
  });

  it('offers a one-step re-approval when the files changed', async () => {
    const calls = hub((url, method) => {
      if (url.endsWith('/api/hooks') && method === 'GET') {
        return { status: 200, body: listing({ hooks: [{ ...HOOK, binding_current: false }] }) };
      }
      if (url.includes('/enable')) return { status: 202, body: { ok: true, task_id: 12 } };
      return { status: 404, body: {} };
    });
    render(<HooksPanel />);
    fireEvent.click(await screen.findByText('re-approve…'));
    await screen.findByText(/approval card 12 queued/);
    expect(calls.some((c) => c.url.includes(`/api/hooks/${HOOK.id}/enable`))).toBe(true);
  });

  it('says why hooks cannot run here', async () => {
    hub(() => ({ status: 200, body: listing({ status: { ready: false, blockers: ['admin_credential_required'] } }) }));
    render(<HooksPanel />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('admin token');
  });
});
