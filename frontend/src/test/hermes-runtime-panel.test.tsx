import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiFetchOnce } from '../api/client';
import { HermesRuntimePanel } from '../hermes-runtime-panel';

vi.mock('../api/client', () => ({
  apiFetchOnce: vi.fn(),
  getAdminToken: vi.fn(() => 'owner-token'),
}));

const fetchOnce = vi.mocked(apiFetchOnce);
const catalog = {
  source_sha: 'pinned-sha',
  methods: [
    { name: 'session.list', summary: 'List sessions' },
    { name: 'session.create', summary: 'Create session', risk_tier: 'controlled' },
    { name: 'tool.inspect', summary: 'Inspect a tool' },
  ],
};
const pendingTask = {
  task_id: 17, status: 'blocked', disposition: 'queued', operation: 'fs.write',
  target: '/tmp/hermes-sentinel', arguments: { content: 'hello', overwrite: false },
  risk_tier: 'controlled', created_at: '2026-10-06T12:00:00Z',
  expires_at: '2026-10-06T12:05:00Z',
};

function response(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body } as Response;
}

function setup(status: { enabled: boolean; ready: boolean; reason?: string }) {
  fetchOnce.mockImplementation(async (path, opts) => {
    if (path === '/api/hermes/status') return response(status);
    if (path === '/api/hermes/catalog') return response(catalog);
    if (path === '/api/hermes/approvals') return response({ tasks: [], total: 0 });
    if (path === '/api/hermes/rpc' && opts?.body && typeof opts.body === 'object') {
      const body = opts.body as { method: string; params: unknown };
      if (body.method === 'session.list') {
        return response({ result: { sessions: [{ id: 'session-1', status: 'active' }] } });
      }
      return response({ result: { accepted: true, params: body.params } });
    }
    return response(status);
  });
}

