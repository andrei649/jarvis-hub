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
    // DRA-52 residual: it used to print `err.message`, i.e. the request line
    // "POST /api/subagents/spawn -> 429", as the *reason* the spawn was refused. The
    // backend said `concurrency_cap`; that is what an operator needs and now what they get.
    await waitFor(() => expect(screen.getByText(/refused · concurrency_cap/)).toBeTruthy());
    expect(screen.queryByText(/-> 429/)).toBeNull();
    // and the button comes back, rather than staying stuck "running"
    expect(screen.getByTitle(/spawn/).disabled).toBe(false);
  });

  it('states that the spawn request runs the whole turn inline', async () => {
    mockApi(() => ok({}));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText(/stays open until the sub-agent's turn finishes/)).toBeTruthy());
  });

  /* 1.1.0 — steer and stop. The backend answers 409 `not_running` for a finished spawn,
     so the controls must not be offered on one; and `delivered:false` is an honest
     partial (the record kept the message, the running turn never saw it) that must not
     read as a plain success. */
  it('offers steer and stop only on a running spawn', async () => {
    mockApi(() => ok({}));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    // sub-jarvis-2 is the only running row in LIST, so exactly one pair of controls
    expect(screen.getAllByTitle(/send guidance/).length).toBe(1);
    expect(screen.getAllByTitle(/cancel this running sub-agent/).length).toBe(1);
  });

  it('POSTs the steer message to the running spawn and reports delivery', async () => {
    const fn = mockApi((url) => (String(url).includes('/steer')
      ? ok({ ok: true, id: 'sub-jarvis-2', delivered: true, origin: 'user', pending: 1 })
      : ok({})));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-2')).toBeTruthy());

    fireEvent.click(screen.getByTitle(/send guidance/));
    fireEvent.change(screen.getByPlaceholderText(/guidance for sub-jarvis-2/), {
      target: { value: 'prefer the changelog over the diff' },
    });
    fireEvent.click(screen.getByText('send'));

    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]) === '/api/subagents/sub-jarvis-2/steer');
      expect(call).toBeTruthy();
      expect(JSON.parse(call[1].body)).toEqual({ message: 'prefer the changelog over the diff' });
    });
    await waitFor(() => expect(screen.getByText(/steered sub-jarvis-2 · delivered/)).toBeTruthy());
  });

  it('renders an undelivered steer as recorded, not as delivered', async () => {
    mockApi((url) => (String(url).includes('/steer')
      ? ok({ ok: true, id: 'sub-jarvis-2', delivered: false, origin: 'user', pending: 0 })
      : ok({})));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-2')).toBeTruthy());

    fireEvent.click(screen.getByTitle(/send guidance/));
    fireEvent.change(screen.getByPlaceholderText(/guidance for sub-jarvis-2/), {
      target: { value: 'slow down' },
    });
    fireEvent.click(screen.getByText('send'));

    await waitFor(() => expect(
      screen.getByText(/recorded, not delivered to the running turn/)).toBeTruthy());
  });

  it('POSTs the stop and reports the status the backend read back', async () => {
    const fn = mockApi((url) => (String(url).includes('/stop')
      ? ok({ ok: true, id: 'sub-jarvis-2', status: 'stopped' })
      : ok({})));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-2')).toBeTruthy());

    fireEvent.click(screen.getByTitle(/cancel this running sub-agent/));

    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]) === '/api/subagents/sub-jarvis-2/stop');
      expect(call).toBeTruthy();
    });
    await waitFor(() => expect(screen.getByText(/sub-jarvis-2 is stopped/)).toBeTruthy());
  });

  it('surfaces a 409 not_running refusal on stop instead of reading as success', async () => {
    mockApi((url) => (String(url).includes('/stop')
      ? Promise.resolve({ ok: false, status: 409, json: async () => ({ ok: false, reason: 'not_running' }) })
      : ok({})));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-2')).toBeTruthy());

    fireEvent.click(screen.getByTitle(/cancel this running sub-agent/));
    // apiPost rejects on the 409 — this only renders because stopSpawn passes an onErr.
    await waitFor(() => expect(screen.getByText(/refused ·/)).toBeTruthy());
  });
});

