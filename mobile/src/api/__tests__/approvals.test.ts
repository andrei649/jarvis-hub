import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { decideApproval, fetchApprovals } from '../client';

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

describe('mobile approval API', () => {
  it('fetches the unified autonomy approval queue with admin auth', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      pending: [{ id: 7, title: 'Send draft', risk_tier: 2, reversible: false }],
      irreversible: [{ id: 7 }],
      counts: { total: 1, reversible: 0, irreversible: 1 },
    }));

    const out = await fetchApprovals({
      baseUrl: '192.168.1.20:8080/',
      token: 'user-token',
      adminToken: 'admin-token',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/autonomy/approvals',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'X-User-Token': 'user-token',
          'X-Admin-Token': 'admin-token',
        }),
      }),
    );
    expect(out.pending).toHaveLength(1);
    expect(out.counts.total).toBe(1);
    expect(out.reversible).toEqual([]);
  });

  it('normalizes sparse approval payloads to stable arrays and counts', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    const out = await fetchApprovals({ baseUrl: 'hub.local', token: '', adminToken: 'adm' });

    expect(out).toEqual({
      pending: [],
      reversible: [],
      irreversible: [],
      counts: { total: 0, reversible: 0, irreversible: 0 },
    });
  });

  it('posts approval decisions to the task decision endpoint', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, task: { id: 42, status: 'approved' } }));

    const out = await decideApproval(
      { baseUrl: 'http://jarvis.lan', token: '', adminToken: 'adm' },
      42,
      'accept',
    );

    expect(mockFetch).toHaveBeenCalledWith(
      'http://jarvis.lan/autonomy/tasks/42/decision',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-Admin-Token': 'adm' }),
        body: JSON.stringify({ action: 'accept' }),
      }),
    );
    expect(out.task?.status).toBe('approved');
  });
});