beforeEach(() => {
  fetchOnce.mockReset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('HermesRuntimePanel', () => {
  it('shows disabled setup state and refuses controls until configured', async () => {
    setup({ enabled: false, ready: false, reason: 'not configured' });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(screen.getByText(/Disabled · not configured/)).toBeTruthy());
    expect(screen.getByText(/Set up the pinned Hermes runtime/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Start' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Send RPC' }) as HTMLButtonElement).disabled).toBe(true);
    expect(fetchOnce.mock.calls.every(([, opts]) => opts?.admin === true)).toBe(true);
    expect(fetchOnce.mock.calls.every(([, opts]) => opts?.method === 'GET')).toBe(true);
  });

  it('uses one RPC mutation, validates arguments, and lists sessions', async () => {
    setup({ enabled: true, ready: true });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(screen.getByText('Ready')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Refresh sessions' }));
    await waitFor(() => expect(screen.getByText(/session-1 · active/)).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Method'), { target: { value: 'tool.inspect' } });
    fireEvent.change(screen.getByLabelText('JSON arguments'), { target: { value: '[1]' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send RPC' }));
    expect(screen.getByRole('alert').textContent).toMatch(/JSON object/);
    const before = fetchOnce.mock.calls.filter(([path]) => path === '/api/hermes/rpc').length;

    fireEvent.change(screen.getByLabelText('JSON arguments'), { target: { value: '{"name":"read"}' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send RPC' }));
    await waitFor(() => expect(screen.getByLabelText('Hermes RPC result').textContent).toMatch(/accepted/));
    const rpcCalls = fetchOnce.mock.calls.filter(([path]) => path === '/api/hermes/rpc');
    expect(rpcCalls).toHaveLength(before + 1);
    expect(rpcCalls[rpcCalls.length - 1]?.[1]?.body).toEqual({ method: 'tool.inspect', params: { name: 'read' } });
  });

  it('forwards an explicit server-request reply through the same-origin WebSocket', async () => {
    const sockets: FakeSocket[] = [];
    class FakeSocket {
      static OPEN = 1;
      readyState = 1;
      url: string;
      protocols: string[];
      sent: string[] = [];
      onopen: (() => void) | null = null;
      onmessage: ((message: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: (() => void) | null = null;
      constructor(url: string, protocols: string[]) {
        this.url = url;
        this.protocols = protocols;
        sockets.push(this);
      }
      send(value: string) { this.sent.push(value); }
      close() {}
    }
    vi.stubGlobal('WebSocket', FakeSocket);
    setup({ enabled: true, ready: true });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(sockets[0].url).toMatch(/^ws:\/\/localhost:\d+\/api\/hermes\/ws$/);
    expect(sockets[0].url).not.toContain('owner-token');
    expect(sockets[0].protocols).toEqual(['hermes-runtime-v1', 'nerva-admin.owner-token']);
    sockets[0].onmessage?.({ data: JSON.stringify({
      jsonrpc: '2.0', id: 'upstream-1', generation: 'abc123',
      method: 'approval.request', params: { tool: 'read' },
    }) });
    await waitFor(() => expect(screen.getByText(/Server request pending: approval.request/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('JSON response'), { target: { value: '{"approved":false}' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reply to server request' }));
    expect(JSON.parse(sockets[0].sent[0])).toEqual({
      jsonrpc: '2.0', id: 'upstream-1', generation: 'abc123', result: { approved: false },
    });
  });

  it('shows a server refusal after one start attempt', async () => {
    setup({ enabled: true, ready: false });
    fetchOnce.mockImplementation(async (path) => {
      if (path === '/api/hermes/catalog') return response(catalog);
      if (path === '/api/hermes/status') return response({ enabled: true, ready: false });
      return response({ detail: { error: 'runtime_unavailable' } }, 503);
    });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(screen.getByText('Stopped')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Start' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/runtime_unavailable/));
    expect(fetchOnce.mock.calls.filter(([path]) => path === '/api/hermes/start')).toHaveLength(1);
  });

  it('shows exact queued target and arguments, then posts one decision and refreshes', async () => {
    setup({ enabled: true, ready: true });
    let task = pendingTask;
    const previous = fetchOnce.getMockImplementation()!;
    fetchOnce.mockImplementation(async (path, opts) => {
      if (path === '/api/hermes/approvals') return response({ tasks: [task], total: 1 });
      if (path === '/api/hermes/approvals/17/decision') {
        task = { ...task, status: 'approved', disposition: 'approved' };
        return response(task);
      }
      return previous(path, opts);
    });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(screen.getByText('/tmp/hermes-sentinel')).toBeTruthy());
    expect(screen.getByLabelText('Arguments for task 17').textContent).toContain('"overwrite": false');
    fireEvent.click(screen.getByRole('button', { name: 'Approve task 17' }));
    await waitFor(() => expect(screen.getByText(/Task 17: approved/)).toBeTruthy());
    expect(fetchOnce.mock.calls.filter(([path]) => path === '/api/hermes/approvals/17/decision')).toHaveLength(1);
    expect(fetchOnce.mock.calls.find(([path]) => path === '/api/hermes/approvals/17/decision')?.[1])
      .toMatchObject({ method: 'POST', admin: true, body: { approved: true } });
    expect((screen.getByRole('button', { name: 'Approve task 17' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('denies a blocked task once and preserves a refusal for inspection', async () => {
    setup({ enabled: true, ready: true });
    const previous = fetchOnce.getMockImplementation()!;
    fetchOnce.mockImplementation(async (path, opts) => {
      if (path === '/api/hermes/approvals') return response({ tasks: [pendingTask], total: 1 });
      if (path === '/api/hermes/approvals/17/decision') return response({ detail: { error: 'approval_expired' } }, 409);
      return previous(path, opts);
    });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Deny task 17' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Deny task 17' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('approval_expired'));
    expect(fetchOnce.mock.calls.filter(([path]) => path === '/api/hermes/approvals/17/decision')).toHaveLength(1);
    expect(fetchOnce.mock.calls.find(([path]) => path === '/api/hermes/approvals/17/decision')?.[1])
      .toMatchObject({ method: 'POST', admin: true, body: { approved: false } });
  });

  it('shows a consumed unknown outcome without offering another decision', async () => {
    setup({ enabled: true, ready: false });
    const previous = fetchOnce.getMockImplementation()!;
    fetchOnce.mockImplementation(async (path, opts) => {
      if (path === '/api/hermes/approvals') return response({ tasks: [{
        ...pendingTask, status: 'done', disposition: 'consumed_outcome_unknown',
        result: { disposition: 'consumed_outcome_unknown' },
        error: 'upstream reply lost',
      }], total: 1 });
      return previous(path, opts);
    });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(screen.getByLabelText('Outcome for task 17').textContent)
      .toContain('consumed_outcome_unknown'));
    expect(screen.getByLabelText('Outcome for task 17').textContent).toContain('upstream reply lost');
    expect((screen.getByRole('button', { name: 'Approve task 17' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('does not offer a decision for a revoked blocked card', async () => {
    setup({ enabled: true, ready: true });
    const previous = fetchOnce.getMockImplementation()!;
    fetchOnce.mockImplementation(async (path, opts) => {
      if (path === '/api/hermes/approvals') return response({ tasks: [{
        ...pendingTask, disposition: 'generation_revoked', error: 'Runtime generation revoked',
      }], total: 1 });
      return previous(path, opts);
    });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(screen.getByLabelText('Outcome for task 17').textContent)
      .toContain('Runtime generation revoked'));
    expect((screen.getByRole('button', { name: 'Approve task 17' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Deny task 17' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the queued task ID after an RPC refusal and refreshes approvals', async () => {
    setup({ enabled: true, ready: true });
    const previous = fetchOnce.getMockImplementation()!;
    fetchOnce.mockImplementation(async (path, opts) => {
      if (path === '/api/hermes/approvals') return response({ tasks: [pendingTask], total: 1 });
      if (path === '/api/hermes/rpc') return response({
        detail: { error: 'approval_required', task_id: 17, disposition: 'queued' },
      }, 409);
      return previous(path, opts);
    });
    render(<HermesRuntimePanel />);
    await waitFor(() => expect(screen.getByText('/tmp/hermes-sentinel')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Send RPC' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('task 17'));
    expect(fetchOnce.mock.calls.filter(([path]) => path === '/api/hermes/rpc')).toHaveLength(1);
    expect(fetchOnce.mock.calls.filter(([path]) => path === '/api/hermes/approvals').length).toBeGreaterThan(1);
  });
});
