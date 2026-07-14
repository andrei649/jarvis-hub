import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { mapLocalModelsForAdmin, localModelStatus, useLiveModes } from '../api/live';
import { V2 } from '../data';
import { LMStudioPanel } from '../gap';

const controls = (can_configure = false, can_load = false, can_unload = false) => ({
  can_configure, can_load, can_unload,
});

const INVENTORY = {
  models: [
    { id: 'resident', provider: 'lm-studio', available: true, configured: false, resident: true, controls: controls(true, false, true) },
    { id: 'unknown', provider: 'lm-studio', available: true, configured: true, resident: null, controls: controls(false, false, false) },
    { id: 'loadable', provider: 'lm-studio', available: true, configured: false, resident: false, controls: controls(true, true, false) },
    { id: 'catalog-unknown', provider: 'lm-studio', available: null, configured: false, resident: false, controls: controls(false, false, false) },
    { id: 'missing', provider: 'lm-studio', available: false, configured: false, active: true, resident: false, controls: controls(false, false, false) },
    // Deliberately malformed capabilities: the frontend must still never route an
    // Ollama id through LM Studio lifecycle endpoints.
    { id: 'ollama-ready', provider: 'ollama', available: true, configured: false, resident: false, controls: controls(true, true, true) },
  ],
};

function mockInventory() {
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => Promise.resolve({
    ok: true,
    status: 200,
    json: async () => url === '/api/models/local' ? INVENTORY : { ok: true, status: 'ok' },
  }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function LiveModesHarness() {
  const state = useLiveModes();
  return <div data-testid="model-evidence">models:{String(state.live.ADMIN_MODELS === true)}</div>;
}

function installLiveModesFetch(modelResponses: Array<{ ok: boolean; status: number; payload?: unknown }>) {
  let modelCall = 0;
  const fetchMock = vi.fn((url: string) => {
    if (url === '/plugins') return Promise.resolve({
      ok: true, status: 200,
      json: async () => ({ plugins: [{ id: 'calendar', name: 'Calendar', enabled: true, configured: true }] }),
    });
    if (url === '/api/models/local') {
      const response = modelResponses[Math.min(modelCall, modelResponses.length - 1)];
      modelCall += 1;
      return Promise.resolve({
        ok: response.ok,
        status: response.status,
        json: async () => response.payload ?? {},
      });
    }
    return unavailableResponse();
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

const unavailableResponse = () => Promise.resolve({
  ok: false, status: 503, json: async () => ({}),
});

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe('local model truth adapter', () => {
  it('uses resident/available precedence and preserves configured plus controls', () => {
    expect(INVENTORY.models.map(localModelStatus)).toEqual([
      'loaded',
      'residency unknown',
      'ready',
      'availability unknown',
      'unavailable',
      'ready',
    ]);

    const mapped = mapLocalModelsForAdmin(INVENTORY.models);
    expect(mapped.map((row) => row.status)).toEqual([
      'loaded',
      'residency unknown',
      'ready',
      'availability unknown',
      'unavailable',
      'ready',
    ]);
    expect(mapped[1]).toMatchObject({
      id: 'unknown', provider: 'lm-studio', configured: true, resident: null,
      controls: controls(false, false, false),
    });
  });
});

describe('LMStudioPanel truthful controls', () => {
  it('renders residency independently from configured state and removes free-form lifecycle', async () => {
    mockInventory();
    render(<LMStudioPanel />);

    await waitFor(() => expect(screen.getByText('resident')).toBeTruthy());
    expect(screen.getByText('loaded')).toBeTruthy();
    expect(screen.getByText('residency unknown')).toBeTruthy();
    expect(screen.getAllByText('ready').length).toBe(2);
    expect(screen.getByText('availability unknown')).toBeTruthy();
    expect(screen.getByText('unavailable')).toBeTruthy();
    expect(screen.getByText('configured')).toBeTruthy();
    expect(screen.queryByPlaceholderText('model id')).toBeNull();
  });

  it('offers only capability-declared actions and never sends Ollama to LM Studio lifecycle', async () => {
    const fetchMock = mockInventory();
    render(<LMStudioPanel />);
    await waitFor(() => expect(screen.getByText('resident')).toBeTruthy());

    expect(screen.getByTitle('unload lm-studio:resident')).toBeTruthy();
    expect(screen.getByTitle('load lm-studio:loadable')).toBeTruthy();
    expect(screen.getByTitle('configure ollama:ollama-ready')).toBeTruthy();
    expect(screen.queryByTitle('load ollama:ollama-ready')).toBeNull();
    expect(screen.queryByTitle('unload ollama:ollama-ready')).toBeNull();

    fireEvent.click(screen.getByTitle('configure ollama:ollama-ready'));
    fireEvent.click(screen.getByTitle('load lm-studio:loadable'));
    fireEvent.click(screen.getByTitle('unload lm-studio:resident'));

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST');
      expect(posts.some(([url, init]) => url === '/api/models/local/switch'
        && JSON.parse(String(init?.body)).model === 'ollama-ready')).toBe(true);
      expect(posts.some(([url, init]) => url === '/api/llm/load'
        && JSON.parse(String(init?.body)).model === 'loadable')).toBe(true);
      expect(posts.some(([url, init]) => url === '/api/llm/unload'
        && JSON.parse(String(init?.body)).model === 'resident')).toBe(true);
      expect(posts.some(([url, init]) => String(url).startsWith('/api/llm/')
        && JSON.parse(String(init?.body || '{}')).model === 'ollama-ready')).toBe(false);
    });
  });

  it.each([
    ['configure', '/api/models/local/switch', 'configure ollama:ollama-ready', 409],
    ['load', '/api/llm/load', 'load lm-studio:loadable', 503],
  ])('surfaces a bounded %s failure and refreshes inventory', async (label, failedPath, title, status) => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/models/local' && (!init || init.method === 'GET')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => INVENTORY });
      }
      if (url === failedPath && init?.method === 'POST') {
        return Promise.resolve({ ok: false, status, json: async () => ({ error: 'sensitive backend detail' }) });
      }
      return unavailableResponse();
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<LMStudioPanel />);
    await waitFor(() => expect(screen.getByText('resident')).toBeTruthy());

    fireEvent.click(screen.getByTitle(title));

    await waitFor(() => expect(screen.getByText(`${label} failed · HTTP ${status}`)).toBeTruthy());
    expect(screen.queryByText(/sensitive backend detail/)).toBeNull();
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/models/local').length).toBeGreaterThan(1);
  });
});

