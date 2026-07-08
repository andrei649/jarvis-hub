// @ts-nocheck
/* 0.19 — the First-Run Command Center panel reads GET /api/onboarding/command-center
   (install health + model + wizard + honest first actions in one fetch). fetch is
   mocked (like comms-rate-panel.test.tsx). Asserts the wiring, the install/model
   truth rows, that a ready "say hello" action drives a real /chat turn + records the
   test_chat funnel step, and that a held action shows its reason instead of a button. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CommandCenterPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const WARM = {
  install: { ready: true, version: '0.11.0', checks: { agents_loaded: 17 } },
  model: { backend: 'lmstudio', active_model: 'gemma-local', ready: true, cloud_configured: false },
  wizard: {
    steps: [{ key: 'intro', title: 'Welcome' }, { key: 'test_chat', title: 'Say hello' }],
    completed: ['intro'], complete: false, hint: null,
  },
  first_actions: [
    { key: 'say_hello', title: 'Say hello', kind: 'chat', path: '/chat', ready: true, reason: null },
    { key: 'morning_brief', title: 'Get your morning brief', kind: 'get', path: '/autonomy/brief', ready: true, reason: null },
    { key: 'index_docs', title: 'Chat with a folder of your docs', kind: 'post', path: '/api/local-docs/index', ready: false, folders: [], reason: 'no folder configured — set local_docs.folders in Admin → settings' },
  ],
};

function mockFetch(routes) {
  const fn = vi.fn().mockImplementation((url, opts) => {
    const path = String(url);
    const hit = Object.entries(routes).find(([p]) => path.includes(p));
    const payload = hit ? (typeof hit[1] === 'function' ? hit[1](opts) : hit[1]) : {};
    return Promise.resolve({ ok: true, status: 200, json: async () => payload });
  });
  global.fetch = fn;
  return fn;
}

describe('CommandCenterPanel — one screen: install health + model + first actions', () => {
  it('GETs the command-center read and renders the truth rows', async () => {
    const fn = mockFetch({ '/api/onboarding/command-center': WARM });
    render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText(/v0\.11\.0/)).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/onboarding/command-center'))).toBe(true);
    expect(screen.getByText(/✓ ready/)).toBeTruthy();          // install health
    expect(screen.getByText('gemma-local')).toBeTruthy();       // model truth
    expect(screen.getByText('LIVE')).toBeTruthy();              // honesty chip
  });

  it('a held action shows its reason, never a run button', async () => {
    mockFetch({ '/api/onboarding/command-center': WARM });
    render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText(/no folder configured/)).toBeTruthy());
    // only the ready say_hello action gets a run button
    expect(screen.getAllByText('run').length).toBe(1);
  });

  it('say hello drives a real /chat turn and records the funnel step', async () => {
    const fn = mockFetch({
      '/api/onboarding/command-center': WARM,
      '/chat': { reply: 'Hello sir, all systems nominal.' },
      '/api/onboarding/funnel': { ok: true, recorded: 'funnel.test_chat.complete' },
    });
    render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText('run')).toBeTruthy());
    fireEvent.click(screen.getByText('run'));
    await waitFor(() => expect(screen.getByText(/all systems nominal/)).toBeTruthy());
    const posts = fn.mock.calls.filter((c) => c[1] && c[1].method === 'POST').map((c) => String(c[0]));
    expect(posts.some((u) => u.includes('/chat'))).toBe(true);
    expect(posts.some((u) => u.includes('/api/onboarding/funnel'))).toBe(true);
  });

  it('cold start renders honestly (starting, no model, actions held)', async () => {
    mockFetch({
      '/api/onboarding/command-center': {
        install: { ready: false, version: '0.11.0', checks: {} },
        model: { backend: 'none', active_model: null, ready: null, cloud_configured: false },
        wizard: { steps: [], completed: [], complete: false, hint: null },
        first_actions: [
          { key: 'say_hello', title: 'Say hello', kind: 'chat', path: '/chat', ready: false, reason: 'still starting' },
          { key: 'morning_brief', title: 'Get your morning brief', kind: 'get', path: '/autonomy/brief', ready: false, reason: 'still starting' },
          { key: 'index_docs', title: 'Chat with a folder of your docs', kind: 'post', path: '/api/local-docs/index', ready: false, folders: [], reason: 'no folder configured — set local_docs.folders in Admin → settings' },
        ],
      },
    });
    render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText(/○ starting/)).toBeTruthy());
    expect(screen.queryByText('run')).toBeNull();
    expect(screen.getAllByText(/still starting/).length).toBeGreaterThan(0);
  });
});
