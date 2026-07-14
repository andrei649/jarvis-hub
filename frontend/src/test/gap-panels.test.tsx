// @ts-nocheck
/* Smoke tests for the TASK-2 depth panels: each new Console panel must hit its REAL
   endpoint (method + path + body verified against agents/web.py). fetch is mocked —
   these assert the wiring through the component, like wired-controls.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import gapSource from '../gap.tsx?raw';
import { CapabilitiesPanel, DataSpacesPanel, LMStudioPanel, PairingPanel, RoomsPanel, SandboxPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url) => {
    const hit = Object.entries(routes).find(([p]) => String(url).includes(p));
    return Promise.resolve({ ok: true, status: 200, json: async () => (hit ? hit[1] : {}) });
  });
  global.fetch = fn;
  return fn;
}

describe('Console Build registry', () => {
  it('imports and registers the governed Operator panel in Build', () => {
    expect(gapSource).toMatch(/import\s+\{\s*OperatorPanel\s*\}\s+from\s+['"]\.\/operator-panel['"]/);
    expect(gapSource).toMatch(/\['Build', \[[^\]]*\bOperatorPanel\b/);
  });
});

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

describe('DataSpacesPanel (H10.26) — per-agent scope controls are live', () => {
  it('renders current assignments and POSTs assign/unassign decisions', async () => {
    const fn = mockFetch({
      '/api/memory/spaces': {
        spaces: [{ space: 'family', sources: ['family_facts'] }],
        assignments: { frigga: ['family'] },
      },
      '/api/memory/spaces/assign': { ok: true },
      '/api/memory/spaces/unassign': { ok: true },
    });
    render(<DataSpacesPanel />);

    await waitFor(() => expect(screen.getByText('frigga')).toBeTruthy());
    expect(screen.getAllByText('family').length).toBeGreaterThan(0);

    fireEvent.change(screen.getByPlaceholderText('agent id'), { target: { value: 'jarvis' } });
    fireEvent.change(screen.getByLabelText('space to assign'), { target: { value: 'family' } });
    fireEvent.click(screen.getByText('assign'));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/memory/spaces/assign') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ agent: 'jarvis', space: 'family' });
    });

    fireEvent.click(screen.getByTitle('unassign frigga from family'));
    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/memory/spaces/unassign') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ agent: 'frigga', space: 'family' });
    });
  });
});

describe('RoomsPanel (H10.20) — saved room history is visible', () => {
  it('opens the selected room history drawer from the real history endpoint', async () => {
    const fn = mockFetch({
      '/api/rooms/room-1/history': {
        history: [
          { role: 'user', content: '@jarvis plan the launch', at: '2026-07-04T12:00:00Z' },
          { role: 'assistant', agent: 'jarvis', content: 'Launch plan ready.', at: '2026-07-04T12:00:01Z' },
        ],
      },
      '/api/rooms': {
        rooms: [{ id: 'room-1', name: 'project-alpha', agents: ['jarvis'] }],
      },
    });
    render(<RoomsPanel />);

    await waitFor(() => expect(screen.getByText('project-alpha')).toBeTruthy());
    fireEvent.click(screen.getByText('project-alpha'));

    await waitFor(() => {
      const get = fn.mock.calls.find((c) => String(c[0]).includes('/api/rooms/room-1/history'));
      expect(get).toBeTruthy();
      expect(screen.getByText('@jarvis plan the launch')).toBeTruthy();
      expect(screen.getByText('Launch plan ready.')).toBeTruthy();
    });
  });
});

describe('CapabilitiesPanel (H17.3) — grants can be issued and checked', () => {
  it('POSTs capability issue requests, lists the issued grant, and checks a token/capability pair', async () => {
    const fn = mockFetch({
      '/api/security/capabilities/issue': {
        ok: true,
        token: {
          id: 'tok-123',
          capabilities: ['memory.write'],
          expires_at: 1783180800,
        },
      },
      '/api/security/capabilities/check': {
        allowed: true,
        reason: '',
      },
    });
    render(<CapabilitiesPanel />);

    fireEvent.change(screen.getByPlaceholderText('capabilities csv'), { target: { value: 'memory.write' } });
    fireEvent.click(screen.getByText('issue'));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/security/capabilities/issue') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ capabilities: ['memory.write'] });
      expect(screen.getByText('tok-123')).toBeTruthy();
      expect(screen.getByText('memory.write')).toBeTruthy();
    });

    fireEvent.change(screen.getByPlaceholderText('token id'), { target: { value: 'tok-123' } });
    fireEvent.change(screen.getByPlaceholderText('capability to check'), { target: { value: 'memory.write' } });
    fireEvent.click(screen.getByText('check'));

    await waitFor(() => {
      const get = fn.mock.calls.find((c) => String(c[0]).includes('/api/security/capabilities/check'));
      expect(get).toBeTruthy();
      expect(String(get[0])).toContain('token=tok-123');
      expect(String(get[0])).toContain('capability=memory.write');
      expect(screen.getByText('allowed')).toBeTruthy();
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

describe('LMStudioPanel — configuration stays separate from residency', () => {
  it('uses the exact provider-pair switch body without treating configuration as load', async () => {
    const fn = mockFetch({
      '/api/models/local/switch': { ok: true, active: 'qwen:7b' },
      '/api/models/local': {
        models: [{
          id: 'qwen:7b', provider: 'ollama', available: true, configured: false, resident: false,
          controls: { can_configure: true, can_load: false, can_unload: false },
        }],
      },
    });
    render(<LMStudioPanel />);
    await waitFor(() => expect(screen.getByText('qwen:7b')).toBeTruthy());
    fireEvent.click(screen.getByTitle('configure ollama:qwen:7b'));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => c[0] === '/api/models/local/switch' && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({ model: 'qwen:7b', provider: 'ollama' });
      expect(fn.mock.calls.some((c) => String(c[0]).startsWith('/api/llm/') && c[1]?.method === 'POST')).toBe(false);
    });
  });
});
