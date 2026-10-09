import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchSessions, resumeSession } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const originalFetch = globalThis.fetch;

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  globalThis.fetch = mockFetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('mobile session history API', () => {
  it('uses an admin-only credential for list and resume, preserving the requested ID', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ sessions: [{ id: 'case_ID-123' }] }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, session: 'case_ID-123', turns: [] }));
    const config = { baseUrl: 'http://hub.local', token: '', adminToken: ' owner-secret ' };

    expect(await fetchSessions(config)).toEqual([{ id: 'case_ID-123' }]);
    expect(await resumeSession(config, 'case_ID-123')).toEqual({
      ok: true, session: 'case_ID-123', turns: [],
    });

    expect(mockFetch).toHaveBeenNthCalledWith(1, 'http://hub.local/sessions', expect.objectContaining({
      method: 'GET',
      headers: expect.objectContaining({ 'X-Admin-Token': 'owner-secret' }),
    }));
    expect(mockFetch).toHaveBeenNthCalledWith(2, 'http://hub.local/sessions/resume', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'X-Admin-Token': 'owner-secret' }),
      body: JSON.stringify({ session_id: 'case_ID-123' }),
    }));
  });

  it('retains user and admin credentials together for both History requests', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ sessions: [] }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, session: 'thread_9', turns: [] }));
    const config = { baseUrl: 'http://hub.local', token: ' user-secret ', adminToken: ' owner-secret ' };

    await fetchSessions(config);
    await resumeSession(config, 'thread_9');

    for (const [, init] of mockFetch.mock.calls) {
      expect(init?.headers).toEqual(expect.objectContaining({
        'X-User-Token': 'user-secret',
        'X-Admin-Token': 'owner-secret',
      }));
    }
  });
});
