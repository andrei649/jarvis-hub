// @ts-nocheck
/* Smoke tests for the TASK-2 depth panels: each new Console panel must hit its REAL
   endpoint (method + path + body verified against agents/web.py). fetch is mocked —
   these assert the wiring through the component, like wired-controls.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PairingPanel, SandboxPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve({ ok: true, status: 200, json: async () => (hit ? hit[1] : {}) });
  });
  global.fetch = fn;
  return fn;
}

describe('PairingPanel (H12.19) — sender approvals are live', () => {
  it('lists pending senders and POSTs an approve decision with channel + sender_id', async () => {
    const fn = mockFetch({
      '/api/channels/pairing': {
        senders: [{ channel: 'telegram', sender_id: '12345', name: 'maria', status: 'pending' }],
        summary: { pending: 1 },
      },
    });
    render(<PairingPanel />);
    await waitFor(() => expect(screen.getByText('maria')).toBeTruthy());
    fireEvent.click(screen.getByTitle('approve'));
    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/channels/pairing/decide') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toMatchObject({ channel: 'telegram', sender_id: '12345', action: 'approve' });
    });
  });
});

describe('SandboxPanel — code execution is live', () => {
  it('POSTs {code,language} to /sandbox/execute and renders stdout', async () => {
    const fn = mockFetch({
      '/sandbox/status': { backend: 'docker' },
      '/sandbox/execute': { stdout: 'hello from the sandbox', stderr: '', exit_code: 0 },
    });
    render(<SandboxPanel />);
    fireEvent.change(screen.getByPlaceholderText('print("hello from the sandbox")'), { target: { value: 'print(1)' } });
    fireEvent.click(screen.getByText('execute'));
    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/sandbox/execute') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ code: 'print(1)', language: 'python' });
      expect(screen.getByText(/hello from the sandbox/)).toBeTruthy();
    });
  });

  it('surfaces the DEV_MODE gate instead of pretending to run (403 → honest message)', async () => {
    const fn = vi.fn().mockImplementation((url) => Promise.resolve({
      ok: !String(url).includes('/sandbox/execute'),
      status: String(url).includes('/sandbox/execute') ? 403 : 200,
      json: async () => ({}),
    }));
    global.fetch = fn;
    render(<SandboxPanel />);
    fireEvent.change(screen.getByPlaceholderText('print("hello from the sandbox")'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('execute'));
    await waitFor(() => expect(screen.getByText(/sandbox disabled/)).toBeTruthy());
  });
});
