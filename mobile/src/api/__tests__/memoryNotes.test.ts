import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchMemory, fetchNotes } from '../client';

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

describe('mobile memory and notes API', () => {
  it('fetches recent memory turns with user auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        session: 'sess-1',
        turns: [
          { role: 'user', content: 'hello', timestamp: '2026-07-05T10:00:00Z' },
          { role: 'assistant', content: 'hi', agent_id: 'jarvis' },
        ],
      }),
    );

    const out = await fetchMemory({
      baseUrl: '192.168.1.20:8080/',
      token: 'user-token',
      adminToken: 'admin-token',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/memory',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'X-User-Token': 'user-token',
        }),
      }),
    );
    expect(out).toEqual({
      session: 'sess-1',
      turns: [
        { role: 'user', content: 'hello', timestamp: '2026-07-05T10:00:00Z' },
        { role: 'assistant', content: 'hi', agent_id: 'jarvis' },
      ],
    });
  });

  it('fetches session notes with user auth', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ session: 'sess-2', content: 'remember the launch plan' }));

    const out = await fetchNotes({
      baseUrl: 'http://jarvis.lan',
      token: 'tok',
      adminToken: '',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://jarvis.lan/api/notes',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-User-Token': 'tok' }),
      }),
    );
    expect(out).toEqual({ session: 'sess-2', content: 'remember the launch plan' });
  });

  it('normalizes sparse memory and notes payloads', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ session: 42, turns: 'bad' }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ content: 123 }));

    const memory = await fetchMemory({ baseUrl: 'hub.local', token: '', adminToken: '' });
    const notes = await fetchNotes({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(memory).toEqual({ session: '42', turns: [] });
    expect(notes).toEqual({ content: '' });
  });
});