/* H681 — a child's own model, and honest failure. */
describe('SubAgentsPanel — per-child model and failure reasons (H681)', () => {
  const withRows = (spawns) => {
    const fn = vi.fn().mockImplementation((url, init) => {
      const method = (init && init.method) || 'GET';
      if (method !== 'POST') return Promise.resolve({ ok: true, status: 200, json: async () => ({ ...LIST, spawns }) });
      return ok({});
    });
    global.fetch = fn;
    return fn;
  };

  it('sends the model only when one is typed', async () => {
    const fn = mockApi(() => ok({ ok: true, id: 'sub-jarvis-3', status: 'done' }));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('task for the sub-agent'), { target: { value: 'a' } });
    fireEvent.click(screen.getByTitle(/spawn/));
    await waitFor(() => expect(screen.getByText(/spawned sub-jarvis-3/)).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('task for the sub-agent'), { target: { value: 'b' } });
    fireEvent.change(screen.getByPlaceholderText('model (optional)'), { target: { value: '  qwen3:8b ' } });
    fireEvent.click(screen.getByTitle(/spawn/));
    await waitFor(() => expect(fn.mock.calls.filter((c) => c[1] && c[1].method === 'POST').length).toBe(2));
    const bodies = fn.mock.calls.filter((c) => c[1] && c[1].method === 'POST').map((c) => JSON.parse(c[1].body));
    expect(bodies[0]).toEqual({ task: 'a', agent: '' });
    expect(bodies[1]).toEqual({ task: 'b', agent: '', model: 'qwen3:8b' });
  });

  it('shows a failed child as failed with the reason, not as a refusal', async () => {
    mockApi(() => Promise.resolve({ ok: false, status: 422, json: async () => ({
      ok: false, id: 'sub-jarvis-3', status: 'failed',
      result: { error: 'provider_failed', detail: "openrouter: model 'foo' not found (HTTP 404)" } }) }));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('task for the sub-agent'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTitle(/spawn/));
    await waitFor(() => expect(screen.getByText("failed · openrouter: model 'foo' not found (HTTP 404)")).toBeTruthy());
    expect(screen.getByRole('alert').style.color).toBe('var(--red)');
  });

  it('names the price and the flag a guarded model needs', async () => {
    mockApi(() => Promise.resolve({ ok: false, status: 409, json: async () => ({
      error: 'selection_guard', detail: 'claude-fable-5 costs $10/M input and $50/M output tokens',
      needs: ['confirm_expensive'] }) }));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('task for the sub-agent'), { target: { value: 'x' } });
    fireEvent.change(screen.getByPlaceholderText('model (optional)'), { target: { value: 'claude-fable-5' } });
    fireEvent.click(screen.getByTitle(/spawn/));
    await waitFor(() => expect(screen.getByText(/refused · claude-fable-5 costs \$10\/M/)).toBeTruthy());
    expect(screen.getByText(/needs confirm_expensive/)).toBeTruthy();
  });

  it('lists the model a child ran on and what chose it, and why a child failed', async () => {
    withRows([
      { id: 'sub-jarvis-4', agent: 'sub', task: 'x', status: 'failed',
        selection: { model: 'foo', provider: 'openrouter', source: 'setting' },
        failure: { error: 'provider_failed', detail: '[OpenRouter error]' } },
      { id: 'sub-jarvis-5', agent: 'sub', task: 'y', status: 'done',
        selection: { model: 'qwen3:8b', provider: null, source: 'explicit' } },
      { id: 'sub-jarvis-6', agent: 'sub', task: 'z', status: 'done',
        selection: { model: null, provider: null, source: 'parent' } },
    ]);
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-4')).toBeTruthy());
    expect(screen.getByText('foo').closest('span[title]').getAttribute('title')).toBe('model chosen by autonomy.subagent_model');
    expect(screen.getByText('qwen3:8b').closest('span[title]').getAttribute('title')).toBe('model chosen by the spawn');
    expect(screen.getByText('provider_failed · [OpenRouter error]')).toBeTruthy();
    expect(screen.getAllByText(/provider_failed/)).toHaveLength(1);    // the done rows carry none
  });
});

