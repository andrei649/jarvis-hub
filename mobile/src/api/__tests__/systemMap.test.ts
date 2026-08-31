import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchSystemMap } from '../client';

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

const config = { baseUrl: 'hub.local', token: 'user-token', adminToken: '' };

describe('mobile Live System Map API (H34.7 / M6)', () => {
  it('fetches /api/system-map with user auth and joins topology labels to statuses', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        version: 1,
        topology_version: '2026-08-31',
        initialized: true,
        topology: {
          nodes: [
            { id: 'orch', label: 'Orchestrator' },
            { id: 'local', label: 'Local LLM' },
            { id: 'cloud', label: 'Cloud LLM' },
          ],
        },
        nodes: {
          orch: { status: 'ok', stats: { agents: 18 } },
          local: { status: 'attention', stats: { available: false } },
          cloud: { status: 'off', stats: {} },
        },
        edges: {},
      }),
    );

    const out = await fetchSystemMap(config);

    expect(mockFetch).toHaveBeenCalledWith(
      'http://hub.local/api/system-map',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-User-Token': 'user-token' }),
      }),
    );
    expect(out).toEqual({
      topology_version: '2026-08-31',
      initialized: true,
      nodes: [
        { id: 'orch', label: 'Orchestrator', status: 'ok' },
        { id: 'local', label: 'Local LLM', status: 'attention' },
        { id: 'cloud', label: 'Cloud LLM', status: 'off' },
      ],
    });
  });

  it('unknown never renders green: a missing or invalid status normalizes to unknown', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        topology_version: '2026-08-31',
        initialized: true,
        topology: { nodes: [{ id: 'memory', label: 'Memory' }, { id: 'kernel', label: 'Action Kernel' }] },
        nodes: { kernel: { status: 'green-forever' } }, // memory absent, kernel invalid
      }),
    );

    const out = await fetchSystemMap(config);
    expect(out.nodes).toEqual([
      { id: 'memory', label: 'Memory', status: 'unknown' },
      { id: 'kernel', label: 'Action Kernel', status: 'unknown' },
    ]);
  });

  it('degrades honestly on a malformed feed', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ nodes: 'nope' }));
    await expect(fetchSystemMap(config)).resolves.toEqual({
      topology_version: '',
      initialized: false,
      nodes: [],
    });
  });
});
