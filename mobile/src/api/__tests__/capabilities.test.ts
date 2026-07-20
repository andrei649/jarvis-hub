import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchCapabilities } from '../client';

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

describe('mobile capability registry API (H18.22 / H27.8)', () => {
  it('fetches the read-only capability registry with user auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        capabilities: [
          {
            id: 'weather.today',
            kind: 'plugin',
            state: 'wired',
            owner_agent: 'jarvis',
            description: 'Local weather lookup',
            risk: 'read_only',
            confidence: 0.8,
            supports: ['weather'],
          },
        ],
        total: 1,
        by_state: { missing: 0, seam: 0, wired: 1, verified: 0, ga: 0 },
        harness_pending: true,
      }),
    );

    const out = await fetchCapabilities({
      baseUrl: '192.168.1.20:8080/',
      token: 'user-token',
      adminToken: 'admin-token',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/api/capabilities',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'X-User-Token': 'user-token',
        }),
      }),
    );
    expect(out).toEqual({
      capabilities: [
        {
          id: 'weather.today',
          kind: 'plugin',
          state: 'wired',
          ownerAgent: 'jarvis',
          description: 'Local weather lookup',
          risk: 'read_only',
          confidence: 0.8,
          supports: ['weather'],
        },
      ],
      total: 1,
      byState: { missing: 0, seam: 0, wired: 1, verified: 0, ga: 0 },
      harnessPending: true,
    });
  });

  it('drops malformed capability entries and defaults missing fields', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        capabilities: [
          { id: 'bare.cap' },
          { kind: 'plugin' }, // no id -> dropped
          'not-an-object', // dropped
        ],
        total: 3,
      }),
    );

    const out = await fetchCapabilities({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(out.capabilities).toEqual([
      {
        id: 'bare.cap',
        kind: '',
        state: 'seam',
        ownerAgent: '',
        description: '',
        risk: 'read_only',
        confidence: 0,
        supports: [],
      },
    ]);
    expect(out.total).toBe(3);
    expect(out.byState).toEqual({});
    // No harness_pending in the payload -> honest default is "pending" (never claim
    // proven when the field is absent), matching the backend's own honesty contract.
    expect(out.harnessPending).toBe(true);
  });

  it('normalizes a sparse/empty payload to a stable shape', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    const out = await fetchCapabilities({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(out).toEqual({ capabilities: [], total: 0, byState: {}, harnessPending: true });
  });
});
