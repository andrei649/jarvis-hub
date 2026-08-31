// @ts-nocheck
/* DRA-36 (sub-agents half) — `GET /api/subagents` and `POST /api/subagents/spawn` (H20.6)
   had no caller: SwarmPanel showed `subagents.spawns` as a bare count and nothing could
   list or start one. Two properties are pinned here beyond the plain wiring:
   (1) the spawn POST runs the sub-agent's whole turn inside the request, so the button
       must lock while it is in flight rather than letting a user fire N of them;
   (2) every cap refusal (concurrency_cap / recursion_depth_cap / spawn_budget_exhausted)
       comes back as a 429, and apiPost THROWS on 4xx — so without an onErr the button
       reads as success. That silent-refusal bug is the one gap.tsx:78-82 warns about. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SubAgentsPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const LIST = {
  spawns: [
    { id: 'sub-jarvis-1', parent: 'jarvis', agent: 'researcher', task: 'read the changelog', status: 'done', blocked: ['shell'] },
    { id: 'sub-jarvis-2', parent: 'jarvis', agent: 'sub', task: 'summarise the inbox', status: 'running', blocked: [] },
  ],
  stats: { total: 2, active: 3, cap: 3, max_depth: 2, blocked: ['shell'] },
};

/* GET returns LIST; POST is delegated to `post(url)` so each test picks its own outcome. */
function mockApi(post) {
  const fn = vi.fn().mockImplementation((url, init) => {
    const method = (init && init.method) || 'GET';
    if (method !== 'POST') return Promise.resolve({ ok: true, status: 200, json: async () => LIST });
    return post(url, init);
  });
  global.fetch = fn;
  return fn;
}

const ok = (payload) => Promise.resolve({ ok: true, status: 200, json: async () => payload });
const refused = (payload) => Promise.resolve({ ok: false, status: 429, json: async () => payload });

describe('SubAgentsPanel — the H20.6 spawn register is reachable', () => {
  it('GETs /api/subagents and lists each spawn with its status', async () => {
    const fn = mockApi(() => ok({}));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]) === '/api/subagents')).toBe(true);
    expect(screen.getByText('sub-jarvis-2')).toBeTruthy();
    expect(screen.getByText('running')).toBeTruthy();
    expect(screen.getByText('done')).toBeTruthy();
    expect(screen.getByText(/read the changelog/)).toBeTruthy();
  });

  it('says so when the concurrency cap is full instead of showing a bare count', async () => {
    mockApi(() => ok({}));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('3/3 active')).toBeTruthy());
    expect(screen.getByText('at cap')).toBeTruthy();
    expect(screen.getByText('depth ≤ 2')).toBeTruthy();
  });

  it('POSTs the task + agent and locks the button while the turn runs', async () => {
    let release;
    const fn = mockApi(() => new Promise((res) => { release = () => res({ ok: true, status: 200, json: async () => ({ ok: true, id: 'sub-jarvis-3', status: 'done' }) }); }));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('task for the sub-agent'), { target: { value: 'check the logs' } });
    fireEvent.change(screen.getByPlaceholderText('agent (optional)'), { target: { value: 'researcher' } });
    fireEvent.click(screen.getByTitle(/spawn/));

    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]) === '/api/subagents/spawn');
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({ task: 'check the logs', agent: 'researcher' });
    });
    // the POST holds the connection open for the whole sub-agent turn — the control must
    // say so and refuse a second click rather than queueing runs behind a spinner-less button
    expect(screen.getByTitle(/spawn/).disabled).toBe(true);
    expect(screen.getByText(/spawning… the connection is held for the whole turn/)).toBeTruthy();

    release();
    await waitFor(() => expect(screen.getByText(/spawned sub-jarvis-3/)).toBeTruthy());
  });

  it('surfaces a 429 cap refusal instead of reading as success', async () => {
    mockApi(() => refused({ ok: false, reason: 'concurrency_cap', active: 3, cap: 3 }));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('task for the sub-agent'), { target: { value: 'check the logs' } });
    fireEvent.click(screen.getByTitle(/spawn/));

    // apiPost rejects on the 429 — this line only renders because spawn() passes an onErr.
    await waitFor(() => expect(screen.getByText(/refused · POST \/api\/subagents\/spawn -> 429/)).toBeTruthy());
    // and the button comes back, rather than staying stuck "running"
    expect(screen.getByTitle(/spawn/).disabled).toBe(false);
  });

  it('states that the spawn request runs the whole turn inline', async () => {
    mockApi(() => ok({}));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText(/stays open until the sub-agent's turn finishes/)).toBeTruthy());
  });
});
