import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { commandCenterModelLabel, fetchCommandCenter } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

const config = { baseUrl: 'hub.local', token: '', adminToken: '' } as any;

describe('mobile first-run command center API (H18.19)', () => {
  it('fetches the unified command-center read and normalizes it', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        install: { ready: true, version: '0.11.0', checks: { agents_loaded: 17, channels: 2 } },
        model: {
          backend: 'lm-studio',
          active_model: 'gemma-local',
          configured_model: 'gemma-local',
          resident_models: [
            { provider: 'lm-studio', id: 'gemma-local' },
            { provider: '', id: 'discard-me' },
            'malformed',
          ],
          residency_state: 'known',
          active_provider: 'lm-studio',
          route: 'local',
          ready: true,
          cloud_configured: false,
        },
        wizard: {
          steps: [
            { key: 'intro', title: 'Welcome to Jarvis' },
            { key: 'model', title: 'Connect a model' },
          ],
          completed: ['intro'],
          complete: false,
          hint: null,
        },
        first_actions: [
          { key: 'say_hello', title: 'Say hello', kind: 'chat', path: '/chat', ready: true, reason: null },
          {
            key: 'index_docs',
            title: 'Chat with a folder of your docs',
            kind: 'post',
            path: '/api/local-docs/index',
            ready: false,
            folders: [],
            reason: 'no folder configured — set local_docs.folders in Admin → settings',
          },
        ],
      }),
    );
    const out = await fetchCommandCenter(config);
    const url = String(mockFetch.mock.calls[0][0]);
    expect(url).toContain('/api/onboarding/command-center');
    expect(out.install.ready).toBe(true);
    expect(out.install.version).toBe('0.11.0');
    expect(out.model.backend).toBe('lm-studio');
    expect(out.model.active_model).toBe('gemma-local');
    expect(out.model.configured_model).toBe('gemma-local');
    expect(out.model.resident_models).toEqual([{ provider: 'lm-studio', id: 'gemma-local' }]);
    expect(out.model.residency_state).toBe('known');
    expect(out.model.active_provider).toBe('lm-studio');
    expect(out.model.route).toBe('local');
    expect(commandCenterModelLabel(out.model)).toBe('gemma-local · loaded');
    expect(
      commandCenterModelLabel({
        ...out.model,
        resident_models: [],
      }),
    ).toBe('gemma-local · configured, not loaded');
    expect(
      commandCenterModelLabel({
        ...out.model,
        backend: 'gemini',
        active_provider: 'gemini',
        route: 'cloud',
        active_model: 'gemini-2.5-flash',
        configured_model: null,
        resident_models: [],
        residency_state: 'offline',
      }),
    ).toBe('gemini-2.5-flash · cloud ready');
    expect(
      commandCenterModelLabel({
        ...out.model,
        backend: 'none',
        active_provider: null,
        route: 'not-cloud',
        active_model: 'route-trap',
        configured_model: null,
        resident_models: [],
        residency_state: 'unknown',
      }),
    ).toBe('route-trap · residency unknown');
    expect(
      commandCenterModelLabel({
        ...out.model,
        backend: 'gemini',
        active_provider: 'gemini',
        route: 'not-cloud',
        active_model: 'provider-trap',
        configured_model: null,
        resident_models: [],
        residency_state: 'unknown',
      }),
    ).toBe('provider-trap · residency unknown');
    expect(
      commandCenterModelLabel({
        ...out.model,
        active_model: null,
        configured_model: 'offline-model',
        resident_models: [],
        residency_state: 'offline',
        ready: false,
      }),
    ).toBe('offline-model · configured, not loaded');
    expect(
      commandCenterModelLabel({
        ...out.model,
        route: 'not-local',
      }),
    ).toBe('gemma-local · configured, not loaded');
    expect(
      commandCenterModelLabel({
        ...out.model,
        backend: 'gemini',
        active_provider: 'gemini',
        route: 'cloud',
        active_model: ' none ',
        configured_model: null,
        resident_models: [{ provider: 'gemini', id: 'none' }],
      }),
    ).toBe('no runnable model');
    expect(
      commandCenterModelLabel({
        ...out.model,
        active_model: null,
        configured_model: 'none',
        resident_models: [],
        ready: false,
      }),
    ).toBe('no runnable model');
    expect(
      commandCenterModelLabel({
        ...out.model,
        active_model: 'qwen3.5:0.8b',
        configured_model: 'minimax/minimax-m2.7',
        resident_models: [{ provider: 'ollama', id: 'qwen3.5:0.8b' }],
      }),
    ).toBe('minimax/minimax-m2.7 · configured, not loaded');
    expect(out.wizard.completed).toEqual(['intro']);
    expect(out.wizard.steps.length).toBe(2);
    expect(out.first_actions.length).toBe(2);
    expect(out.first_actions[0].ready).toBe(true);
    expect(out.first_actions[1].ready).toBe(false);
    expect(out.first_actions[1].reason).toContain('no folder configured');

    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        model: {
          backend: 'claude',
          active_model: 'claude-sonnet-4',
          configured_model: null,
          resident_models: [],
          residency_state: 'offline',
          active_provider: 'claude',
          route: 'claude',
          ready: true,
          cloud_configured: true,
        },
      }),
    );
    const cloud = await fetchCommandCenter(config);
    expect(cloud.model.active_provider).toBe('claude');
    expect(cloud.model.route).toBe('claude');
    expect(commandCenterModelLabel(cloud.model)).toBe('claude-sonnet-4 · cloud ready');

    const oversizedResidents = Array.from({ length: 65 }, (_, index) => ({
      provider: 'ollama',
      id: `model-${index}`,
    }));
    Object.defineProperty(oversizedResidents, 64, {
      enumerable: true,
      get: () => {
        throw new Error('resident normalization exceeded its safety cap');
      },
    });
    mockFetch.mockResolvedValueOnce(jsonResponse({ model: { resident_models: oversizedResidents } }));
    const bounded = await fetchCommandCenter(config);
    expect(bounded.model.resident_models).toHaveLength(64);
  });

  it('normalizes the honest cold-start shape without crashing', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        install: { ready: false, version: '0.11.0', checks: {} },
        model: {
          backend: 'lm-studio',
          active_model: null,
          configured_model: 'minimax/minimax-m2.7',
          resident_models: [],
          residency_state: 'unknown',
          active_provider: 'lm-studio',
          route: null,
          ready: null,
          cloud_configured: false,
        },
        wizard: { steps: [], completed: [], complete: false, hint: null },
        first_actions: [],
      }),
    );
    const out = await fetchCommandCenter(config);
    expect(out.install.ready).toBe(false);
    expect(out.model.backend).toBe('lm-studio');
    expect(out.model.active_model).toBeNull();
    expect(out.model.configured_model).toBe('minimax/minimax-m2.7');
    expect(out.model.resident_models).toEqual([]);
    expect(out.model.residency_state).toBe('unknown');
    expect(out.model.active_provider).toBe('lm-studio');
    expect(out.model.route).toBeNull();
    expect(out.model.ready).toBeNull();
    expect(commandCenterModelLabel(out.model)).toBe('minimax/minimax-m2.7 · residency unknown');
    expect(commandCenterModelLabel({ ...out.model, residency_state: 'known', ready: false })).toBe(
      'minimax/minimax-m2.7 · configured, not loaded',
    );
    expect(out.first_actions).toEqual([]);
  });

  it('tolerates a malformed payload by degrading to safe empties', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        nonsense: true,
        model: {
          backend: 'none',
          active_model: ' none ',
          configured_model: 'none',
          resident_models: [{ provider: 'gemini', id: 'none' }],
          active_provider: { malformed: true },
          route: 42,
          ready: true,
        },
      }),
    );
    const out = await fetchCommandCenter(config);
    expect(out.install.ready).toBe(false);
    expect(out.model.backend).toBe('none');
    expect(out.model.configured_model).toBeNull();
    expect(out.model.resident_models).toEqual([]);
    expect(out.model.residency_state).toBe('unknown');
    expect(out.model.active_provider).toBeNull();
    expect(out.model.route).toBeNull();
    expect(commandCenterModelLabel(out.model)).toBe('no runnable model');
    expect(out.wizard.steps).toEqual([]);
    expect(out.first_actions).toEqual([]);
  });
});
