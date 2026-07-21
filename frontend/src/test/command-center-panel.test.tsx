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
  model: {
    backend: 'lm-studio',
    active_provider: 'lm-studio',
    active_model: 'gemma-local',
    configured_model: 'gemma-local',
    resident_models: [{ provider: 'lm-studio', id: 'gemma-local' }],
    residency_state: 'known',
    route: 'local',
    ready: true,
    cloud_configured: false,
  },
  wizard: {
    steps: [{ key: 'intro', title: 'Welcome' }, { key: 'test_chat', title: 'Say hello' }],
    completed: ['intro'], complete: false, hint: null,
  },
  first_actions: [
    { key: 'say_hello', title: 'Say hello', kind: 'chat', path: '/chat', ready: true, reason: null },
    { key: 'morning_brief', title: 'Get your morning brief', kind: 'get', path: '/autonomy/brief', ready: true, reason: null },
    { key: 'index_docs', title: 'Chat with a folder of your docs', kind: 'post', path: '/api/local-docs/index', ready: false, folders: [], reason: 'no folder configured — set local_docs.folders in Admin → settings' },
  ],
  starter_outcomes: [
    { key: 'plan_my_day', title: 'Plan my day', status: 'live', setup: null, privacy: 'third_party_account', changes: 'none' },
    { key: 'private_documents', title: 'Use my private documents', status: 'needs_setup', setup: 'Choose a local folder in Settings.', privacy: 'local_storage_cloud_model', changes: 'none' },
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
    expect(screen.getByText('gemma-local · loaded')).toBeTruthy(); // model truth
    expect(screen.getByText('LIVE')).toBeTruthy();              // honesty chip
  });

  it('labels runnable, configured-only, unknown, and cloud routes honestly', async () => {
    const resident = {
      ...WARM,
      model: {
        backend: 'lm-studio',
        active_provider: 'lm-studio',
        active_model: 'qwen3.5:0.8b',
        configured_model: 'qwen3.5:0.8b',
        resident_models: [{ provider: 'lm-studio', id: 'qwen3.5:0.8b' }],
        residency_state: 'known',
        route: 'local',
        ready: true,
        cloud_configured: false,
      },
    };
    mockFetch({ '/api/onboarding/command-center': resident });
    const mounted = render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText('qwen3.5:0.8b · loaded')).toBeTruthy());
    mounted.unmount();

    const configuredOnly = {
      ...WARM,
      model: {
        backend: 'lm-studio',
        active_provider: null,
        active_model: null,
        configured_model: 'minimax/minimax-m2.7',
        resident_models: [],
        residency_state: 'known',
        route: 'local',
        ready: false,
        cloud_configured: false,
      },
    };
    mockFetch({ '/api/onboarding/command-center': configuredOnly });
    const configuredMount = render(<CommandCenterPanel />);
    await waitFor(() => {
      expect(screen.getByText('minimax/minimax-m2.7 · configured, not loaded')).toBeTruthy();
    });
    configuredMount.unmount();

    const unknown = {
      ...configuredOnly,
      model: { ...configuredOnly.model, residency_state: 'unknown', ready: null },
    };
    mockFetch({ '/api/onboarding/command-center': unknown });
    const unknownMount = render(<CommandCenterPanel />);
    await waitFor(() => {
      expect(screen.getByText('minimax/minimax-m2.7 · residency unknown')).toBeTruthy();
    });
    unknownMount.unmount();

    const cloud = {
      ...WARM,
      model: {
        backend: 'gemini',
        active_provider: 'gemini',
        active_model: 'gemini-2.5-flash',
        configured_model: 'minimax/minimax-m2.7',
        resident_models: [],
        residency_state: 'offline',
        route: 'cloud-flash',
        ready: true,
        cloud_configured: true,
      },
    };
    mockFetch({ '/api/onboarding/command-center': cloud });
    const cloudMount = render(<CommandCenterPanel />);
    await waitFor(() => {
      expect(screen.getByText('gemini-2.5-flash · cloud ready')).toBeTruthy();
    });
    cloudMount.unmount();

    const missingResident = {
      ...resident,
      model: { ...resident.model, resident_models: [] },
    };
    mockFetch({ '/api/onboarding/command-center': missingResident });
    const missingResidentMount = render(<CommandCenterPanel />);
    await waitFor(() => {
      expect(screen.getByText('qwen3.5:0.8b · configured, not loaded')).toBeTruthy();
    });
    missingResidentMount.unmount();

    const unsafeCloud = {
      ...cloud,
      model: {
        ...cloud.model,
        active_model: 'gemini-pretender',
        configured_model: 'gemini-pretender',
        route: 'not-cloud',
      },
    };
    mockFetch({ '/api/onboarding/command-center': unsafeCloud });
    const unsafeRouteMount = render(<CommandCenterPanel />);
    await waitFor(() => {
      expect(screen.getByText('gemini-pretender · configured, not loaded')).toBeTruthy();
    });
    unsafeRouteMount.unmount();

    const sentinel = {
      ...cloud,
      model: { ...cloud.model, active_model: 'none', configured_model: 'none' },
    };
    mockFetch({ '/api/onboarding/command-center': sentinel });
    render(<CommandCenterPanel />);
    await waitFor(() => {
      expect(screen.getByText('no runnable model')).toBeTruthy();
    });
    expect(screen.queryByText(/none · (loaded|cloud ready)/)).toBeNull();
  });

  it('a held action shows its reason, never a run button', async () => {
    mockFetch({ '/api/onboarding/command-center': WARM });
    render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText(/no folder configured/)).toBeTruthy());
    // only the ready say_hello action gets a run button
    expect(screen.getAllByText('run').length).toBe(1);
  });

  it('renders consumer outcomes with live/setup, privacy, and effect truth', async () => {
    mockFetch({ '/api/onboarding/command-center': WARM });
    render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText('Plan my day')).toBeTruthy());
    expect(screen.getByText('Use my private documents')).toBeTruthy();
    expect(screen.getByText('READY NOW')).toBeTruthy();
    expect(screen.getByText('NEEDS SETUP')).toBeTruthy();
    expect(screen.getByText('stored locally · cloud model may receive context')).toBeTruthy();
    expect(screen.getAllByText('read-only')).toHaveLength(2);
    expect(screen.getByText('Choose a local folder in Settings.')).toBeTruthy();
  });

  it('labels private documents as staying local on a local model route', async () => {
    const localDocuments = {
      ...WARM,
      starter_outcomes: [
        { key: 'private_documents', title: 'Use my private documents', status: 'live', setup: null, privacy: 'local_only', changes: 'none' },
      ],
    };
    mockFetch({ '/api/onboarding/command-center': localDocuments });
    render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText('Use my private documents')).toBeTruthy());
    expect(screen.getByText('stays local')).toBeTruthy();
    expect(screen.getByText('read-only')).toBeTruthy();
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

  it('a degraded "say hello" reply does NOT tick the test_chat step (honest wizard)', async () => {
    // Real-world finding (2026-07-08 test-drive): a fresh install where the model
    // 400s/is-unreachable returns a degraded "⚠️ can't reach the model" reply.
    // The panel used to record test_chat.complete anyway, so the wizard ticked
    // "Say hello ✓" on a hello that never actually reached a model.
    const fn = mockFetch({
      '/api/onboarding/command-center': WARM,
      '/chat': { reply: '⚠️ The local LM Studio model hit an error and couldn\'t answer.' },
      '/api/onboarding/funnel': { ok: true, recorded: 'funnel.test_chat.complete' },
    });
    render(<CommandCenterPanel />);
    await waitFor(() => expect(screen.getByText('run')).toBeTruthy());
    fireEvent.click(screen.getByText('run'));
    await waitFor(() => expect(screen.getByText(/hit an error/)).toBeTruthy());  // shows the failure
    const posts = fn.mock.calls.filter((c) => c[1] && c[1].method === 'POST').map((c) => String(c[0]));
    expect(posts.some((u) => u.includes('/chat'))).toBe(true);                    // the hello was attempted
    expect(posts.some((u) => u.includes('/api/onboarding/funnel'))).toBe(false);  // but NOT recorded complete
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
