// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SandboxPanel } from '../gap';

/* K3 — the panel half. What is worth testing here is not that a number renders but
   that three states an owner could confuse stay distinguishable: a kernel they have,
   a kernel they do not have, and a reset whose outcome is unknown because the call
   itself failed. The last one is the reason this file exists: "reset" and "we could
   not tell" must never read the same, or the button stops meaning anything on the
   one day it matters. */

function response(payload) {
  return Promise.resolve({ ok: true, status: 200, json: async () => payload });
}

const STATUS = { available: true, docker_image: 'python:3.12-slim', timeout: 30,
  backend: 'docker', tool_rpc: { available: true, tools: [] } };
const SESSION = { mode: 'session', reason: '', kernel: null };
const KERNEL = { agent: 'jarvis', principal: 'owner', session_id: 's1', data_scope: '*',
  token: 'abc123', cells_run: 4, idle_seconds: 12.4, alive: true, backend: 'docker' };

function stub(kernels, extra) {
  global.fetch = vi.fn((url, init) => {
    const target = String(url);
    if (target.includes('/sandbox/kernels/reset')) return (extra || (() => response({})))(init);
    if (target.includes('/sandbox/kernels')) return response(kernels);
    if (target.includes('/sandbox/status')) return response(STATUS);
    return response({});
  });
}

beforeEach(() => { localStorage.clear(); });

describe('SandboxPanel session kernels (K3)', () => {
  it('shows the mode and, with no kernel, says the first cell starts one', async () => {
    stub(SESSION);
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByText('session')).toBeTruthy());
    expect(screen.getByText(/first cell starts one/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /reset kernel/i })).toBeTruthy();
  });

  it('shows the caller own kernel age and cell count', async () => {
    stub({ ...SESSION, kernel: KERNEL });
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByText('4 cells')).toBeTruthy());
    expect(screen.getByText('idle 12s')).toBeTruthy();
    expect(screen.getByText('alive')).toBeTruthy();
  });

  it('names the switch when sessions are off, and offers no reset', async () => {
    stub({ mode: 'one_shot', reason: 'sessions_disabled', kernel: null });
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByText('one_shot')).toBeTruthy());
    expect(screen.getByText('sessions_disabled')).toBeTruthy();
    expect(screen.getByText(/own container/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /reset kernel/i })).toBeNull();
  });

  it('reports a reset that destroyed a kernel', async () => {
    stub({ ...SESSION, kernel: KERNEL }, () => response({ reset: true, mode: 'session' }));
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByText('4 cells')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /reset kernel/i }));
    await waitFor(() => expect(screen.getByText(/kernel destroyed/i)).toBeTruthy());
  });

  it('does not call an empty seat a reset', async () => {
    stub(SESSION, () => response({ reset: false, mode: 'session', reason: '' }));
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByText('session')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /reset kernel/i }));
    await waitFor(() => expect(screen.getByText(/nothing to reset/i)).toBeTruthy());
    expect(screen.queryByText(/kernel destroyed/i)).toBeNull();
  });

  it('keeps a failed call distinct from a successful reset', async () => {
    // The one that matters: a timeout is NOT "reset", and the panel must not imply
    // the kernel is gone when it has no idea whether it is.
    stub(SESSION, () => Promise.resolve({ ok: false, status: 504, json: async () => ({}) }));
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByText('session')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /reset kernel/i }));
    await waitFor(() => expect(screen.getByText(/reset UNCONFIRMED/i)).toBeTruthy());
    expect(screen.getByText(/may still be running/i)).toBeTruthy();
    expect(screen.queryByText(/kernel destroyed/i)).toBeNull();
    expect(screen.queryByText(/nothing to reset/i)).toBeNull();
  });
});