describe('Admin local-model evidence', () => {
  it('clears seeded models when plugins succeed but the model payload is malformed', async () => {
    const savedModels = V2.ADMIN.models;
    V2.ADMIN.models = [{ name: 'seeded-gemma', type: 'local', backend: 'seed', ctx: '—', status: 'loaded', use: '' }];
    installLiveModesFetch([{ ok: true, status: 200, payload: { models: 'malformed' } }]);
    const view = render(<LiveModesHarness />);
    try {
      await waitFor(() => expect(V2.ADMIN.models).toEqual([]));
      expect(screen.getByTestId('model-evidence').textContent).toBe('models:false');
    } finally {
      view.unmount();
      V2.ADMIN.models = savedModels;
    }
  });

  it('clears a previous successful inventory and its evidence when the next cycle fails', async () => {
    const savedModels = V2.ADMIN.models;
    let poll: TimerHandler | undefined;
    const nativeSetInterval = window.setInterval.bind(window);
    const intervalSpy = vi.spyOn(window, 'setInterval').mockImplementation((handler: TimerHandler, timeout?: number, ...args: any[]) => {
      if (timeout === 30000) {
        poll = handler;
        return 1;
      }
      return nativeSetInterval(handler, timeout, ...args);
    });
    installLiveModesFetch([
      { ok: true, status: 200, payload: { models: [INVENTORY.models[0]] } },
      { ok: false, status: 503 },
    ]);
    const view = render(<LiveModesHarness />);
    try {
      await waitFor(() => expect(V2.ADMIN.models[0]?.name).toBe('resident'));
      expect(screen.getByTestId('model-evidence').textContent).toBe('models:true');
      expect(typeof poll).toBe('function');

      act(() => { if (typeof poll === 'function') poll(); });

      await waitFor(() => expect(V2.ADMIN.models).toEqual([]));
      expect(screen.getByTestId('model-evidence').textContent).toBe('models:false');
    } finally {
      view.unmount();
      intervalSpy.mockRestore();
      V2.ADMIN.models = savedModels;
    }
  });
});