describe('SubAgentsPanel — batch (H681)', () => {
  it('POSTs one child per line and shows the summary and the notice', async () => {
    const fn = mockApi(() => ok({
      ok: false, children: [],
      summary: { total: 2, done: 0, failed: 2, refused: 0 },
      notice: { kind: 'subagent_model_rejected', model: 'foo',
                message: "Every sub-agent in this batch failed: openrouter does not know the model 'foo'" } }));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText(/batch: one task per line/), { target: { value: 'a\n\n  b  \n' } });
    fireEvent.change(screen.getByPlaceholderText('agent (optional)'), { target: { value: 'researcher' } });
    fireEvent.click(screen.getByTitle(/run these tasks as a batch/));
    await waitFor(() => expect(screen.getByText('batch · 0 done · 2 failed · 0 refused')).toBeTruthy());
    expect(screen.getByText(/does not know the model 'foo'/)).toBeTruthy();
    const post = fn.mock.calls.find((c) => c[1] && c[1].method === 'POST');
    expect(String(post[0])).toBe('/api/subagents/batch');
    expect(JSON.parse(post[1].body)).toEqual({ tasks: [{ task: 'a', agent: 'researcher' }, { task: 'b', agent: 'researcher' }] });
  });

  it('refuses more than 16 tasks before sending anything', async () => {
    const fn = mockApi(() => ok({}));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    const many = Array.from({ length: 17 }, (_, i) => `t${i}`).join('\n');
    fireEvent.change(screen.getByPlaceholderText(/batch: one task per line/), { target: { value: many } });
    expect(screen.getByText('a batch holds at most 16 tasks')).toBeTruthy();
    expect(screen.getByTitle(/run these tasks as a batch/).disabled).toBe(true);
    expect(fn.mock.calls.some((c) => c[1] && c[1].method === 'POST')).toBe(false);
  });
});

describe('SubAgentsPanel — a guarded model is confirmed, not lost (H681 review)', () => {
  it('resends the same spawn with exactly the flags the hub named', async () => {
    let n = 0;
    const fn = mockApi(() => (++n === 1
      ? Promise.resolve({ ok: false, status: 409, json: async () => ({
          error: 'selection_guard', detail: 'claude-fable-5 costs $50/M output', needs: ['confirm_expensive'] }) })
      : ok({ ok: true, id: 'sub-jarvis-9', status: 'done' })));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('task for the sub-agent'), { target: { value: 'x' } });
    fireEvent.change(screen.getByPlaceholderText('model (optional)'), { target: { value: 'claude-fable-5' } });
    fireEvent.click(screen.getByTitle(/spawn a sub-agent/));
    await waitFor(() => expect(screen.getByText('confirm (confirm_expensive) and send')).toBeTruthy());
    fireEvent.click(screen.getByTitle(/confirm this model/));
    await waitFor(() => expect(screen.getByText(/spawned sub-jarvis-9/)).toBeTruthy());
    const posts = fn.mock.calls.filter((c) => c[1] && c[1].method === 'POST').map((c) => JSON.parse(c[1].body));
    expect(posts).toEqual([
      { task: 'x', agent: '', model: 'claude-fable-5' },
      { task: 'x', agent: '', model: 'claude-fable-5', confirm_expensive: true },
    ]);
    expect(screen.queryByText(/confirm \(confirm_expensive\)/)).toBeNull();
  });

  it('confirms a guarded batch against the batch route', async () => {
    let n = 0;
    const fn = mockApi(() => (++n === 1
      ? Promise.resolve({ ok: false, status: 409, json: async () => ({
          error: 'selection_guard', detail: 'trains on prompts', needs: ['acknowledge_training'] }) })
      : ok({ ok: true, children: [], summary: { total: 1, done: 1, failed: 0, refused: 0 }, notice: null })));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText(/batch: one task per line/), { target: { value: 'a' } });
    fireEvent.click(screen.getByTitle(/run these tasks as a batch/));
    await waitFor(() => expect(screen.getByTitle(/confirm this model/)).toBeTruthy());
    fireEvent.click(screen.getByTitle(/confirm this model/));
    await waitFor(() => expect(screen.getByText('batch · 1 done · 0 failed · 0 refused')).toBeTruthy());
    const posts = fn.mock.calls.filter((c) => c[1] && c[1].method === 'POST');
    expect(String(posts[1][0])).toBe('/api/subagents/batch');
    expect(JSON.parse(posts[1][1].body).acknowledge_training).toBe(true);
  });

  it('names why a selection is invalid', async () => {
    mockApi(() => Promise.resolve({ ok: false, status: 422, json: async () => ({
      ok: false, reason: 'invalid_selection', detail: 'model must be a bounded model identifier' }) }));
    render(<SubAgentsPanel />);
    await waitFor(() => expect(screen.getByText('sub-jarvis-1')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('task for the sub-agent'), { target: { value: 'x' } });
    fireEvent.change(screen.getByPlaceholderText('model (optional)'), { target: { value: 'bad model' } });
    fireEvent.click(screen.getByTitle(/spawn a sub-agent/));
    await waitFor(() => expect(screen.getByText('refused · model must be a bounded model identifier')).toBeTruthy());
    expect(screen.queryByTitle(/confirm this model/)).toBeNull();
  });
});
