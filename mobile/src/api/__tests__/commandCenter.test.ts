import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchCommandCenter } from '../client';

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
        model: { backend: 'lmstudio', active_model: 'gemma-local', ready: true, cloud_configured: false },
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
    expect(out.model.backend).toBe('lmstudio');
    expect(out.model.active_model).toBe('gemma-local');
    expect(out.wizard.completed).toEqual(['intro']);
    expect(out.wizard.steps.length).toBe(2);
    expect(out.first_actions.length).toBe(2);
    expect(out.first_actions[0].ready).toBe(true);
    expect(out.first_actions[1].ready).toBe(false);
    expect(out.first_actions[1].reason).toContain('no folder configured');
  });

  it('normalizes the honest cold-start shape without crashing', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        install: { ready: false, version: '0.11.0', checks: {} },
        model: { backend: 'none', active_model: null, ready: null, cloud_configured: false },
        wizard: { steps: [], completed: [], complete: false, hint: null },
        first_actions: [],
      }),
    );
    const out = await fetchCommandCenter(config);
    expect(out.install.ready).toBe(false);
    expect(out.model.backend).toBe('none');
    expect(out.model.active_model).toBeNull();
    expect(out.model.ready).toBeNull();
    expect(out.first_actions).toEqual([]);
  });

  it('tolerates a malformed payload by degrading to safe empties', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ nonsense: true }));
    const out = await fetchCommandCenter(config);
    expect(out.install.ready).toBe(false);
    expect(out.model.backend).toBe('none');
    expect(out.wizard.steps).toEqual([]);
    expect(out.first_actions).toEqual([]);
  });
});
